"""GET /history — check-ins de um dispositivo em um dia (UTC), para o mapa e a tabela."""

from datetime import date, datetime, time, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from backend.models.database import AsyncSessionLocal, Checkin, Device

router = APIRouter(tags=["history"])


class HistoryRow(BaseModel):
    """Um registro de check-in no histórico diário."""

    timestamp: datetime
    lat: float | None
    lon: float | None
    source: str
    accuracy: float | None
    region: str | None
    city: str | None
    status: str


def _day_bounds_utc(d: date) -> tuple[datetime, datetime]:
    """Início e fim do dia civil em UTC (inclusive do fim)."""
    start = datetime.combine(d, time.min, tzinfo=timezone.utc)
    end = datetime.combine(d, time.max, tzinfo=timezone.utc)
    return start, end


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@router.get("/history", response_model=list[HistoryRow])
async def history_for_day(
    hostname: str = Query(..., description="Hostname do dispositivo"),
    username: str = Query(..., description="Usuário Windows"),
    date: date | None = Query(
        None,
        description="Dia civil em UTC (YYYY-MM-DD). Ignorado se start e end forem enviados.",
    ),
    start: datetime | None = Query(
        None,
        description="Início do intervalo em UTC (ISO 8601). Use com end para o dia local do navegador.",
    ),
    end: datetime | None = Query(
        None,
        description="Fim exclusivo do intervalo em UTC (ISO 8601).",
    ),
):
    """
    Lista check-ins do dispositivo no período, ordenados por timestamp crescente.

    Preferencialmente envie ``start`` e ``end`` (fim exclusivo) calculados no cliente para o
    **dia civil local** — assim check-ins batem com o que o usuário escolhe no calendário.
    Se só ``date`` for enviado, o intervalo é o dia inteiro em **UTC** (comportamento antigo).
    """
    hn = hostname.strip()
    un = username.strip()
    if not hn or not un:
        raise HTTPException(status_code=400, detail="hostname e username são obrigatórios")

    if start is not None and end is not None:
        start_utc = _as_utc(start)
        end_utc = _as_utc(end)
        if start_utc >= end_utc:
            raise HTTPException(
                status_code=400,
                detail="start deve ser anterior a end (end é exclusivo)",
            )
        range_start, range_end = start_utc, end_utc
        use_exclusive_end = True
    elif date is not None:
        range_start, range_end = _day_bounds_utc(date)
        use_exclusive_end = False
    else:
        raise HTTPException(
            status_code=400,
            detail="Informe o par date (dia UTC) ou start e end (intervalo UTC, end exclusivo).",
        )

    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(Device).where(Device.hostname == hn, Device.username == un)
        )
        device = r.scalar_one_or_none()
        if device is None:
            raise HTTPException(status_code=404, detail="Dispositivo não encontrado")

        ts_filter = Checkin.timestamp >= range_start
        if use_exclusive_end:
            ts_filter = ts_filter & (Checkin.timestamp < range_end)
        else:
            ts_filter = ts_filter & (Checkin.timestamp <= range_end)

        stmt = (
            select(Checkin)
            .where(
                Checkin.device_id == device.id,
                ts_filter,
            )
            .order_by(Checkin.timestamp.asc())
        )
        rows = (await session.execute(stmt)).scalars().all()

        return [
            HistoryRow(
                timestamp=c.timestamp,
                lat=c.lat,
                lon=c.lon,
                source=(c.source or "ip").strip() or "ip",
                accuracy=c.accuracy,
                region=c.region,
                city=c.city,
                status=c.status.value,
            )
            for c in rows
        ]
