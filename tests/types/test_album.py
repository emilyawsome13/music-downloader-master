import pytest

from spotdl.types.album import Album
from spotdl.utils.spotify import SpotifyClient


def _build_album_metadata():
    return {
        "id": "album-id",
        "name": "NCS: The Best of 2017",
        "artists": [{"name": "Various Artists"}],
        "album_type": "compilation",
        "release_date": "2017-12-31",
        "total_tracks": 16,
        "label": "NCS",
        "images": [],
        "tracks": {
            "items": [
                {
                    "name": f"Song {index}",
                    "artists": [{"name": f"Artist {index}"}],
                    "disc_number": 1,
                    "duration_ms": 180000,
                    "track_number": index,
                    "id": f"track-{index}",
                    "explicit": False,
                    "external_urls": {
                        "spotify": f"https://open.spotify.com/track/track-{index}"
                    },
                }
                for index in range(1, 17)
            ],
            "next": None,
        },
    }


def test_album_init():
    """
    Test if Playlist class is initialized correctly.
    """

    Album(name="test", url="test", songs=[], artist={"name": "test"}, urls=[])


def test_album_wrong_init():
    """
    Test if Playlist class raises exception when initialized with wrong parameters.
    """

    with pytest.raises(TypeError):
        Album(
            name="test",
            url="test",
        )  # type: ignore


def test_album_from_url(monkeypatch):
    """
    Test if Album class can be initialized from url.
    """

    monkeypatch.setattr(SpotifyClient, "album", lambda self, _: _build_album_metadata())
    monkeypatch.setattr(
        SpotifyClient,
        "album_tracks",
        lambda self, _: (_ for _ in ()).throw(AssertionError("album_tracks should not be called")),
    )

    album = Album.from_url(
        "https://open.spotify.com/album/4MQnUDGXmHOvnsWCpzeqWT",
        fetch_songs=False,
    )

    assert album.name == "NCS: The Best of 2017"
    assert album.url == "https://open.spotify.com/album/4MQnUDGXmHOvnsWCpzeqWT"
    assert album.artist["name"] == "Various Artists"
    assert len(album.songs) == 16


# @pytest.mark.vcr()
# def test_album_from_string():
#     """
#     Test if Album class can be initialized from string.
#     """

#     album = Album.from_search_term("album: demon days gorillaz")

#     assert album.name == "Demon Days"
#     assert album.url == "http://open.spotify.com/album/0bUTHlWbkSQysoM3VsWldT"
#     assert album.artist["name"] == "Gorillaz"
#     assert len(album.urls) == 15


def test_album_length(monkeypatch):
    """
    Tests if Album.length works correctly.
    """

    monkeypatch.setattr(SpotifyClient, "album", lambda self, _: _build_album_metadata())
    monkeypatch.setattr(
        SpotifyClient,
        "album_tracks",
        lambda self, _: (_ for _ in ()).throw(AssertionError("album_tracks should not be called")),
    )

    album = Album.from_url(
        "https://open.spotify.com/album/4MQnUDGXmHOvnsWCpzeqWT",
        fetch_songs=False,
    )

    assert album.length == 16


def test_album_from_url_without_label(monkeypatch):
    """
    Test if Album.from_url() tolerates missing optional album metadata.
    """

    monkeypatch.setattr(
        SpotifyClient,
        "album",
        lambda self, _: {
            "id": "album-id",
            "name": "Sample Album",
            "artists": [{"name": "Sample Artist"}],
            "album_type": "single",
            "release_date": "2024-01-01",
            "total_tracks": 1,
            "tracks": {
                "items": [
                    {
                        "name": "Sample Song",
                        "artists": [{"name": "Sample Artist"}],
                        "disc_number": 1,
                        "duration_ms": 180000,
                        "track_number": 1,
                        "id": "track-id",
                        "explicit": False,
                        "external_urls": {
                            "spotify": "https://open.spotify.com/track/track-id"
                        },
                    }
                ],
                "next": None,
            },
            "images": [],
        },
    )

    album = Album.from_url("https://open.spotify.com/album/album-id", fetch_songs=False)

    assert album.name == "Sample Album"
    assert album.songs[0].publisher == ""


def test_album_from_url_uses_embedded_tracks(monkeypatch):
    """
    Test if Album.from_url() reuses track data already embedded in album metadata.
    """

    monkeypatch.setattr(
        SpotifyClient,
        "album",
        lambda self, _: {
            "id": "album-id",
            "name": "Sample Album",
            "artists": [{"name": "Sample Artist"}],
            "album_type": "single",
            "release_date": "2024-01-01",
            "total_tracks": 1,
            "images": [],
            "tracks": {
                "items": [
                    {
                        "name": "Sample Song",
                        "artists": [{"name": "Sample Artist"}],
                        "disc_number": 1,
                        "duration_ms": 180000,
                        "track_number": 1,
                        "id": "track-id",
                        "explicit": False,
                        "external_urls": {
                            "spotify": "https://open.spotify.com/track/track-id"
                        },
                    }
                ],
                "next": None,
            },
        },
    )
    monkeypatch.setattr(
        SpotifyClient,
        "album_tracks",
        lambda self, _: (_ for _ in ()).throw(AssertionError("album_tracks should not be called")),
    )

    album = Album.from_url("https://open.spotify.com/album/album-id", fetch_songs=False)

    assert album.name == "Sample Album"
    assert len(album.songs) == 1
