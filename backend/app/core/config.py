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
    
    # RTSP Ingestion Transport Invariants (Section 8: Phase 3 & Stage 5)
    RTSP_TRANSPORT: Literal["tcp"] = "tcp"  # Strict invariant: ALWAYS FORCE TCP
    RTSP_CONNECT_TIMEOUT_MS: int = 5000
    
    # Stream Ingestion Engine (Stage 5 Architecture)
    STREAM_RING_BUFFER_SIZE: int = 15
    STREAM_RECONNECT_BASE_DELAY: float = 1.0
    STREAM_RECONNECT_MAX_DELAY: float = 30.0
    STREAM_RECONNECT_FACTOR: float = 2.0
    STREAM_HEALTH_WATCHDOG_TIMEOUT_SECONDS: float = 10.0
    STREAM_CONSECUTIVE_FRAMES_FOR_HEALTH: int = 5

    # Vehicle Detection Pipeline (Stage 6 Architecture)
    VEHICLE_DETECTOR_BACKEND: Literal["MOCK", "ONNX_RUNTIME"] = "MOCK"
    VEHICLE_DETECTOR_MODEL_PATH: Optional[str] = None
    VEHICLE_CONFIDENCE_THRESHOLD: float = 0.25
    VEHICLE_IOU_THRESHOLD: float = 0.45
    DETECTION_FPS_LIMIT: float = 5.0

    # Plate Detection & OCR / ANPR Pipeline (Stage 7 Architecture)
    PLATE_DETECTOR_BACKEND: Literal["MOCK", "ONNX_RUNTIME"] = "MOCK"
    PLATE_DETECTOR_MODEL_PATH: Optional[str] = None
    PLATE_CONFIDENCE_THRESHOLD: float = 0.40
    OCR_PROVIDER_BACKEND: Literal["MOCK", "ONNX_RUNTIME"] = "MOCK"
    OCR_MODEL_PATH: Optional[str] = None
    OCR_CONFIDENCE_THRESHOLD: float = 0.50
    ANPR_PREPROCESSING_VARIANT: Literal["standard", "clahe", "grayscale", "raw"] = "standard"

    # Watchlist Matching Configuration (Stage 9 Architecture)
    # Configurable implementation parameters (NOT scientifically validated benchmarks; unbenchmarked prototype)
    WATCHLIST_FUZZY_MATCHING_ENABLED: bool = True
    WATCHLIST_FUZZY_SIMILARITY_THRESHOLD: float = 0.85
    WATCHLIST_FUZZY_MAX_DISTANCE: int = 1
    WATCHLIST_OCR_CONFIDENCE_THRESHOLD: float = 0.40



    
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
