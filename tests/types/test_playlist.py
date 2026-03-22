import pytest
from spotipy.exceptions import SpotifyException

from spotdl.types.playlist import Playlist, PlaylistError
from spotdl.types.song import Song
from spotdl.utils.spotify import SpotifyClient


def _build_playlist_tracks():
    return {
        "items": [
            {
                "track": {
                    "name": "Song One",
                    "artists": [{"name": "Artist One"}],
                    "album": {
                        "id": "album-1",
                        "name": "Album One",
                        "artists": [{"name": "Artist One"}],
                        "album_type": "single",
                        "release_date": "2024-01-01",
                        "total_tracks": 2,
                        "images": [
                            {
                                "url": "https://example.com/cover-1.jpg",
                                "width": 300,
                                "height": 300,
                            }
                        ],
                    },
                    "disc_number": 1,
                    "duration_ms": 180000,
                    "track_number": 1,
                    "id": "track-1",
                    "explicit": False,
                    "external_urls": {"spotify": "https://open.spotify.com/track/track-1"},
                    "external_ids": {"isrc": "ISRC1"},
                    "type": "track",
                }
            },
            {
                "track": {
                    "name": "Song Two",
                    "artists": [{"name": "Artist Two"}],
                    "album": {
                        "id": "album-2",
                        "name": "Album Two",
                        "artists": [{"name": "Artist Two"}],
                        "album_type": "album",
                        "release_date": "2023-02-02",
                        "total_tracks": 2,
                        "images": [
                            {
                                "url": "https://example.com/cover-2.jpg",
                                "width": 300,
                                "height": 300,
                            }
                        ],
                    },
                    "disc_number": 1,
                    "duration_ms": 200000,
                    "track_number": 2,
                    "id": "track-2",
                    "explicit": True,
                    "external_urls": {"spotify": "https://open.spotify.com/track/track-2"},
                    "external_ids": {"isrc": "ISRC2"},
                    "type": "track",
                }
            },
        ],
        "next": None,
    }


def _build_playlist_payload():
    return {
        "name": "Top 10 NCS Songs Episode 2",
        "description": "",
        "external_urls": {"spotify": "https://open.spotify.com/user/test-user"},
        "owner": {"display_name": "Test User"},
        "images": [
            {
                "url": "https://example.com/playlist-cover.jpg",
                "width": 300,
                "height": 300,
            }
        ],
    }


def test_playlist_init():
    """
    Test if Playlist class is initialized correctly.
    """

    playlist = Playlist(
        name="test",
        url="test",
        songs=[],
        urls=[],
        description="test",
        author_url="test",
        author_name="test",
        cover_url="test",
    )

    assert playlist.name == "test"
    assert playlist.url == "test"
    assert playlist.songs == []
    assert playlist.description == "test"
    assert playlist.author_url == "test"
    assert playlist.author_name == "test"


def test_playlist_wrong_initget_results():
    """
    Tests if Playlist class raises exception when initialized with wrong parameters.
    """

    with pytest.raises(TypeError):
        Playlist(
            name=1,
            url="test",
            songs=[],
            description="test",
        )  # type: ignore


def test_playlist_from_url(monkeypatch):
    """
    Tests if Playlist.from_url() works correctly.
    """

    monkeypatch.setattr(SpotifyClient, "playlist", lambda self, _: _build_playlist_payload())
    monkeypatch.setattr(
        SpotifyClient, "playlist_items", lambda self, _: _build_playlist_tracks()
    )

    playlist = Playlist.from_url(
        "https://open.spotify.com/playlist/5LkNhFidYyyjRWwnkcMbQs",
        fetch_songs=False,
    )

    assert playlist.name == "Top 10 NCS Songs Episode 2"
    assert playlist.url == "https://open.spotify.com/playlist/5LkNhFidYyyjRWwnkcMbQs"
    assert len(playlist.songs) == 2
    assert playlist.description == ""

def test_playlist_from_string(monkeypatch):
    """
    Test if Playlist class can be initialized from string.
    """

    monkeypatch.setattr(
        SpotifyClient,
        "search",
        lambda self, *_args, **_kwargs: {
            "playlists": {
                "items": [
                    {
                        "id": "37i9dQZF1DZ06evO25rXbO",
                        "name": "This Is Gorillaz",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        Playlist,
        "get_metadata",
        staticmethod(
            lambda _url: (
                {
                    "name": "This Is Gorillaz",
                    "url": "http://open.spotify.com/playlist/37i9dQZF1DZ06evO25rXbO",
                    "description": "",
                    "author_url": "https://open.spotify.com/user/test-user",
                    "author_name": "Test User",
                    "cover_url": "https://example.com/playlist-cover.jpg",
                },
                [
                    Song.from_missing_data(
                        name="Track One",
                        artist="Gorillaz",
                        artists=["Gorillaz"],
                        url="https://open.spotify.com/track/track-1",
                    ),
                    Song.from_missing_data(
                        name="Track Two",
                        artist="Gorillaz",
                        artists=["Gorillaz"],
                        url="https://open.spotify.com/track/track-2",
                    ),
                ],
            )
        ),
    )

    playlist = Playlist.from_search_term("playlist: This Is Gorillaz", fetch_songs=False)

    assert playlist.name == "This Is Gorillaz"
    assert playlist.url == "http://open.spotify.com/playlist/37i9dQZF1DZ06evO25rXbO"
    assert len(playlist.urls) > 1

def test_playlist_length(monkeypatch):
    """
    Tests if Playlist.length works correctly.
    """

    monkeypatch.setattr(SpotifyClient, "playlist", lambda self, _: _build_playlist_payload())
    monkeypatch.setattr(
        SpotifyClient, "playlist_items", lambda self, _: _build_playlist_tracks()
    )

    playlist = Playlist.from_url(
        "https://open.spotify.com/playlist/5LkNhFidYyyjRWwnkcMbQs",
        fetch_songs=False,
    )

    assert playlist.length == 2


def test_playlist_from_url_requires_user_auth(monkeypatch):
    """
    Tests if playlist auth failures give a clear next step.
    """

    monkeypatch.setattr(SpotifyClient, "playlist", lambda self, _: _build_playlist_payload())
    monkeypatch.setattr(
        SpotifyClient,
        "playlist_items",
        lambda self, _: (_ for _ in ()).throw(
            SpotifyException(
                http_status=401,
                code=-1,
                msg="Valid user authentication required",
                headers={},
            )
        ),
    )

    with pytest.raises(PlaylistError, match="--user-auth"):
        Playlist.from_url("https://open.spotify.com/playlist/5LkNhFidYyyjRWwnkcMbQs")
