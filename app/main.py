from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.config import APP_NAME, DATABASE_PATH, SECRET_KEY, UPLOAD_DIR
from app.database import db_session, init_db
from app.routers.admin import router as admin_router
from app.routers.admin_governance import router as governance_router
from app.routers.catalog import router as catalog_router

APP_DIR = Path(__file__).resolve().parent
error_templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


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
app.include_router(governance_router)


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Tangani 404/403 (termasuk route yang tidak cocok) dengan halaman HTML kustom."""
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    if exc.status_code in (403, 404):
        return error_templates.TemplateResponse(
            request=request,
            name=f"errors/{exc.status_code}.html",
            context={"app_name": APP_NAME, "detail": exc.detail},
            status_code=exc.status_code,
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


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
