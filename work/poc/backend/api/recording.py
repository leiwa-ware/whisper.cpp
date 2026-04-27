import uuid
import tempfile
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from services.transcription import transcribe_audio
from services.summarizer import summarize_transcript
from services.minutes_connector import WhisperCppAdapter

router = APIRouter()


@router.post("/recordings", status_code=201)
async def upload_recording(
    audio: UploadFile = File(...),
    meeting_type: str = Form("opp"),
    client_name: str = Form(""),
    owner_name: str = Form(""),
    opportunity_id: str = Form(""),
):
    """音声ファイルを受信し、転写→要約→minutesMarkdown を返す。"""
    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name

    try:
        # 得意先名・担当者名をプロンプトに含めると固有名詞の認識精度が上がる
        prompt = ", ".join(filter(None, [client_name, owner_name]))
        transcription = transcribe_audio(tmp_path, language="ja", initial_prompt=prompt)
        summary = summarize_transcript(transcription.text, meeting_type=meeting_type)

        participants = [p.strip() for p in owner_name.split(",") if p.strip()]
        opp_id = opportunity_id or f"OPP-{uuid.uuid4().hex[:6].upper()}"
        adapter = WhisperCppAdapter(
            raw_transcript=transcription.text,
            opportunity_id=opp_id,
            participants=participants,
        )

        return {
            "meeting_id": opp_id,
            "source_type": "whisper_cpp",
            "raw_transcript": transcription.text,
            "minutes_markdown": adapter.to_markdown(),
            "summary": {
                "topics": summary.topics,
                "actions": [
                    {"text": a.text, "assignee": a.assignee, "due": a.due, "urgent": a.urgent}
                    for a in summary.actions
                ],
                "risks": summary.risks,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)
