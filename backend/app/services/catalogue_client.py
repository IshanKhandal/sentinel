"""Official Sentinel CCTV catalogue client for GET /api/ingest.

Protocol Standard: Section 1 & Section 3 of Phase 3 Directive.
"The catalogue is the contract. The URL pattern is not.
NEVER hard-code a camera list. NEVER hard-code camera IDs.
NEVER construct a camera URL before obtaining the camera information from /api/ingest."
"""

from typing import List, Optional, Dict, Any, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field

from backend.app.core.config import settings


class CatalogueError(Exception):
    """Base exception for Sentinel catalogue operations."""
    pass


class CatalogueHostNotConfiguredError(CatalogueError):
    """Raised when SENTINEL_STREAM_HOST is not configured (UNKNOWN / BLOCKED)."""
    pass


class CatalogueConnectionError(CatalogueError):
    """Raised when the official catalogue cannot be reached (network/socket failure)."""
    pass


class CatalogueResponseError(CatalogueError):
    """Raised when the catalogue returns non-200 or an invalid/malformed response."""
    pass


class SentinelCatalogueCamera(BaseModel):
    """Normalized camera record from the official /api/ingest catalogue."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(..., description="Authoritative unique camera ID assigned by Sentinel")
    name: Optional[str] = Field(default=None, description="Human-readable camera label or junction name")
    rtsp_url: Optional[str] = Field(default=None, alias="rtsp", description="Authoritative RTSP stream URL")
    whep_url: Optional[str] = Field(default=None, alias="whep", description="Authoritative WebRTC WHEP preview URL")
    hls_url: Optional[str] = Field(default=None, alias="hls", description="Authoritative HLS m3u8 playlist URL")
    codec: Optional[str] = Field(default=None, description="Video codec (e.g. H.264, H.265)")
    live: Optional[bool] = Field(default=None, description="Catalogue-reported live state (NOT application-verified)")
    resolution: Optional[str] = Field(default=None, description="Resolution string (e.g. 1920x1080)")
    fps: Optional[float] = Field(default=None, description="Reported frame rate")
    latitude: Optional[float] = Field(default=None, alias="lat", description="Geographic latitude")
    longitude: Optional[float] = Field(default=None, alias="lng", description="Geographic longitude")

    @property
    def extra_properties(self) -> Dict[str, Any]:
        """Access any unmodeled / unexpected metadata fields safely."""
        return self.model_extra or {}


class SentinelCatalogueClient:
    """HTTP client responsible for querying and validating the Sentinel camera catalogue."""

    def __init__(self, host: Optional[str] = None, timeout: Optional[float] = None) -> None:
        self.host = (host if host is not None else settings.SENTINEL_STREAM_HOST)
        if self.host:
            self.host = self.host.rstrip("/")
        self.timeout = timeout if timeout is not None else settings.SENTINEL_CATALOGUE_TIMEOUT_SECONDS

    @property
    def is_configured(self) -> bool:
        """Return True if an actual stream host is configured."""
        return bool(self.host and self.host.strip())

    def get_catalogue_endpoint(self) -> str:
        """Construct the authoritative catalogue URL."""
        if not self.is_configured:
            raise CatalogueHostNotConfiguredError(
                "SENTINEL_STREAM_HOST is not configured. Stream host is UNKNOWN / BLOCKED."
            )
        return f"{self.host}/api/ingest"

    def fetch_catalogue(self) -> List[SentinelCatalogueCamera]:
        """Fetch and parse the official camera catalogue from GET /api/ingest."""
        endpoint = self.get_catalogue_endpoint()

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(endpoint)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise CatalogueConnectionError(
                f"Failed to connect to official Sentinel catalogue at {endpoint}: {exc}"
            ) from exc
        except Exception as exc:
            raise CatalogueConnectionError(
                f"Unexpected network error connecting to {endpoint}: {exc}"
            ) from exc

        if response.status_code != 200:
            raise CatalogueResponseError(
                f"Catalogue endpoint {endpoint} returned unexpected HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except Exception as exc:
            raise CatalogueResponseError(
                f"Failed to parse catalogue response from {endpoint} as valid JSON: {exc}"
            ) from exc

        return self.parse_catalogue_payload(payload)

    def parse_catalogue_payload(self, payload: Any) -> List[SentinelCatalogueCamera]:
        """Validate and normalize diverse JSON catalogue structures without fabricating fields."""
        items: List[Any] = []
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            for key in ("cameras", "data", "streams", "items"):
                if key in payload and isinstance(payload[key], list):
                    items = payload[key]
                    break
            else:
                if "id" in payload:
                    items = [payload]
                else:
                    raise CatalogueResponseError(
                        f"Catalogue JSON dict does not contain recognized camera list: keys={list(payload.keys())}"
                    )
        else:
            raise CatalogueResponseError(
                f"Unexpected catalogue payload type: expected list or dict, got {type(payload).__name__}"
            )

        validated_cameras: List[SentinelCatalogueCamera] = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                raise CatalogueResponseError(
                    f"Catalogue item at index {idx} is not a JSON object: {item}"
                )
            if "id" not in item:
                raise CatalogueResponseError(
                    f"Catalogue item at index {idx} missing mandatory 'id' field: {item}"
                )
            try:
                cam = SentinelCatalogueCamera.model_validate(item)
                validated_cameras.append(cam)
            except Exception as exc:
                raise CatalogueResponseError(
                    f"Failed to validate catalogue camera at index {idx}: {exc}"
                ) from exc

        return validated_cameras
