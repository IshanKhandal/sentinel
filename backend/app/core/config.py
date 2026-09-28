"""Application configuration module using Pydantic Settings."""

from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Sentinel system configuration."""

    PROJECT_NAME: str = "Sentinel CCTV & Vehicle Intelligence"
    VERSION: str = "0.1.0"
    
    # Database
    DATABASE_URL: str = "sqlite:///./sentinel.db"
    
    # Operation Mode (Strict Rule 29 / docs/demo-mode.md enforcement)
    SENTINEL_OPERATION_MODE: Literal["DEMO", "LIVE"] = "DEMO"
    
    # Security
    SECRET_KEY: str = "development-only-insecure-secret-key-do-not-use-in-production-min32c"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    
    # Logging
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
