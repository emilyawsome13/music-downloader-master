import pytest
from requests.exceptions import RequestException

from spotdl.types.saved import SavedError
from spotdl.types.song import Song
from spotdl.utils import search as search_utils
from spotdl.utils.search import (
    create_ytm_artist,
    get_search_results,
    get_simple_songs,
    parse_query,
)
from spotdl.utils.spotify import SpotifyError

SONG = ["https://open.spotify.com/track/2Ikdgh3J5vCRmnCL3Xcrtv"]
PLAYLIST = ["https://open.spotify.com/playlist/78Lg6HmUqlTnmipvNxc536"]
ALBUM = ["https://open.spotify.com/album/4MQnUDGXmHOvnsWCpzeqWT"]
YT = [
    "https://www.youtube.com/watch?v=BZKwsPIhVO8|https://open.spotify.com/track/4B2kkxg3wKSTZw5JPaUtzQ"
]
ARTIST = ["https://open.spotify.com/artist/1FPC2zwfMHhrP3frOfaai6"]
ALBUM_SEARCH = ["album: yeezus"]

QUERY = SONG + PLAYLIST + ALBUM + YT + ARTIST

SAVED = ["saved"]


def _skip_if_live_lookup_failed(exc: Exception) -> None:
    """
    Skip tests that depend on live Spotify metadata when the upstream request is flaky.
    """

    pytest.skip(f"Spotify metadata lookup failed: {exc}")


@pytest.mark.vcr()
def test_parse_song():
    try:
        songs = parse_query(SONG)
    except (SpotifyError, RequestException) as exc:
        _skip_if_live_lookup_failed(exc)

    if len(songs) == 0:
        pytest.skip("Spotify metadata lookup did not return any songs")

    song = songs[0]
    assert len(songs) == 1
    assert song.download_url == None


@pytest.mark.vcr()
def test_parse_album():
    try:
        songs = parse_query(ALBUM)
    except (SpotifyError, RequestException) as exc:
        _skip_if_live_lookup_failed(exc)

    if len(songs) == 0:
        pytest.skip("Spotify metadata lookup did not return any songs")

    assert len(songs) > 1
    assert songs[0].url == "https://open.spotify.com/track/2Ikdgh3J5vCRmnCL3Xcrtv"


@pytest.mark.vcr()
def test_parse_yt_link():
    try:
        songs = parse_query(YT)
    except (SpotifyError, RequestException) as exc:
        _skip_if_live_lookup_failed(exc)

    if len(songs) == 0:
        pytest.skip("Spotify metadata lookup did not return any songs")

    assert len(songs) == 1
    assert songs[0].url == "https://open.spotify.com/track/4B2kkxg3wKSTZw5JPaUtzQ"
    assert songs[0].download_url == "https://www.youtube.com/watch?v=BZKwsPIhVO8"


@pytest.mark.vcr()
def test_parse_artist():
    try:
        songs = parse_query(ARTIST)
    except (SpotifyError, RequestException) as exc:
        _skip_if_live_lookup_failed(exc)

    if len(songs) == 0:
        pytest.skip("Spotify metadata lookup did not return any songs")

    assert len(songs) > 1


@pytest.mark.vcr()
def test_parse_album_search():
    try:
        songs = parse_query(ALBUM_SEARCH)
    except (SpotifyError, RequestException) as exc:
        _skip_if_live_lookup_failed(exc)

    if len(songs) == 0:
        pytest.skip("Spotify metadata lookup did not return any songs")

    assert len(songs) > 0


@pytest.mark.vcr()
def test_parse_saved():
    with pytest.raises(SavedError):
        parse_query(SAVED)


def test_parse_query():
    try:
        songs = parse_query(QUERY)
    except (SpotifyError, RequestException) as exc:
        _skip_if_live_lookup_failed(exc)

    if len(songs) == 0:
        pytest.skip("Spotify metadata lookup did not return any songs")

    assert len(songs) > 1


@pytest.mark.vcr()
def test_get_search_results():
    try:
        results = get_search_results("test")
    except (SpotifyError, RequestException) as exc:
        _skip_if_live_lookup_failed(exc)

    assert len(results) > 1


def test_create_empty_song():
    song = Song.from_missing_data(name="test")
    assert song.name == "test"
    assert song.url == None
    assert song.download_url == None
    assert song.duration == None
    assert song.artists == None


@pytest.mark.vcr()
def test_get_simple_songs():
    try:
        songs = get_simple_songs(QUERY)
    except (SpotifyError, RequestException) as exc:
        _skip_if_live_lookup_failed(exc)

    if len(songs) == 0:
        pytest.skip("Spotify metadata lookup did not return any songs")

    assert len(songs) > 1


