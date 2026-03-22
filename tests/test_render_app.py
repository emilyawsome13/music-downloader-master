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
