from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações carregadas do .env com validação de tipos."""

    # Meta WhatsApp Cloud API
    whatsapp_token: str
    phone_number_id: str
    waba_id: str
    webhook_verify_token: str

    # Anthropic
    anthropic_api_key: str

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # Graph API
    graph_api_version: str = "v21.0"
    graph_api_base: str = "https://graph.facebook.com"

    # Claude — modelo principal (agentes especializados)
    claude_model: str = "claude-sonnet-4-5"
    claude_max_tokens: int = 1024

    # Claude — modelo do classifier (mais barato, só classifica intent)
    classifier_model: str = "claude-haiku-4-5-20251001"

    # Memória de conversa
    memory_db_path: str = "data/conversations.db"
    memory_max_messages: int = 20

    # Google Calendar (Fase 4.2)
    google_credentials_path: str
    google_calendar_id: str
    studio_timezone: str = "America/Sao_Paulo"
    studio_open_hour: int = 7
    studio_close_hour: int = 22

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
