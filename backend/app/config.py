from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    jwt_secret: str = "change-me-in-production"
    jwt_expiry_minutes: int = 60
    cors_origins: str = "http://localhost:5173"
    google_api_key: str = ""
    google_model: str = "gemini-2.5-flash"
    oracle_user: str = ""
    oracle_password: str = ""
    oracle_dsn: str = ""
    oracle_wallet_dir: str = ""
    oracle_wallet_password: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = ""
    otp_provider: str = "mock"
    otp_expiry_minutes: int = 10
    max_upload_mb: int = 10
    max_iterations: int = 3
    rate_limit_requests: int = 3
    rate_limit_window_seconds: int = 10

    @property
    def allowed_origins(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings()