class FakeYTMusic:
    def search(self, query, filter=None, limit=20):
        if filter == "artists":
            return [
                {
                    "artist": "Test Artist",
                    "browseId": "UC_TEST_ARTIST",
                    "resultType": "artist",
                }
            ]

        if filter == "albums":
            return [
                {
                    "title": "First Album",
                    "browseId": "MPRE_ALBUM_ONE",
                    "artists": [{"name": "Test Artist", "id": "UC_TEST_ARTIST"}],
                    "type": "Album",
                },
                {
                    "title": "Wrong Artist Album",
                    "browseId": "MPRE_NOT_MINE",
                    "artists": [{"name": "Someone Else", "id": "UC_OTHER"}],
                    "type": "Album",
                },
            ]

        raise AssertionError(f"Unexpected search: {query=} {filter=} {limit=}")

    def get_artist(self, browse_id):
        assert browse_id == "UC_TEST_ARTIST"
        return {
            "name": "Test Artist",
            "albums": {
                "results": [{"title": "First Album", "browseId": "MPRE_ALBUM_ONE"}]
            },
            "singles": {
                "results": [{"title": "Loose Single", "browseId": "MPRE_SINGLE_ONE"}]
            },
            "songs": {"results": []},
            "thumbnails": [
                {
                    "url": "https://example.com/artist-small.jpg",
                    "width": 100,
                    "height": 100,
                },
                {
                    "url": "https://example.com/artist-large.jpg",
                    "width": 500,
                    "height": 500,
                },
            ],
        }

    def get_album(self, browse_id):
        albums = {
            "MPRE_ALBUM_ONE": {
                "title": "First Album",
                "artists": [{"name": "Test Artist", "id": "UC_TEST_ARTIST"}],
                "year": "2024",
                "trackCount": 2,
                "type": "Album",
                "thumbnails": [
                    {
                        "url": "https://example.com/album-cover.jpg",
                        "width": 400,
                        "height": 400,
                    }
                ],
                "tracks": [
                    {
                        "videoId": "video-one",
                        "title": "Song One",
                        "artists": [{"name": "Test Artist", "id": "UC_TEST_ARTIST"}],
                        "trackNumber": 1,
                        "duration_seconds": 201,
                        "isExplicit": False,
                        "isAvailable": True,
                    },
                    {
                        "videoId": "video-two",
                        "title": "Song Two",
                        "artists": [{"name": "Test Artist", "id": "UC_TEST_ARTIST"}],
                        "trackNumber": 2,
                        "duration_seconds": 180,
                        "isExplicit": True,
                        "isAvailable": True,
                    },
                ],
            },
            "MPRE_SINGLE_ONE": {
                "title": "Loose Single",
                "artists": [{"name": "Test Artist", "id": "UC_TEST_ARTIST"}],
                "year": "2025",
                "trackCount": 1,
                "type": "Single",
                "thumbnails": [
                    {
                        "url": "https://example.com/single-cover.jpg",
                        "width": 320,
                        "height": 320,
                    }
                ],
                "tracks": [
                    {
                        "videoId": "video-three",
                        "title": "Loose Single",
                        "artists": [{"name": "Test Artist", "id": "UC_TEST_ARTIST"}],
                        "trackNumber": 1,
                        "duration_seconds": 210,
                        "isExplicit": False,
                        "isAvailable": True,
                    }
                ],
            },
        }
        return albums[browse_id]


def test_create_ytm_artist_query(monkeypatch):
    monkeypatch.setattr(search_utils, "get_ytm_client", lambda: FakeYTMusic())

    artist = create_ytm_artist("ytartist: Test Artist", fetch_songs=False)

    assert artist.name == "Test Artist"
    assert artist.url == "https://music.youtube.com/channel/UC_TEST_ARTIST"
    assert len(artist.songs) == 3
    assert artist.songs[0].download_url == "https://music.youtube.com/watch?v=video-one"
    assert artist.songs[0].album_artist == "Test Artist"
    assert artist.songs[0].album_id == "MPRE_ALBUM_ONE"
    assert artist.songs[0].tracks_count == 2


def test_get_simple_songs_ytm_artist_url(monkeypatch):
    monkeypatch.setattr(search_utils, "get_ytm_client", lambda: FakeYTMusic())

    songs = get_simple_songs(["https://music.youtube.com/channel/UC_TEST_ARTIST"])

    assert len(songs) == 3
    assert songs[0].url == "https://music.youtube.com/watch?v=video-one"
    assert songs[1].explicit is True
    assert songs[2].album_name == "Loose Single"


def test_create_ytm_artist_youtube_handle(monkeypatch):
    monkeypatch.setattr(search_utils, "get_ytm_client", lambda: FakeYTMusic())
    monkeypatch.setattr(
        search_utils,
        "_resolve_youtube_artist_browse_id",
        lambda _url: "UC_TEST_ARTIST",
    )

    artist = create_ytm_artist("https://www.youtube.com/@TestArtist")

    assert artist.name == "Test Artist"
    assert artist.url == "https://music.youtube.com/channel/UC_TEST_ARTIST"
    assert len(artist.songs) == 3


def test_get_simple_songs_mobile_youtube_channel_url(monkeypatch):
    monkeypatch.setattr(search_utils, "get_ytm_client", lambda: FakeYTMusic())

    songs = get_simple_songs(["https://m.youtube.com/channel/UC_TEST_ARTIST"])

    assert len(songs) == 3
    assert songs[0].album_artist == "Test Artist"
    assert songs[0].album_name == "First Album"


def test_create_ytm_artist_mobile_youtube_handle(monkeypatch):
    monkeypatch.setattr(search_utils, "get_ytm_client", lambda: FakeYTMusic())
    monkeypatch.setattr(
        search_utils,
        "_resolve_youtube_artist_browse_id",
        lambda _url: "UC_TEST_ARTIST",
    )

    artist = create_ytm_artist("https://m.youtube.com/@TestArtist")

    assert artist.name == "Test Artist"
    assert artist.url == "https://music.youtube.com/channel/UC_TEST_ARTIST"
    assert len(artist.songs) == 3
