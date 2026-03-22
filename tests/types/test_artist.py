import pytest

from spotdl.types.album import Album
from spotdl.types.artist import Artist
from spotdl.types.song import Song
from spotdl.utils.spotify import SpotifyClient


def test_artist_init():
    """
    Test if Artist class initializes correctly.
    """

    artist = Artist(
        name="test",
        songs=[],
        urls=[],
        albums=[],
        genres=[],
        url="test",
    )

    assert artist.name == "test"
    assert artist.url == "test"
    assert artist.songs == []
    assert artist.albums == []
    assert artist.genres == []


def test_artist_wrong_init():
    """
    Test if Artist class raises exception when initialized with wrong parameters.
    """

    with pytest.raises(TypeError):
        Artist(
            name="test",
            songs=[],
            urls=[],
            albums=[],
            genres=[],
            url="test",
            wrong_key="test",  # type: ignore
        )


def test_artist_from_url(monkeypatch):
    """
    Test if Artist class can be initialized from url.
    """

    monkeypatch.setattr(
        SpotifyClient,
        "artist",
        lambda self, _: {
            "id": "artist-id",
            "name": "Kontinuum",
            "genres": [],
        },
    )
    monkeypatch.setattr(
        SpotifyClient,
        "artist_albums",
        lambda self, *_args, **_kwargs: {
            "items": [
                {
                    "name": "Album One",
                    "external_urls": {
                        "spotify": "https://open.spotify.com/album/album-one"
                    },
                },
                {
                    "name": "Album Two",
                    "external_urls": {
                        "spotify": "https://open.spotify.com/album/album-two"
                    },
                },
                {
                    "name": "Album Three",
                    "external_urls": {
                        "spotify": "https://open.spotify.com/album/album-three"
                    },
                },
            ],
            "next": None,
        },
    )
    monkeypatch.setattr(
        Album,
        "from_url",
        lambda album_url, fetch_songs=False: Album(
            name="Sample Album",
            url=album_url,
            urls=[
                f"https://open.spotify.com/track/{album_url.rsplit('/', 1)[-1]}-1",
                f"https://open.spotify.com/track/{album_url.rsplit('/', 1)[-1]}-2",
            ],
            songs=[
                Song.from_missing_data(
                    name=f"Song {album_url.rsplit('/', 1)[-1]} 1",
                    artist="Kontinuum",
                    artists=["Kontinuum"],
                    url=f"https://open.spotify.com/track/{album_url.rsplit('/', 1)[-1]}-1",
                ),
                Song.from_missing_data(
                    name=f"Song {album_url.rsplit('/', 1)[-1]} 2",
                    artist="Kontinuum",
                    artists=["Kontinuum"],
                    url=f"https://open.spotify.com/track/{album_url.rsplit('/', 1)[-1]}-2",
                ),
            ],
            artist={"name": "Kontinuum"},
        ),
    )

    artist = Artist.from_url(
        "https://open.spotify.com/artist/1FPC2zwfMHhrP3frOfaai6",
        fetch_songs=False,
    )

    assert artist.name == "Kontinuum"
    assert artist.url == "https://open.spotify.com/artist/1FPC2zwfMHhrP3frOfaai6"
    assert len(artist.songs) > 1
    assert len(artist.albums) > 2


def test_artist_from_string(monkeypatch):
    """
    Test if Artist class can be initialized from string.
    """

    monkeypatch.setattr(
        SpotifyClient,
        "search",
        lambda self, *_args, **_kwargs: {
            "artists": {
                "items": [
                    {
                        "id": "3AA28KZvwAUcZuOKwyblJQ",
                        "name": "Gorillaz",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        Artist,
        "get_metadata",
        staticmethod(
            lambda _url: (
                {
                    "name": "Gorillaz",
                    "genres": [],
                    "url": "http://open.spotify.com/artist/3AA28KZvwAUcZuOKwyblJQ",
                    "albums": ["https://open.spotify.com/album/test-album"],
                },
                [
                    Song.from_missing_data(
                        name="Feel Good Inc.",
                        artist="Gorillaz",
                        artists=["Gorillaz"],
                        url="https://open.spotify.com/track/test-track",
                    )
                ],
            )
        ),
    )

    artist = Artist.from_search_term("artist: gorillaz", fetch_songs=False)
    assert artist.name == "Gorillaz"
    assert len(artist.urls) == 1


def test_artist_get_metadata_without_genres(monkeypatch):
    """
    Test if Artist.get_metadata() tolerates missing genres in Spotify metadata.
    """

    artist_album_calls = []

    monkeypatch.setattr(
        SpotifyClient,
        "artist",
        lambda self, _: {
            "id": "artist-id",
            "name": "Kontinuum",
        },
    )
    monkeypatch.setattr(
        SpotifyClient,
        "artist_albums",
        lambda self, artist_id, **kwargs: (
            artist_album_calls.append((artist_id, kwargs)),
            {
                "items": [
                    {
                        "name": "Sample Album",
                        "external_urls": {
                            "spotify": "https://open.spotify.com/album/sample-album"
                        },
                    }
                ],
                "next": None,
            },
        )[1],
    )
    monkeypatch.setattr(
        Album,
        "from_url",
        lambda *_args, **_kwargs: Album(
            name="Sample Album",
            url="https://open.spotify.com/album/sample-album",
            urls=["https://open.spotify.com/track/sample-track"],
            songs=[
                Song.from_missing_data(
                    name="Sample Song",
                    artist="Kontinuum",
                    artists=["Kontinuum"],
                    url="https://open.spotify.com/track/sample-track",
                )
            ],
            artist={"name": "Kontinuum"},
        ),
    )

    metadata, songs = Artist.get_metadata(
        "https://open.spotify.com/artist/1FPC2zwfMHhrP3frOfaai6"
    )

    assert metadata["name"] == "Kontinuum"
    assert metadata["genres"] == []
    assert artist_album_calls == [
        (
            "artist-id",
            {
                "include_groups": "album,single,compilation",
                "limit": 10,
            },
        )
    ]
    assert len(songs) == 1
