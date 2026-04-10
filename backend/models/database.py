"""Modelos SQLAlchemy, sessão assíncrona e migrações leves (SQLite) sem apagar dados."""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String, Float, Boolean, Enum as SAEnum, UniqueConstraint, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from backend.config import get_settings


class Base(DeclarativeBase):
    pass


class CheckinStatus(str, Enum):
    ok = "ok"
    violation = "violation"


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("hostname", "username", name="uq_device_hostname_username"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    hostname: Mapped[str] = mapped_column(String(255), index=True)
    username: Mapped[str] = mapped_column(String(255), index=True)
    estado_permitido: Mapped[str] = mapped_column(String(64))

    checkins: Mapped[list["Checkin"]] = relationship(back_populates="device")
    violation_windows: Mapped[list["ViolationWindow"]] = relationship(back_populates="device")


class Checkin(Base):
    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    ip: Mapped[str] = mapped_column(String(45), default="")
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[CheckinStatus] = mapped_column(
        SAEnum(CheckinStatus, values_callable=lambda x: [e.value for e in x])
    )
    vpn_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    # Fonte da posição e leitura bruta do agente (GPS); checkins antigos: source='ip', demais nulos
    source: Mapped[str] = mapped_column(String(16), default="ip")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_boot_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    uptime_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Inventário enviado pelo agente (último check-in)
    os_caption: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mac_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    machine_serial: Mapped[str | None] = mapped_column(String(128), nullable=True)

    device: Mapped["Device"] = relationship(back_populates="checkins")


class ViolationWindow(Base):
    """Janela contínua fora do estado permitido (alerta só após limiar temporal)."""

    __tablename__ = "violation_windows"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    first_seen_outside: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_outside: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    alert_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    device: Mapped["Device"] = relationship(back_populates="violation_windows")


def _engine():
    url = get_settings().database_url
    if "sqlite" in url:
        return create_async_engine(
            url,
            echo=False,
            connect_args={"check_same_thread": False},
        )
    return create_async_engine(url, echo=False)


engine = _engine()
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


def _migrate_sqlite_checkins(connection) -> None:
    """Adiciona colunas novas em checkins se faltarem (bancos já existentes)."""
    rows = connection.execute(text("PRAGMA table_info(checkins)")).fetchall()
    existing = {row[1] for row in rows}
    statements: list[str] = []
    if "source" not in existing:
        statements.append(
            "ALTER TABLE checkins ADD COLUMN source VARCHAR(8) NOT NULL DEFAULT 'ip'"
        )
    if "latitude" not in existing:
        statements.append("ALTER TABLE checkins ADD COLUMN latitude REAL")
    if "longitude" not in existing:
        statements.append("ALTER TABLE checkins ADD COLUMN longitude REAL")
    if "accuracy" not in existing:
        statements.append("ALTER TABLE checkins ADD COLUMN accuracy REAL")
    if "last_boot_utc" not in existing:
        statements.append("ALTER TABLE checkins ADD COLUMN last_boot_utc TIMESTAMP")
    if "uptime_seconds" not in existing:
        statements.append("ALTER TABLE checkins ADD COLUMN uptime_seconds REAL")
    if "os_caption" not in existing:
        statements.append("ALTER TABLE checkins ADD COLUMN os_caption VARCHAR(512)")
    if "mac_address" not in existing:
        statements.append("ALTER TABLE checkins ADD COLUMN mac_address VARCHAR(64)")
    if "machine_serial" not in existing:
        statements.append("ALTER TABLE checkins ADD COLUMN machine_serial VARCHAR(128)")
    for stmt in statements:
        connection.execute(text(stmt))


def _migrate_postgres_checkins(connection) -> None:
    """Colunas adicionadas ao modelo após o primeiro deploy (PostgreSQL / Azure)."""
    stmts = [
        "ALTER TABLE checkins ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'ip'",
        "ALTER TABLE checkins ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION",
        "ALTER TABLE checkins ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION",
        "ALTER TABLE checkins ADD COLUMN IF NOT EXISTS accuracy DOUBLE PRECISION",
        "ALTER TABLE checkins ADD COLUMN IF NOT EXISTS last_boot_utc TIMESTAMPTZ",
        "ALTER TABLE checkins ADD COLUMN IF NOT EXISTS uptime_seconds DOUBLE PRECISION",
        "ALTER TABLE checkins ADD COLUMN IF NOT EXISTS os_caption VARCHAR(512)",
        "ALTER TABLE checkins ADD COLUMN IF NOT EXISTS mac_address VARCHAR(64)",
        "ALTER TABLE checkins ADD COLUMN IF NOT EXISTS machine_serial VARCHAR(128)",
    ]
    for stmt in stmts:
        connection.execute(text(stmt))


async def migrate_schema() -> None:
    """Migração incremental: não remove dados."""
    url = get_settings().database_url.lower()
    if "sqlite" in url:
        async with engine.begin() as conn:
            await conn.run_sync(_migrate_sqlite_checkins)
    elif "postgresql" in url or "postgres" in url:
        async with engine.begin() as conn:
            await conn.run_sync(_migrate_postgres_checkins)


async def init_db():
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    await migrate_schema()
