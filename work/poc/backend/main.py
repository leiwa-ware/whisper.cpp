import asyncio
import logging
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
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


async def _ensure_whisper_server() -> Optional[subprocess.Popen]:
    """
    whisper-server が起動済みなら何もしない。
    未起動かつバイナリがあれば Popen で起動して ready 待ち。
    管理対象プロセスを返す（外部起動済みの場合は None）。
    """
    url = f"http://127.0.0.1:{WHISPER_SERVER_PORT}/"

    # 既に起動済みかチェック
    async with httpx.AsyncClient() as client:
        try:
            await client.get(url, timeout=1.0)
            _log.info("whisper-server already running on port %d", WHISPER_SERVER_PORT)
            return None  # 外部管理なので終了時に terminate しない
        except Exception:
            pass

    # 未起動 → 自動起動を試みる
    bin_path = Path(WHISPER_SERVER_BIN)
    if not bin_path.exists():
        _log.warning("whisper-server not found at %s — realtime disabled", bin_path)
        return None

    # asyncio.create_subprocess_exec は Windows の --reload モードで
    # NotImplementedError になるため subprocess.Popen を使用する
    proc = subprocess.Popen(
        [str(bin_path), "-m", WHISPER_MODEL, "-l", "ja",
         "--host", "127.0.0.1", "--port", str(WHISPER_SERVER_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # ポートが Listen されるまで最大 10 秒待機
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
    ws_proc = await _ensure_whisper_server()
    yield
    if ws_proc:
        ws_proc.terminate()
        ws_proc.wait()


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
