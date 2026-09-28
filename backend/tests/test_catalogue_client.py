"""Automated unit tests for SentinelCatalogueClient."""

import pytest
import httpx
from backend.app.services.catalogue_client import (
    SentinelCatalogueClient,
    SentinelCatalogueCamera,
    CatalogueHostNotConfiguredError,
    CatalogueConnectionError,
    CatalogueResponseError,
)


def test_missing_host_raises_host_not_configured_error():
    """Verify that unconfigured stream host raises explicit BLOCKED exception without guessing."""
    client = SentinelCatalogueClient(host=None)
    assert not client.is_configured
    with pytest.raises(CatalogueHostNotConfiguredError) as exc_info:
        client.fetch_catalogue()
    assert "UNKNOWN / BLOCKED" in str(exc_info.value)


def test_empty_host_raises_host_not_configured_error():
    """Verify that empty string host raises host not configured error."""
    client = SentinelCatalogueClient(host="   ")
    assert not client.is_configured
    with pytest.raises(CatalogueHostNotConfiguredError):
        client.fetch_catalogue()


def test_parse_valid_list_payload():
    """Verify parsing a valid top-level list of camera records."""
    raw_payload = [
        {
            "id": "cam_01",
            "name": "Junction 01 - SG Highway",
            "rtsp": "rtsp://sentinel-host:8554/stream/cam_01",
            "whep": "http://sentinel-host:8889/stream/cam_01/whep",
            "hls": "http://sentinel-host/live/stream/cam_01/index.m3u8",
            "codec": "H.264",
            "live": True,
            "resolution": "1920x1080",
            "fps": 25.0,
            "lat": 23.0450,
            "lng": 72.5200,
            "unknown_future_field": "preserved_safely"
        },
        {
            "id": "cam_02",
            "codec": "H.265",
            "live": False
        }
    ]
    client = SentinelCatalogueClient(host="http://dummy-host")
    cameras = client.parse_catalogue_payload(raw_payload)

    assert len(cameras) == 2
    c1 = cameras[0]
    assert c1.id == "cam_01"
    assert c1.name == "Junction 01 - SG Highway"
    assert c1.rtsp_url == "rtsp://sentinel-host:8554/stream/cam_01"
    assert c1.whep_url == "http://sentinel-host:8889/stream/cam_01/whep"
    assert c1.codec == "H.264"
    assert c1.live is True
    assert c1.latitude == 23.0450
    assert c1.extra_properties["unknown_future_field"] == "preserved_safely"

    c2 = cameras[1]
    assert c2.id == "cam_02"
    assert c2.codec == "H.265"
    assert c2.live is False
    assert c2.name is None  # Optional field handled cleanly


def test_parse_wrapped_dict_payload():
    """Verify parsing a dictionary wrapped camera catalogue."""
    raw_payload = {
        "cameras": [
            {
                "id": "cam_10",
                "rtsp": "rtsp://sentinel-host:8554/stream/cam_10",
                "codec": "H.264",
                "live": True
            }
        ]
    }
    client = SentinelCatalogueClient(host="http://dummy-host")
    cameras = client.parse_catalogue_payload(raw_payload)
    assert len(cameras) == 1
    assert cameras[0].id == "cam_10"


def test_missing_mandatory_id_field_raises_response_error():
    """Verify that catalogue items missing 'id' are rejected with clear error."""
    raw_payload = [
        {"name": "Nameless Camera", "rtsp": "rtsp://host/stream/1"}
    ]
    client = SentinelCatalogueClient(host="http://dummy-host")
    with pytest.raises(CatalogueResponseError) as exc_info:
        client.parse_catalogue_payload(raw_payload)
    assert "missing mandatory 'id' field" in str(exc_info.value)


def test_connection_failure_handling(monkeypatch):
    """Verify that network connection drops raise CatalogueConnectionError."""
    def mock_get(*args, **kwargs):
        raise httpx.ConnectError("Connection refused by target machine")

    client = SentinelCatalogueClient(host="http://unreachable-sentinel-host:8080")
    monkeypatch.setattr(httpx.Client, "get", mock_get)

    with pytest.raises(CatalogueConnectionError) as exc_info:
        client.fetch_catalogue()
    assert "Failed to connect to official Sentinel catalogue" in str(exc_info.value)


def test_non_200_response_handling(monkeypatch):
    """Verify that HTTP 404 or 500 raises CatalogueResponseError."""
    class MockResponse:
        status_code = 502
        text = "Bad Gateway"

    def mock_get(*args, **kwargs):
        return MockResponse()

    client = SentinelCatalogueClient(host="http://mock-host")
    monkeypatch.setattr(httpx.Client, "get", mock_get)

    with pytest.raises(CatalogueResponseError) as exc_info:
        client.fetch_catalogue()
    assert "HTTP 502" in str(exc_info.value)
