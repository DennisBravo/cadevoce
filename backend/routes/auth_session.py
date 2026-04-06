"""Sessão do dashboard: cookie HttpOnly após validar API_SECRET_KEY (sem chave fixa no front)."""

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.services.browser_session import (
    BROWSER_COOKIE_NAME,
    DEFAULT_TTL_SECONDS,
    create_browser_cookie_value,
    verify_browser_cookie,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class BrowserLoginBody(BaseModel):
    api_key: str = Field(..., min_length=1, description="Mesmo valor de API_SECRET_KEY / agente")


async def require_api_key_or_browser_session(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    browser_session: str | None = Cookie(None, alias=BROWSER_COOKIE_NAME),
):
    """
    Agentes: header X-API-Key.
    Dashboard: cookie HttpOnly emitido por POST /auth/browser/login.
    """
    settings = get_settings()
    secret = settings.api_secret_key
    if x_api_key and x_api_key == secret:
        return "agent"
    if browser_session and verify_browser_cookie(browser_session, secret):
        return "browser"
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="X-API-Key ou sessão do navegador inválida ou ausente",
    )


@router.post("/browser/login")
async def browser_login(body: BrowserLoginBody, response: Response):
    settings = get_settings()
    if body.api_key != settings.api_secret_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chave inválida",
        )
    val = create_browser_cookie_value(
        settings.api_secret_key,
        ttl_seconds=DEFAULT_TTL_SECONDS,
    )
    response.set_cookie(
        key=BROWSER_COOKIE_NAME,
        value=val,
        max_age=DEFAULT_TTL_SECONDS,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return {"ok": True}


@router.post("/browser/logout")
async def browser_logout(response: Response):
    settings = get_settings()
    response.delete_cookie(
        key=BROWSER_COOKIE_NAME,
        path="/",
        secure=settings.cookie_secure,
        samesite="lax",
        httponly=True,
    )
    return {"ok": True}


@router.get("/browser/me")
async def browser_me(
    browser_session: str | None = Cookie(None, alias=BROWSER_COOKIE_NAME),
):
    settings = get_settings()
    ok = bool(
        browser_session
        and verify_browser_cookie(browser_session, settings.api_secret_key)
    )
    return {"authenticated": ok}
