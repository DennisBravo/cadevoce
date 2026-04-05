"""Consulta assíncrona ao ip-api.com para geolocalização (proxy/hosting → flag tipo VPN)."""

from dataclasses import dataclass

import httpx


@dataclass
class GeoIPResult:
    country: str | None
    region: str | None
    city: str | None
    lat: float | None
    lon: float | None
    vpn: bool  # True se proxy ou hosting (equivalente ao vpn_detected no check-in)


async def lookup_ip(ip: str) -> GeoIPResult:
    """
    Busca metadados do IP na API ip-api.com (sem token).
    proxy/hosting indicam datacenter/VPN comum — não bloqueiam a validação de estado no backend.
    """
    fields = "status,message,country,regionName,city,lat,lon,proxy,hosting"
    url = f"http://ip-api.com/json/{ip}?fields={fields}&lang=pt-BR"

    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()

    if data.get("status") == "fail":
        msg = data.get("message") or "falha na consulta"
        err_resp = httpx.Response(502, request=r.request, json=data)
        raise httpx.HTTPStatusError(
            f"ip-api.com: {msg}",
            request=r.request,
            response=err_resp,
        )

    proxy = data.get("proxy") is True
    hosting = data.get("hosting") is True
    vpn_flag = bool(proxy or hosting)

    lat_raw = data.get("lat")
    lon_raw = data.get("lon")
    lat: float | None = None
    lon: float | None = None
    if lat_raw is not None:
        try:
            lat = float(lat_raw)
        except (TypeError, ValueError):
            pass
    if lon_raw is not None:
        try:
            lon = float(lon_raw)
        except (TypeError, ValueError):
            pass

    return GeoIPResult(
        country=data.get("country"),
        region=data.get("regionName"),
        city=data.get("city"),
        lat=lat,
        lon=lon,
        vpn=vpn_flag,
    )
