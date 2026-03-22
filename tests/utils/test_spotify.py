import json

import pytest
from spotipy import Spotify as BaseSpotify
from spotipy.exceptions import SpotifyException

from spotdl.utils import spotify
from spotdl.utils.spotify import SpotifyClient, SpotifyError


def test_init(patch_dependencies):
    """
    Test SpotifyClient initialization
    """

    SpotifyClient.init(
        client_id="client_id",
        client_secret="client_secret",
        user_auth=False,
        no_cache=True,
    )

    assert SpotifyClient._instance is not None


def test_multiple_init():
    """
    Test multiple SpotifyClient initialization.
    It was initialized in the previous function so there is no need to initialize it again.
    """

    with pytest.raises(SpotifyError):
        SpotifyClient.init(
            client_id="client_id",
            client_secret="client_secret",
            user_auth=False,
            no_cache=True,
        )


def test_init_disables_requests_level_retries(monkeypatch):
    """
    Test SpotifyClient disables requests-level retry sleeps.
    """

    captured_kwargs = {}

    def fake_spotify_init(self, *args, **kwargs):
        captured_kwargs.update(kwargs)
        self.retries = kwargs.get("retries")
        self.status_retries = kwargs.get("status_retries")
        self.backoff_factor = kwargs.get("backoff_factor")

    monkeypatch.setattr(SpotifyClient, "_instance", None, raising=False)
    monkeypatch.setattr(BaseSpotify, "__init__", fake_spotify_init)

    SpotifyClient.init(
        client_id="client_id",
        client_secret="client_secret",
        user_auth=False,
        no_cache=True,
        use_cache_file=False,
    )

    assert captured_kwargs["retries"] == 0
    assert captured_kwargs["status_retries"] == 0
    assert captured_kwargs["backoff_factor"] == 0


def test_get_retries_after_rate_limit(monkeypatch):
    """
    Test SpotifyClient waits and retries when Spotify responds with 429.
    """

    spotify_client = SpotifyClient()
    sleeps = []
    call_count = 0

    monkeypatch.setattr(spotify_client, "no_cache", False, raising=False)
    monkeypatch.setattr(spotify_client, "max_retries", 2, raising=False)
    monkeypatch.setattr(spotify_client, "cache", {}, raising=False)

    def fake_internal_call(method, url, payload, kwargs):
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            raise SpotifyException(
                429,
                -1,
                "rate limited",
                headers={"Retry-After": "0"},
            )

        return {"id": "track-1", "url": url, "method": method}

    monkeypatch.setattr(spotify_client, "_internal_call", fake_internal_call)
    monkeypatch.setattr("spotdl.utils.spotify.time.sleep", sleeps.append)

    result = spotify_client._get("tracks/track-1")

    assert result["id"] == "track-1"
    assert call_count == 2
    assert sleeps == [1]


def test_save_spotify_cache_keeps_metadata_endpoints(tmp_path, monkeypatch):
    """
    Test Spotify cache persistence keeps useful local metadata responses.
    """

    cache_path = tmp_path / ".spotify_cache"
    monkeypatch.setattr(spotify, "get_spotify_cache_path", lambda: cache_path)

    spotify.save_spotify_cache(
        {
            '{"url": "tracks/1"}': {"id": "track"},
            '{"url": "albums/1"}': {"id": "album"},
            '{"url": "playlists/1/tracks"}': {"items": []},
            '{"url": "search"}': {"tracks": {"items": []}},
            '{"url": "audio-analysis/1"}': {"ignore": True},
            '{"url": "episodes/1"}': {"ignore": True},
            '{"url": "tracks/2"}': None,
        }
    )

    saved_cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert '{"url": "tracks/1"}' in saved_cache
    assert '{"url": "albums/1"}' in saved_cache
    assert '{"url": "playlists/1/tracks"}' in saved_cache
    assert '{"url": "search"}' in saved_cache
    assert '{"url": "audio-analysis/1"}' not in saved_cache
    assert '{"url": "episodes/1"}' not in saved_cache


def test_get_fails_fast_on_large_rate_limit(monkeypatch):
    """
    Test SpotifyClient does not block on very large Retry-After values.
    """

    spotify_client = SpotifyClient()
    sleeps = []

    monkeypatch.setattr(spotify_client, "no_cache", False, raising=False)
    monkeypatch.setattr(spotify_client, "max_retries", 2, raising=False)
    monkeypatch.setattr(spotify_client, "cache", {}, raising=False)

    def fake_internal_call(method, url, payload, kwargs):
        raise SpotifyException(
            429,
            -1,
            "rate limited",
            headers={"Retry-After": "86400"},
        )

    monkeypatch.setattr(spotify_client, "_internal_call", fake_internal_call)
    monkeypatch.setattr("spotdl.utils.spotify.time.sleep", sleeps.append)

    with pytest.raises(SpotifyError, match="will not block waiting that long"):
        spotify_client._get("tracks/track-1")

    assert sleeps == []
