from pathlib import Path

from spotdl import render_build


def test_ensure_ffmpeg_uses_existing_binary(monkeypatch):
    existing = Path("/tmp/existing-ffmpeg")

    monkeypatch.setattr(render_build, "get_ffmpeg_path", lambda: existing)

    def fail_download():
        raise AssertionError("download_ffmpeg should not be called")

    monkeypatch.setattr(render_build, "download_ffmpeg", fail_download)

    assert render_build.ensure_ffmpeg() == existing


def test_ensure_ffmpeg_downloads_when_missing(monkeypatch):
    downloaded = Path("/tmp/downloaded-ffmpeg")

    monkeypatch.setattr(render_build, "get_ffmpeg_path", lambda: None)
    monkeypatch.setattr(render_build, "download_ffmpeg", lambda: downloaded)

    assert render_build.ensure_ffmpeg() == downloaded
