from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from db.models import Base
from config import DB_PATH

engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
