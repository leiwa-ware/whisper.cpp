from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from db.database import init_db
from api.recording import router as recording_router
from api.minutes import router as minutes_router
from api.webhooks import router as webhooks_router

_UI_DIR = Path(__file__).parent.parent.parent / "UIMock"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="PoC Meeting Recording API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # PoC のみ。本番では制限する
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recording_router, prefix="/api")
app.include_router(minutes_router, prefix="/api")
app.include_router(webhooks_router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Must be last: catch-all mount intercepts any path not matched above
if _UI_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")
