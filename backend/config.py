"""Configuração carregada de variáveis de ambiente (.env)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Raiz do projeto (pasta que contém backend/ e .env)
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    teams_webhook_url: str | None = None
    database_url: str = "sqlite+aiosqlite:///./cadevoce.db"
    api_secret_key: str
    # Cookie de sessão do dashboard (login em /auth/browser/login): True em HTTPS (Azure)
    cookie_secure: bool = False
    # Azure Maps — usado no reverse geocoding quando o agente envia GPS
    azure_maps_key: str | None = None
    # Minutos fora do estado antes do primeiro alerta Teams
    violation_threshold_minutes: int = 20


def get_settings() -> Settings:
    """Nova instância a cada chamada — relê variáveis de ambiente / .env."""
    return Settings()
