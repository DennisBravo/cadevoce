"""GET /devices, GET /violations e POST /devices (cadastro de dispositivos)."""

from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from backend.models.database import (
    AsyncSessionLocal,
    Checkin,
    CheckinStatus,
    Device,
    ViolationWindow,
)
from backend.routes.auth_session import require_api_key_or_browser_session

router = APIRouter(tags=["devices"])


class DeviceCreate(BaseModel):
    hostname: str = Field(..., max_length=255)
    username: str = Field(..., max_length=255)
    estado_permitido: str = Field(..., max_length=64, description="Ex.: SP, RJ (BR) ou código de região do ipinfo")
    update_estado_if_exists: bool = Field(
        False,
        description="Se true, atualiza estado_permitido quando hostname+usuário já existem; "
        "se false (padrão), mantém o cadastro existente (uso do agente).",
    )


class DeviceRow(BaseModel):
    hostname: str
    username: str
    ip: str | None
    country: str | None
    region: str | None
    city: str | None
    lat: float | None
    lon: float | None
    status: str | None
    last_seen: datetime | None
    vpn_detected: bool | None
    estado_permitido: str
    source: str | None = "ip"
    accuracy: float | None = None
    last_boot_utc: datetime | None = None
    uptime_seconds: float | None = None
    os_caption: str | None = None
    mac_address: str | None = None
    machine_serial: str | None = None

    model_config = {"from_attributes": False}


class ViolationRow(BaseModel):
    hostname: str
    username: str
    ip: str
    country: str | None
    region: str | None
    city: str | None
    estado_permitido: str
    timestamp: datetime


@router.post("/devices", response_model=dict)
async def register_device(body: DeviceCreate):
    """Cria ou atualiza o estado permitido de um dispositivo (hostname + usuário únicos)."""
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(Device).where(
                Device.hostname == body.hostname.strip(),
                Device.username == body.username.strip(),
            )
        )
        existing = r.scalar_one_or_none()
        if existing:
            if body.update_estado_if_exists:
                existing.estado_permitido = body.estado_permitido.strip()
            await session.commit()
            return {
                "ok": True,
                "id": existing.id,
                "updated": bool(body.update_estado_if_exists),
            }

        d = Device(
            hostname=body.hostname.strip(),
            username=body.username.strip(),
            estado_permitido=body.estado_permitido.strip(),
        )
        session.add(d)
        try:
            await session.commit()
            await session.refresh(d)
        except IntegrityError as e:
            await session.rollback()
            raise HTTPException(status_code=409, detail="Conflito ao cadastrar dispositivo") from e
        return {"ok": True, "id": d.id, "updated": False}


@router.get("/devices", response_model=list[DeviceRow])
async def list_devices():
    """Último check-in de cada dispositivo cadastrado."""
    async with AsyncSessionLocal() as session:
        subq = (
            select(Checkin.device_id, func.max(Checkin.timestamp).label("max_ts"))
            .group_by(Checkin.device_id)
            .subquery()
        )

        stmt = (
            select(Checkin, Device)
            .join(Device, Checkin.device_id == Device.id)
            .join(
                subq,
                (Checkin.device_id == subq.c.device_id)
                & (Checkin.timestamp == subq.c.max_ts),
            )
        )
        rows = (await session.execute(stmt)).all()

        out: list[DeviceRow] = []
        for checkin, device in rows:
            out.append(
                DeviceRow(
                    hostname=device.hostname,
                    username=device.username,
                    ip=checkin.ip or None,
                    country=checkin.country,
                    region=checkin.region,
                    city=checkin.city,
                    lat=checkin.lat,
                    lon=checkin.lon,
                    status=checkin.status.value,
                    last_seen=checkin.timestamp,
                    vpn_detected=checkin.vpn_detected,
                    estado_permitido=device.estado_permitido,
                    source=checkin.source or "ip",
                    accuracy=checkin.accuracy,
                    last_boot_utc=checkin.last_boot_utc,
                    uptime_seconds=checkin.uptime_seconds,
                    os_caption=checkin.os_caption,
                    mac_address=checkin.mac_address,
                    machine_serial=checkin.machine_serial,
                )
            )

        # Dispositivos sem nenhum check-in ainda
        r_all = await session.execute(select(Device))
        devices = r_all.scalars().all()
        seen_ids = {device.id for _, device in rows}
        for d in devices:
            if d.id not in seen_ids:
                out.append(
                    DeviceRow(
                        hostname=d.hostname,
                        username=d.username,
                        ip=None,
                        country=None,
                        region=None,
                        city=None,
                        lat=None,
                        lon=None,
                        status=None,
                        last_seen=None,
                        vpn_detected=None,
                        estado_permitido=d.estado_permitido,
                        source=None,
                        accuracy=None,
                        last_boot_utc=None,
                        uptime_seconds=None,
                    )
                )

        return out


def _day_bounds_utc(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, tzinfo=timezone.utc)
    end = datetime.combine(d, time.max, tzinfo=timezone.utc)
    return start, end


@router.get("/violations", response_model=list[ViolationRow])
async def list_violations(
    username: str | None = Query(None, description="Filtrar por usuário Windows"),
    date_from: date | None = Query(None, description="Data inicial (UTC), inclusive"),
    date_to: date | None = Query(None, description="Data final (UTC), inclusive"),
):
    """Histórico de check-ins com status violação."""
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Checkin, Device)
            .join(Device, Checkin.device_id == Device.id)
            .where(Checkin.status == CheckinStatus.violation)
            .order_by(Checkin.timestamp.desc())
        )
        if username:
            stmt = stmt.where(Device.username == username.strip())
        if date_from:
            df, _ = _day_bounds_utc(date_from)
            stmt = stmt.where(Checkin.timestamp >= df)
        if date_to:
            _, dt_end = _day_bounds_utc(date_to)
            stmt = stmt.where(Checkin.timestamp <= dt_end)

        result = await session.execute(stmt)
        rows = result.all()
        return [
            ViolationRow(
                hostname=device.hostname,
                username=device.username,
                ip=c.ip,
                country=c.country,
                region=c.region,
                city=c.city,
                estado_permitido=device.estado_permitido,
                timestamp=c.timestamp,
            )
            for c, device in rows
        ]


@router.delete(
    "/devices",
    response_model=dict,
    dependencies=[Depends(require_api_key_or_browser_session)],
)
async def delete_device(hostname: str, username: str):
    """Remove um dispositivo e todos os seus check-ins."""
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(Device).where(
                Device.hostname == hostname.strip(),
                Device.username == username.strip(),
            )
        )
        device = r.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail="Dispositivo não encontrado")
        await session.execute(
            delete(ViolationWindow).where(ViolationWindow.device_id == device.id)
        )
        await session.execute(delete(Checkin).where(Checkin.device_id == device.id))
        await session.delete(device)
        await session.commit()
        return {"ok": True, "deleted": f"{hostname}/{username}"}
