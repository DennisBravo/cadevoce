"""Reverse geocoding assíncrono via Azure Maps (lat/lon → país, estado, cidade)."""

import httpx

from backend.services import rules
from backend.services.geoip import GeoIPResult

# DEBUG temporário: log no stdout do processo uvicorn (remover após diagnosticar 502)
_DEBUG_AZURE_MAPS = True


class GeocodingError(Exception):
    """Falha ao resolver endereço a partir de coordenadas (Azure Maps ou resposta vazia)."""


def _mask_key_in_url(full_url: str, key: str) -> str:
    if key and key.strip():
        return full_url.replace(key.strip(), "***REDACTED***")
    return full_url


async def reverse_geocode(latitude: float, longitude: float) -> GeoIPResult:
    """
    Chama Azure Maps Search Address Reverse e devolve estrutura alinhada ao geoip (region em sigla BR quando aplicável).

    Documentação: GET https://atlas.microsoft.com/search/address/reverse/json
    Parâmetros: api-version=1.0, query=latitude,longitude, subscription-key=...
    Resposta de sucesso: raiz com "addresses" (array); cada item tem "address" (objeto Address).
    """
    from backend.config import get_settings

    settings = get_settings()
    key = (settings.azure_maps_key or "").strip()
    if not key:
        raise GeocodingError(
            "AZURE_MAPS_KEY não configurada; necessária para check-ins com source=gps ou gps_serial"
        )

    # Endpoint oficial (formato json no path, não query)
    url = "https://atlas.microsoft.com/search/address/reverse/json"
    params = {
        "api-version": "1.0",
        "query": f"{latitude},{longitude}",
        "subscription-key": key,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, params=params)
        full_url_str = str(r.request.url)

        if _DEBUG_AZURE_MAPS:
            print(
                "[geocoding DEBUG] URL chamada (chave mascarada):",
                _mask_key_in_url(full_url_str, key.strip()),
                flush=True,
            )
            print(
                "[geocoding DEBUG] HTTP status:",
                r.status_code,
                flush=True,
            )
            print(
                "[geocoding DEBUG] Resposta completa Azure Maps:\n",
                r.text,
                "\n[geocoding DEBUG] --- fim resposta ---",
                flush=True,
            )

        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise GeocodingError(
                f"Azure Maps HTTP {e.response.status_code}: {e.response.text[:500]}"
            ) from e

        try:
            data = r.json()
        except ValueError as e:
            raise GeocodingError(
                f"Resposta Azure Maps não é JSON válido: {r.text[:300]}"
            ) from e

    # Raiz: "addresses" (oficial). "results" aparece em outros serviços Search — mantido por compatibilidade.
    addresses = data.get("addresses") or data.get("results") or []

    # Erro em corpo 200 (formato Azure Maps)
    if not addresses and data.get("error"):
        err = data["error"]
        if isinstance(err, dict):
            msg = err.get("message") or str(err)
        else:
            msg = str(err)
        raise GeocodingError(f"Azure Maps (erro no corpo): {msg}")

    if not addresses:
        raise GeocodingError(
            "Azure Maps não retornou endereços para as coordenadas informadas "
            f"(summary: {data.get('summary')!r})"
        )

    addr = (addresses[0] or {}).get("address") or {}

    # Campos Address conforme REST Maps 1.0 (adminDistrict nem sempre vem; BR costuma usar countrySubdivision*)
    country = (
        addr.get("countryRegion")
        or addr.get("countryCode")
        or addr.get("country")
    )
    admin = (
        addr.get("adminDistrict")
        or addr.get("countrySubdivision")
        or addr.get("countrySubdivisionName")
    )
    city = (
        addr.get("localName")
        or addr.get("municipality")
        or addr.get("municipalitySubdivision")
    )

    region_out: str | None = admin
    cr = (country or "").strip().upper()
    if cr in ("BR", "BRAZIL", "BRASIL", "BRA"):
        sigla = rules.br_admin_district_to_sigla(admin)
        if sigla:
            region_out = sigla

    return GeoIPResult(
        country=country,
        region=region_out,
        city=city,
        lat=float(latitude),
        lon=float(longitude),
        vpn=False,
    )
