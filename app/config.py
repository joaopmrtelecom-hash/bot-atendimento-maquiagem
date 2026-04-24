from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações carregadas do .env com validação de tipos."""

    whatsapp_token: str
    phone_number_id: str
    waba_id: str
    webhook_verify_token: str
    anthropic_api_key: str

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    graph_api_version: str = "v21.0"
    graph_api_base: str = "https://graph.facebook.com"

    claude_model: str = "claude-sonnet-4-5"
    claude_max_tokens: int = 1024

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
