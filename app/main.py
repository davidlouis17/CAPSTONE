from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import APP_NAME, DATABASE_PATH, UPLOAD_DIR
from app.database import db_session, init_db

APP_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(title=APP_NAME, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


@app.get("/health", response_class=JSONResponse)
def health_check():
    with db_session() as conn:
        shoe_count = conn.execute("SELECT COUNT(*) AS cnt FROM shoes").fetchone()["cnt"]
        active_rule = conn.execute(
            "SELECT version FROM system_rules WHERE is_active = 1 ORDER BY version DESC LIMIT 1"
        ).fetchone()
    return {
        "status": "ok",
        "app": APP_NAME,
        "database": DATABASE_PATH.name,
        "total_shoes": shoe_count,
        "active_rule_version": active_rule["version"] if active_rule else None,
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with db_session() as conn:
        stats = {
            "total_shoes": conn.execute("SELECT COUNT(*) AS cnt FROM shoes").fetchone()["cnt"],
            "published_shoes": conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM shoes s
                JOIN evaluations e ON e.product_id = s.product_id
                WHERE s.process_status = 'published' AND e.final_grade != 'D'
                """
            ).fetchone()["cnt"],
            "pending_review": conn.execute(
                "SELECT COUNT(*) AS cnt FROM shoes WHERE process_status = 'pending_review'"
            ).fetchone()["cnt"],
            "active_rule": conn.execute(
                "SELECT version FROM system_rules WHERE is_active = 1 ORDER BY version DESC LIMIT 1"
            ).fetchone(),
        }

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": APP_NAME,
            "stats": stats,
        },
    )
