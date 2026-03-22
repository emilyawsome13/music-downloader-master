import asyncio
from pathlib import Path

from spotdl.render_app import create_app
from spotdl.utils.web import app_state


def test_create_app_uses_render_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTDL_DATA_DIR", str(tmp_path / "render-data"))
    monkeypatch.setenv("PORT", "10000")
    monkeypatch.setenv("SPOTDL_AUDIO_PROVIDERS", "youtube-music,youtube")
    monkeypatch.setenv("SPOTDL_BITRATE", "192k")

    app = create_app()

    assert app.title == "spotDL Control Room"
    assert app_state.web_settings["host"] == "0.0.0.0"
    assert app_state.web_settings["port"] == 10000
    assert app_state.downloader_settings["audio_providers"] == [
        "youtube-music",
        "youtube",
    ]
    assert app_state.downloader_settings["output"] == (
        "{album-artist}/{album}/{title}.{output-ext}"
    )
    assert Path(app_state.web_settings["web_gui_location"]).is_dir()


def test_create_app_initializes_spotify_client_on_startup(monkeypatch, tmp_path):
    class FakeSpotifyClient:
        def __init__(self):
            self.init_calls = []
            self.initialized = False

        def __call__(self):
            if not self.initialized:
                raise Exception("Spotify client not created")
            return object()

        def init(self, **kwargs):
            self.initialized = True
            self.init_calls.append(kwargs)

    fake_spotify_client = FakeSpotifyClient()

    monkeypatch.setenv("SPOTDL_DATA_DIR", str(tmp_path / "render-data"))
    monkeypatch.setenv("SPOTDL_CLIENT_ID", "render-client-id")
    monkeypatch.setenv("SPOTDL_CLIENT_SECRET", "render-client-secret")
    monkeypatch.setattr("spotdl.render_app.SpotifyClient", fake_spotify_client)
    monkeypatch.setattr("spotdl.render_app.SpotifyError", Exception)

    app = create_app()

    asyncio.run(app.router.startup())
    asyncio.run(app.router.shutdown())

    assert len(fake_spotify_client.init_calls) == 1
    assert fake_spotify_client.init_calls[0]["client_id"] == "render-client-id"
    assert fake_spotify_client.init_calls[0]["client_secret"] == "render-client-secret"
    assert fake_spotify_client.init_calls[0]["headless"] is True
    assert fake_spotify_client.init_calls[0]["use_cache_file"] is True
