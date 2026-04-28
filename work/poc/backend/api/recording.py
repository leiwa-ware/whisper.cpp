import uuid
import tempfile
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from services.transcription import transcribe_audio
from services.summarizer import correct_and_summarize
from services.minutes_connector import WhisperCppAdapter
from services.vocabulary import build_initial_prompt

router = APIRouter()


@router.post("/recordings", status_code=201)
async def upload_recording(
    audio: UploadFile = File(...),
    meeting_type: str = Form("opp"),
    client_name: str = Form(""),
    owner_name: str = Form(""),
    opportunity_id: str = Form(""),
    industry: str = Form("sales"),
):
    """音声ファイルを受信し、転写→要約→minutesMarkdown を返す。"""
    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name

    try:
        # 業界別語彙と固有名詞を自然文形式の --prompt として渡す。
        # コンマ区切り単語リストはデコーダーを混乱させるため使用しない。
        initial_prompt = build_initial_prompt(
            meeting_type=meeting_type,
            client_name=client_name,
            owner_name=owner_name,
            industry=industry,
        )
        context = " ".join(filter(None, [client_name, owner_name]))
        transcription = transcribe_audio(tmp_path, language="ja", initial_prompt=initial_prompt)

        # 誤認識補正 + 要約を 1 回の LLM 呼び出しで実行（メモリ節約・高速化）
        corrected_text, summary = correct_and_summarize(
            transcription.text, meeting_type=meeting_type, context=context
        )

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
            "raw_transcript": corrected_text,        # 補正済みを表示・保存に使用
            "raw_transcript_original": transcription.text,  # 元の認識結果（デバッグ用）
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
