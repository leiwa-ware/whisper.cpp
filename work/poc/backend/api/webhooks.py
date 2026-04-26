import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import Minutes
from services.minutes_connector import M365CopilotAdapter

router = APIRouter()


class M365WebhookPayload(BaseModel):
    source: str                     # "m365_copilot" | "zoom_ai" | "manual"
    opportunity_id: str
    participants: list[str] = []
    raw_content: str


@router.post("/webhooks/minutes", status_code=201)
async def receive_minutes_webhook(
    payload: M365WebhookPayload,
    db: AsyncSession = Depends(get_db),
):
    """方式 B: 外部製品（M365 Copilot 等）からの議事録 Webhook を受信して保存する。"""
    if payload.source not in ("m365_copilot", "zoom_ai", "manual"):
        raise HTTPException(status_code=400, detail=f"Unknown source: {payload.source}")

    adapter = M365CopilotAdapter(
        raw_content=payload.raw_content,
        opportunity_id=payload.opportunity_id,
        participants=payload.participants,
    )
    minutes_md = adapter.to_markdown()

    record = Minutes(
        meeting_id=payload.opportunity_id,
        source_type="m365",
        raw_transcript=payload.raw_content,
        minutes_markdown=minutes_md,
        summary_topics=json.dumps([], ensure_ascii=False),
        summary_actions=json.dumps([], ensure_ascii=False),
        summary_risks=json.dumps([], ensure_ascii=False),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return {
        "minutes_id": record.id,
        "meeting_id": record.meeting_id,
        "source_type": record.source_type,
        "minutes_markdown": minutes_md,
    }
