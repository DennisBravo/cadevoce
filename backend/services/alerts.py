"""Envio de alertas ao Microsoft Teams via Incoming Webhook."""

from datetime import datetime

import httpx

from backend.config import get_settings


async def send_violation_alert(
    hostname: str,
    username: str,
    ip: str,
    estado_detectado: str | None,
    estado_permitido: str,
    timestamp: datetime,
) -> None:
    """Envia um MessageCard simples ao canal do Teams. Ignora se webhook não estiver configurado."""
    url = get_settings().teams_webhook_url
    if not url:
        return

    ts_str = timestamp.isoformat() if timestamp.tzinfo else f"{timestamp.isoformat()}Z"
    detectado = estado_detectado or "(desconhecido)"

    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": "Cadê Você — violação de localização",
        "themeColor": "FF0000",
        "title": "Violação de estado permitido",
        "sections": [
            {
                "facts": [
                    {"name": "Hostname", "value": hostname},
                    {"name": "Usuário", "value": username},
                    {"name": "IP público", "value": ip},
                    {"name": "Estado detectado", "value": detectado},
                    {"name": "Estado permitido", "value": estado_permitido},
                    {"name": "Timestamp (UTC)", "value": ts_str},
                ]
            }
        ],
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
