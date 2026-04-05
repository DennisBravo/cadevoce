"""POST /checkin — recebe heartbeat do agente (GPS via Azure Maps ou IP via ip-api.com)."""

import logging
import traceback
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from backend.models.database import AsyncSessionLocal, Checkin, CheckinStatus, Device
from backend.services import alerts, geoip, geocoding, rules

logger = logging.getLogger(__name__)
router = APIRouter(tags=["checkin"])


class CheckinBody(BaseModel):
    hostname: str = Field(..., max_length=255)
    username: str = Field(..., max_length=255)
    timestamp: str = Field(..., description="ISO 8601 em UTC")
    source: Literal["gps", "gps_serial", "ip"] | None = Field(
        None,
        description="gps=Windows Location; gps_serial=USB NMEA; omitido=null = ip (legado)",
    )
    latitude: float | None = None
    longitude: float | None = None
    accuracy: float | None = None
    ip: str | None = Field(None, max_length=45)

    @model_validator(mode="after")
    def validar_fonte(self):
        src = self.source or "ip"
        if src == "ip":
            if self.ip is None or not str(self.ip).strip():
                raise ValueError("campo 'ip' obrigatório quando source é ip ou omitido (legado)")
        if src in ("gps", "gps_serial"):
            if self.latitude is None or self.longitude is None:
                raise ValueError(
                    "latitude e longitude obrigatórios quando source é gps ou gps_serial"
                )
        return self


def _parse_ts(raw: str) -> datetime:
    try:
        t = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"timestamp inválido: {e}") from e


async def require_api_key(x_api_key: str | None = Header(None, alias="X-API-Key")):
    from backend.config import get_settings

    if not x_api_key or x_api_key != get_settings().api_secret_key:
        raise HTTPException(status_code=401, detail="X-API-Key inválida ou ausente")


@router.post("/checkin", dependencies=[Depends(require_api_key)])
async def checkin(body: CheckinBody):
    try:
        ts = _parse_ts(body.timestamp)
        src = body.source or "ip"

        async with AsyncSessionLocal() as session:
            r = await session.execute(
                select(Device).where(
                    Device.hostname == body.hostname.strip(),
                    Device.username == body.username.strip(),
                )
            )
            device = r.scalar_one_or_none()
            if device is None:
                raise HTTPException(
                    status_code=404,
                    detail="Dispositivo não cadastrado. Cadastre em POST /devices.",
                )

            raw_lat = raw_lon = raw_acc = None
            ip_stored = ""

            if src in ("gps", "gps_serial"):
                raw_lat = body.latitude
                raw_lon = body.longitude
                raw_acc = body.accuracy
                ip_stored = (body.ip or "").strip()
                try:
                    geo = await geocoding.reverse_geocode(float(raw_lat), float(raw_lon))
                except geocoding.GeocodingError as e:
                    raise HTTPException(status_code=502, detail=str(e)) from e
            else:
                ip_stored = body.ip.strip()
                try:
                    geo = await geoip.lookup_ip(ip_stored)
                except httpx.HTTPStatusError as e:
                    raise HTTPException(
                        status_code=502,
                        detail=f"ip-api.com retornou erro HTTP {e.response.status_code}",
                    ) from e
                except httpx.RequestError as e:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Falha de rede ao consultar ip-api.com: {e!s}",
                    ) from e

            permitido = device.estado_permitido
            in_compliance = rules.region_matches(permitido, geo.region)
            status = CheckinStatus.ok if in_compliance else CheckinStatus.violation

            should_alert = await rules.apply_violation_timing(
                session, device.id, ts, in_compliance
            )

            # Mapa e trajetória: sempre as coordenadas do agente; geo só define estado/cidade.
            map_lat = float(raw_lat) if src in ("gps", "gps_serial") else geo.lat
            map_lon = float(raw_lon) if src in ("gps", "gps_serial") else geo.lon

            row = Checkin(
                device_id=device.id,
                ip=ip_stored,
                country=geo.country,
                region=geo.region,
                city=geo.city,
                lat=map_lat,
                lon=map_lon,
                timestamp=ts,
                status=status,
                vpn_detected=geo.vpn,
                source=src,
                latitude=raw_lat if src in ("gps", "gps_serial") else None,
                longitude=raw_lon if src in ("gps", "gps_serial") else None,
                accuracy=raw_acc if src in ("gps", "gps_serial") else None,
            )
            session.add(row)
            await session.commit()

            if should_alert:
                try:
                    await alerts.send_violation_alert(
                        hostname=body.hostname.strip(),
                        username=body.username.strip(),
                        ip=ip_stored or "(sem IP — GPS)",
                        estado_detectado=geo.region,
                        estado_permitido=permitido,
                        timestamp=ts,
                    )
                except Exception:
                    logger.exception("Falha ao enviar alerta ao Teams; violação já registrada.")

        return {"ok": True}
    except Exception as e:
        print(f"ERRO NO CHECKIN: {type(e).__name__}: {e}")
        traceback.print_exc()
        raise
