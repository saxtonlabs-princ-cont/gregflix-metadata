import pytest

from app.config import TmdbProviderConfig
from app.services.tmdb_client import TmdbClient


class StubResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"results": []}


class StubAsyncClient:
    calls = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def get(self, path, params=None, headers=None):
        self.calls.append({"path": path, "params": params, "headers": headers})
        return StubResponse()


def tmdb_config(**overrides) -> TmdbProviderConfig:
    payload = {
        "base_url": "https://api.themoviedb.org/3",
        "image_base_url": "https://image.tmdb.org/t/p/original",
    }
    payload.update(overrides)
    return TmdbProviderConfig.model_validate(payload)


@pytest.mark.asyncio
async def test_bearer_token_auth_sends_authorization_header_without_api_key(monkeypatch):
    StubAsyncClient.calls = []
    monkeypatch.setattr("app.services.tmdb_client.httpx.AsyncClient", StubAsyncClient)
    monkeypatch.setenv("TMDB_READ_ACCESS_TOKEN", "read-token")

    client = TmdbClient(tmdb_config(auth_mode="bearer_token"))

    await client.search_movie("Signal")

    assert StubAsyncClient.calls == [
        {
            "path": "/search/movie",
            "params": {"query": "Signal"},
            "headers": {"Authorization": "Bearer read-token"},
        }
    ]


@pytest.mark.asyncio
async def test_api_key_auth_sends_api_key_param_without_authorization_header(monkeypatch):
    StubAsyncClient.calls = []
    monkeypatch.setattr("app.services.tmdb_client.httpx.AsyncClient", StubAsyncClient)
    monkeypatch.setenv("TMDB_API_KEY", "v3-key")

    client = TmdbClient(tmdb_config(auth_mode="api_key"))

    await client.search_tv("Signal")

    assert StubAsyncClient.calls == [
        {
            "path": "/search/tv",
            "params": {"query": "Signal", "api_key": "v3-key"},
            "headers": None,
        }
    ]


def test_bearer_token_auth_requires_read_access_token(monkeypatch):
    monkeypatch.delenv("TMDB_READ_ACCESS_TOKEN", raising=False)

    with pytest.raises(ValueError, match="Missing TMDB read access token environment variable"):
        TmdbClient(tmdb_config(auth_mode="bearer_token"))


def test_api_key_auth_requires_api_key(monkeypatch):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)

    with pytest.raises(ValueError, match="Missing TMDB API key environment variable"):
        TmdbClient(tmdb_config(auth_mode="api_key"))
