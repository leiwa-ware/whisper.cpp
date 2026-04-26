import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import Minutes

router = APIRouter()


class MinutesCreate(BaseModel):
    meeting_id: str
    source_type: str
    minutes_markdown: str
    raw_transcript: str = ""
    summary_topics: list[str] = []
    summary_actions: list[dict] = []
    summary_risks: list[str] = []


@router.post("/minutes", status_code=201)
async def create_minutes(payload: MinutesCreate, db: AsyncSession = Depends(get_db)):
    record = Minutes(
        meeting_id=payload.meeting_id,
        source_type=payload.source_type,
        raw_transcript=payload.raw_transcript,
        minutes_markdown=payload.minutes_markdown,
        summary_topics=json.dumps(payload.summary_topics, ensure_ascii=False),
        summary_actions=json.dumps(payload.summary_actions, ensure_ascii=False),
        summary_risks=json.dumps(payload.summary_risks, ensure_ascii=False),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": record.id, "meeting_id": record.meeting_id, "source_type": record.source_type}


@router.get("/minutes/{minutes_id}")
async def get_minutes(minutes_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.get(Minutes, minutes_id)
    if not result:
        raise HTTPException(status_code=404, detail="Minutes not found")
    return {
        "id": result.id,
        "meeting_id": result.meeting_id,
        "source_type": result.source_type,
        "minutes_markdown": result.minutes_markdown,
        "raw_transcript": result.raw_transcript,
        "summary_topics": json.loads(result.summary_topics or "[]"),
        "summary_actions": json.loads(result.summary_actions or "[]"),
        "summary_risks": json.loads(result.summary_risks or "[]"),
        "created_at": result.created_at.isoformat() if result.created_at else None,
    }
