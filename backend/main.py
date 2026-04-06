"""FastAPI: API REST, CORS e arquivos estáticos do dashboard na mesma origem."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.models.database import init_db
from backend.routes import auth_session, checkin, devices, history

# Diretório do projeto (pasta que contém backend/ e dashboard/)
ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = ROOT / "dashboard"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Cadê Você",
    description="Rastreamento de notebooks corporativos por geolocalização de IP",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_session.router)
app.include_router(checkin.router)
app.include_router(devices.router)
app.include_router(history.router)


@app.get("/")
async def dashboard_index():
    """Serve a SPA do dashboard."""
    index = DASHBOARD_DIR / "index.html"
    if not index.is_file():
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse("dashboard/index.html não encontrado", status_code=404)
    return FileResponse(index)


# CSS/JS na raiz: o index é servido em "/" — href="style.css" resolve para cá e também
# funciona se alguém abrir dashboard/index.html pelo disco (file://) com style.css na mesma pasta.
@app.get("/style.css", include_in_schema=False)
async def dashboard_style():
    from fastapi.responses import PlainTextResponse

    p = DASHBOARD_DIR / "style.css"
    if not p.is_file():
        return PlainTextResponse("style.css não encontrado", status_code=404)
    return FileResponse(p, media_type="text/css")


@app.get("/app.js", include_in_schema=False)
async def dashboard_app_js():
    from fastapi.responses import PlainTextResponse

    p = DASHBOARD_DIR / "app.js"
    if not p.is_file():
        return PlainTextResponse("app.js não encontrado", status_code=404)
    return FileResponse(p, media_type="application/javascript")


def _file_response_or_404(rel: str, media: str):
    """FileResponse a partir de DASHBOARD_DIR / rel (para rotas /static/... explícitas)."""
    from fastapi.responses import PlainTextResponse

    p = DASHBOARD_DIR / rel
    if not p.is_file():
        return PlainTextResponse(f"{rel} não encontrado", status_code=404)
    return FileResponse(p, media_type=media)


# Rotas explícitas ANTES do mount: garantem CSS/JS das páginas em /static/*.html
# (evita falha silenciosa do estilo em alguns ambientes com StaticFiles).
@app.get("/static/style.css", include_in_schema=False)
async def static_dashboard_css():
    return _file_response_or_404("style.css", "text/css; charset=utf-8")


@app.get("/static/history.js", include_in_schema=False)
async def static_history_js():
    return _file_response_or_404("history.js", "application/javascript; charset=utf-8")


@app.get("/static/violations.js", include_in_schema=False)
async def static_violations_js():
    return _file_response_or_404("violations.js", "application/javascript; charset=utf-8")


app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")
