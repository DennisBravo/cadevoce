"""Validação de estado permitido e regras temporais para alertas (violation_windows)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.database import ViolationWindow

# Mapeamento: siglas BR → nomes que APIs (ip-api, Azure) podem retornar
_BR_EQUIV = {
    "AC": {"AC", "ACRE"},
    "AL": {"AL", "ALAGOAS"},
    "AP": {"AP", "AMAPÁ", "AMAPA"},
    "AM": {"AM", "AMAZONAS"},
    "BA": {"BA", "BAHIA"},
    "CE": {"CE", "CEARÁ", "CEARA"},
    "DF": {"DF", "DISTRITO FEDERAL"},
    "ES": {"ES", "ESPÍRITO SANTO", "ESPIRITO SANTO"},
    "GO": {"GO", "GOIÁS", "GOIAS"},
    "MA": {"MA", "MARANHÃO", "MARANHAO"},
    "MT": {"MT", "MATO GROSSO"},
    "MS": {"MS", "MATO GROSSO DO SUL"},
    "MG": {"MG", "MINAS GERAIS"},
    "PA": {"PA", "PARÁ", "PARA"},
    "PB": {"PB", "PARAÍBA", "PARAIBA"},
    "PR": {"PR", "PARANÁ", "PARANA"},
    "PE": {"PE", "PERNAMBUCO"},
    "PI": {"PI", "PIAUÍ", "PIAUI"},
    "RJ": {"RJ", "RIO DE JANEIRO"},
    "RN": {"RN", "RIO GRANDE DO NORTE"},
    "RS": {"RS", "RIO GRANDE DO SUL"},
    "RO": {"RO", "RONDÔNIA", "RONDONIA"},
    "RR": {"RR", "RORAIMA"},
    "SC": {"SC", "SANTA CATARINA"},
    "SP": {"SP", "SÃO PAULO", "SAO PAULO"},
    "SE": {"SE", "SERGIPE"},
    "TO": {"TO", "TOCANTINS"},
}


def _normalize(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(s.upper().strip().split())


def br_admin_district_to_sigla(admin_district: str | None) -> str | None:
    """
    Converte nome de subdivisão BR (ex.: Distrito Federal, São Paulo) em sigla (DF, SP).
    Usado após reverse geocoding (Azure adminDistrict).
    """
    d = _normalize(admin_district)
    if not d:
        return None
    if len(d) == 2 and d.isalpha():
        return d
    for sigla, nomes in _BR_EQUIV.items():
        if d in nomes:
            return sigla
        if d == sigla:
            return sigla
    return None


def region_matches(estado_permitido: str, region_detectada: str | None) -> bool:
    """
    Retorna True se a região detectada for equivalente ao estado permitido.
    Comparação case-insensitive; inclui equivalências para estados brasileiros.
    """
    permitido = _normalize(estado_permitido)
    detectada = _normalize(region_detectada)

    if not permitido:
        return False
    if not detectada:
        return False

    if permitido == detectada:
        return True

    equiv = _BR_EQUIV.get(permitido)
    if equiv and detectada in equiv:
        return True

    for sigla, nomes in _BR_EQUIV.items():
        if permitido in nomes and detectada in nomes:
            return True
        if permitido == sigla and detectada in nomes:
            return True

    return False


async def _fechar_janelas_abertas(
    session: AsyncSession, device_id: int, now: datetime
) -> None:
    """Marca como resolvidas as janelas de violação em aberto (voltou ao estado permitido)."""
    r = await session.execute(
        select(ViolationWindow).where(
            ViolationWindow.device_id == device_id,
            ViolationWindow.resolved == False,
        )
    )
    for w in r.scalars().all():
        w.resolved = True
        w.last_seen_outside = now


async def apply_violation_timing(
    session: AsyncSession,
    device_id: int,
    now: datetime,
    in_compliance: bool,
) -> bool:
    """
    1) Dentro do estado: encerra janelas abertas; não alerta.
    2) Fora: cria ou atualiza violation_windows; retorna True se deve enviar Teams
       (primeira vez que (now - first_seen_outside) >= limiar e alert_sent ainda False).
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    threshold_minutes = get_settings().violation_threshold_minutes
    limiar = timedelta(minutes=threshold_minutes)

    if in_compliance:
        await _fechar_janelas_abertas(session, device_id, now)
        return False

    r = await session.execute(
        select(ViolationWindow).where(
            ViolationWindow.device_id == device_id,
            ViolationWindow.resolved == False,
        )
    )
    aberta = r.scalar_one_or_none()

    if aberta is None:
        session.add(
            ViolationWindow(
                device_id=device_id,
                first_seen_outside=now,
                last_seen_outside=now,
                alert_sent=False,
                resolved=False,
            )
        )
        return False

    aberta.last_seen_outside = now
    decorrido = now - aberta.first_seen_outside
    if decorrido >= limiar and not aberta.alert_sent:
        aberta.alert_sent = True
        return True
    return False
