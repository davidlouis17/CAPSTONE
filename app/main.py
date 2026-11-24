from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import APP_NAME, DATABASE_PATH, SECRET_KEY, UPLOAD_DIR
from app.database import db_session, init_db
from app.routers.admin import router as admin_router
from app.routers.catalog import router as catalog_router

APP_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(title=APP_NAME, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
app.include_router(catalog_router)
app.include_router(admin_router)


@app.get("/health", response_class=JSONResponse)
def health_check():
    with db_session() as conn:
        shoe_count = conn.execute("SELECT COUNT(*) AS cnt FROM shoes").fetchone()["cnt"]
        published_count = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM shoes s
            JOIN evaluations e ON e.product_id = s.product_id
            WHERE s.process_status = 'published' AND e.final_grade != 'D'
            """
        ).fetchone()["cnt"]
        active_rule = conn.execute(
            "SELECT version FROM system_rules WHERE is_active = 1 ORDER BY version DESC LIMIT 1"
        ).fetchone()
    return {
        "status": "ok",
        "app": APP_NAME,
        "database": DATABASE_PATH.name,
        "total_shoes": shoe_count,
        "published_shoes": published_count,
        "active_rule_version": active_rule["version"] if active_rule else None,
    }
