"""Cookie de sessão do navegador (assinado com HMAC) para ações no dashboard sem expor a chave no HTML."""

import hashlib
import hmac
import time

BROWSER_COOKIE_NAME = "cadevoce_browser"
DEFAULT_TTL_SECONDS = 8 * 3600


def create_browser_cookie_value(secret: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    exp = int(time.time()) + ttl_seconds
    sig = hmac.new(
        secret.encode("utf-8"),
        str(exp).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{exp}:{sig}"


def verify_browser_cookie(raw: str | None, secret: str) -> bool:
    if not raw or ":" not in raw:
        return False
    exp_s, sig = raw.split(":", 1)
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if int(time.time()) > exp:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        str(exp).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, sig)
