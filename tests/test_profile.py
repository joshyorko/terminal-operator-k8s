import types
import pytest
import httpx
from terminal_operator import main

class DummyResponse:
    def __init__(self):
        self.data = {}

@pytest.mark.asyncio
async def test_handle_profile_success(monkeypatch):
    async def mock_update(name, email):
        return DummyResponse()
    monkeypatch.setattr(main.terminal_client.profile, "update", mock_update)
    spec = {"name": "User", "email": "user@example.com"}
    status = {}
    meta = {"name": "prof", "generation": 1}
    patch = types.SimpleNamespace(status={})
    await main.handle_profile(spec, status, meta, patch, logger=main.logger)
    assert patch.status["phase"] == "Synced"
    assert "lastSyncTime" in patch.status

@pytest.mark.asyncio
async def test_handle_profile_api_error(monkeypatch):
    async def mock_update(name, email):
        req = httpx.Request("PUT", "https://example.com")
        resp = httpx.Response(status_code=400, request=req)
        raise main.APIStatusError("fail", response=resp, body={"code": "bad"})
    monkeypatch.setattr(main.terminal_client.profile, "update", mock_update)
    spec = {"name": "User", "email": "user@example.com"}
    status = {}
    meta = {"name": "prof", "generation": 1}
    patch = types.SimpleNamespace(status={})
    with pytest.raises(main.kopf.PermanentError):
        await main.handle_profile(spec, status, meta, patch, logger=main.logger)

