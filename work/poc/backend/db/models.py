from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Meeting(Base):
    __tablename__ = "meetings"
    id = Column(String(100), primary_key=True)
    type = Column(String(20), nullable=False)   # "opp" | "visit"
    client_name = Column(String(200))
    owner_name = Column(String(100))
    phase = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)


class Minutes(Base):
    __tablename__ = "minutes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(String(100), nullable=False, index=True)
    source_type = Column(String(20), nullable=False)  # "whisper_cpp" | "m365" | "manual"
    raw_transcript = Column(Text)
    minutes_markdown = Column(Text, nullable=False)
    summary_topics = Column(Text)    # JSON string
    summary_actions = Column(Text)   # JSON string
    summary_risks = Column(Text)     # JSON string
    created_at = Column(DateTime, default=datetime.utcnow)
