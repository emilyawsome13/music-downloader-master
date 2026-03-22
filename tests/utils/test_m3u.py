import pytest
from requests.exceptions import RequestException

from spotdl.types.playlist import Playlist
from spotdl.utils.m3u import create_m3u_content, create_m3u_file
from spotdl.utils.spotify import SpotifyError

PLAYLIST = "https://open.spotify.com/playlist/5LkNhFidYyyjRWwnkcMbQs"


def _skip_if_live_lookup_failed(exc: Exception) -> None:
    """
    Skip tests that rely on live Spotify playlist metadata when the upstream fails.
    """

    pytest.skip(f"Spotify metadata lookup failed: {exc}")


def test_create_m3u_content():
    try:
        playlist = Playlist.from_url(PLAYLIST)
    except (SpotifyError, RequestException) as exc:
        _skip_if_live_lookup_failed(exc)

    content = create_m3u_content(
        playlist.songs, "{title} - {output-ext}.{output-ext}", "mp3"
    )

    assert content != ""
    assert len(content.split("\n")) > 5
    assert content.split("\n")[0] == "#EXTM3U"
    assert content.split("\n")[1].startswith("#EXTINF:")
    assert content.split("\n")[2].endswith(".mp3")


def test_create_m3u_file(tmpdir, monkeypatch):
    monkeypatch.chdir(tmpdir)

    try:
        playlist = Playlist.from_url(PLAYLIST)
    except (SpotifyError, RequestException) as exc:
        _skip_if_live_lookup_failed(exc)

    create_m3u_file("test.m3u", playlist.songs, "", "mp3")
    assert tmpdir.join("test.m3u").isfile() is True
