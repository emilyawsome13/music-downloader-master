from pathlib import Path

from spotdl.utils import console


def test_generate_config_defaults_to_no_without_stdin(monkeypatch, capsys, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(console, "get_config_file", lambda: config_path)
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))

    assert console.generate_config() is None

    captured = capsys.readouterr()
    assert "Defaulting to 'N'." in captured.out
    assert "Exiting..." in captured.out


def test_download_ffmpeg_reuses_existing_installation_without_stdin(
    monkeypatch, capsys
):
    monkeypatch.setattr(console, "get_local_ffmpeg", lambda: Path("/tmp/ffmpeg"))
    monkeypatch.setattr(console, "is_ffmpeg_installed", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))

    def fail_download():
        raise AssertionError("ffmpeg_download should not be called")

    monkeypatch.setattr(console, "ffmpeg_download", fail_download)

    console.download_ffmpeg()

    captured = capsys.readouterr()
    assert "Defaulting to 'N'." in captured.out
    assert "Using existing FFmpeg installation." in captured.out
