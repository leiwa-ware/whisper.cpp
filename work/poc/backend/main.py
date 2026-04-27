import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from db.database import init_db
from api.recording import router as recording_router
from api.minutes import router as minutes_router
from api.webhooks import router as webhooks_router
from api.realtime import router as realtime_router
from config import WHISPER_SERVER_BIN, WHISPER_SERVER_PORT, WHISPER_MODEL

_UI_DIR = Path(__file__).parent.parent.parent / "UIMock"
_log = logging.getLogger("poc.whisper_server")


async def _start_whisper_server() -> asyncio.subprocess.Process | None:
    """whisper-server を起動し、ready になるまで待つ。失敗時は None を返す。"""
    bin_path = Path(WHISPER_SERVER_BIN)
    if not bin_path.exists():
        _log.warning("whisper-server not found at %s — realtime transcription disabled", bin_path)
        return None

    proc = await asyncio.create_subprocess_exec(
        str(bin_path),
        "-m", WHISPER_MODEL,
        "-l", "ja",
        "--host", "127.0.0.1",
        "--port", str(WHISPER_SERVER_PORT),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    # ポートが Listen されるまで最大 10 秒待機
    url = f"http://127.0.0.1:{WHISPER_SERVER_PORT}/"
    async with httpx.AsyncClient() as client:
        for _ in range(20):
            await asyncio.sleep(0.5)
            try:
                await client.get(url, timeout=1.0)
                _log.info("whisper-server ready on port %d", WHISPER_SERVER_PORT)
                return proc
            except Exception:
                pass
    _log.error("whisper-server did not become ready in 10 s")
    proc.terminate()
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    ws_proc = await _start_whisper_server()
    yield
    if ws_proc:
        ws_proc.terminate()
        await ws_proc.wait()


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
app.include_router(realtime_router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Must be last: catch-all mount intercepts any path not matched above
if _UI_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")
