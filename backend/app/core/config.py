"""Application configuration module using Pydantic Settings."""

from typing import Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Sentinel system configuration."""

    PROJECT_NAME: str = "Sentinel CCTV & Vehicle Intelligence"
    VERSION: str = "0.1.0"
    
    # Database
    DATABASE_URL: str = "sqlite:///./sentinel.db"
    
    # Operation Mode (Strict Rule 29 / docs/demo-mode.md enforcement)
    SENTINEL_OPERATION_MODE: Literal["DEMO", "LIVE"] = "DEMO"
    
    # Official Sentinel Stream Host (Section 2: Phase 3)
    # When unset or empty, stream host is UNKNOWN / BLOCKED.
    # NEVER set to localhost or fake IP to simulate a real integration.
    SENTINEL_STREAM_HOST: Optional[str] = None
    SENTINEL_CATALOGUE_TIMEOUT_SECONDS: float = 5.0
    
    # RTSP Ingestion Transport Invariants (Section 8: Phase 3)
    RTSP_TRANSPORT: Literal["tcp"] = "tcp"  # Strict invariant: ALWAYS FORCE TCP
    RTSP_CONNECT_TIMEOUT_MS: int = 5000
    
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
