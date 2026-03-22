import asyncio
import zipfile
from argparse import Namespace
from pathlib import Path

from spotdl.types.options import DownloaderOptions
from spotdl.types.song import Song
from spotdl.utils import web as web_utils
from spotdl.utils.config import DOWNLOADER_OPTIONS, create_settings_type


class FakeWebSocket:
    def __init__(self):
        self.messages = []
        self.accepted = False

    async def accept(self):
        self.accepted = True
        return None

    async def send_json(self, payload):
        self.messages.append(payload)


class FakeDownloader:
    def __init__(self, settings, loop=None):
        self.settings = settings
        self.loop = loop
        self.progress_handler = type("ProgressHolder", (), {"web_ui": False})()


def _build_song():
    return Song.from_missing_data(
        name="Dashboard Song",
        artists=["Debug Artist"],
        artist="Debug Artist",
        genres=[],
        disc_number=1,
        disc_count=1,
        album_name="Debug Album",
        album_artist="Debug Artist",
        duration=180,
        year=2026,
        date="2026-03-22",
        track_number=1,
        tracks_count=1,
        song_id="debug-song-id",
        explicit=False,
        publisher="",
        url="https://music.youtube.com/watch?v=debug-song-id",
        isrc=None,
        cover_url=None,
        copyright_text=None,
        download_url="https://music.youtube.com/watch?v=debug-song-id",
    )


def test_client_handle_song_update_tracks_stats(monkeypatch):
    monkeypatch.setattr(web_utils, "Downloader", FakeDownloader)

    web_utils.app_state.web_settings = {
        "host": "127.0.0.1",
        "port": 8800,
        "keep_alive": True,
        "web_use_output_dir": False,
        "keep_sessions": True,
    }
    web_utils.app_state.downloader_settings = DownloaderOptions(
        **create_settings_type(Namespace(config=False), {}, DOWNLOADER_OPTIONS)
    )
    web_utils.app_state.loop = asyncio.new_event_loop()

    websocket = FakeWebSocket()
    client = web_utils.Client(websocket, "dashboard-test")
    song = _build_song()

    asyncio.run(
        client.handle_song_update(
            0,
            {
                "song": song.json,
                "progress": 48,
                "message": "Downloading",
                "overall_progress": 48,
                "overall_completed": 0,
                "overall_total": 1,
            },
        )
    )
    asyncio.run(
        client.handle_song_update(
            0,
            {
                "song": song.json,
                "progress": 100,
                "message": "Done",
                "overall_progress": 100,
                "overall_completed": 1,
                "overall_total": 1,
            },
        )
    )

    snapshot = client.get_state_snapshot()

    assert snapshot["stats"]["total"] == 1
    assert snapshot["stats"]["completed"] == 1
    assert snapshot["songs"][0]["status"] == "done"
    assert websocket.messages[-1]["type"] == "state"


def test_finish_query_download_creates_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(web_utils, "Downloader", FakeDownloader)
    monkeypatch.setattr(web_utils, "get_spotdl_path", lambda: Path(tmp_path))

    web_utils.app_state.web_settings = {
        "host": "127.0.0.1",
        "port": 8800,
        "keep_alive": True,
        "web_use_output_dir": False,
        "keep_sessions": True,
    }
    web_utils.app_state.downloader_settings = DownloaderOptions(
        **create_settings_type(Namespace(config=False), {}, DOWNLOADER_OPTIONS)
    )
    web_utils.app_state.loop = asyncio.new_event_loop()

    websocket = FakeWebSocket()
    client = web_utils.Client(websocket, "bundle-test")
    song = _build_song()

    output_dir = Path(client.get_output_root()) / "Debug Artist" / "Debug Album"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "Dashboard Song.mp3"
    output_file.write_bytes(b"fake audio bytes")

    asyncio.run(client.finish_query_download([(song, output_file)], [], 0))

    snapshot = client.get_state_snapshot()
    bundle = snapshot["bundle"]

    assert bundle is not None
    assert Path(bundle["path"]).is_file()
    assert bundle["count"] == 1

    with zipfile.ZipFile(bundle["path"]) as archive:
        assert archive.namelist() == ["Debug Artist/Debug Album/Dashboard Song.mp3"]


def test_update_settings_falls_back_from_blank_values(monkeypatch):
    monkeypatch.setattr(web_utils, "Downloader", FakeDownloader)

    web_utils.app_state.web_settings = {
        "host": "127.0.0.1",
        "port": 8800,
        "keep_alive": True,
        "web_use_output_dir": False,
        "keep_sessions": True,
    }
    web_utils.app_state.downloader_settings = DownloaderOptions(
        **create_settings_type(Namespace(config=False), {}, DOWNLOADER_OPTIONS)
    )
    web_utils.app_state.loop = asyncio.new_event_loop()
    web_utils.app_state.logger = web_utils.logging.getLogger("spotdl-web-test")

    websocket = FakeWebSocket()
    client = web_utils.Client(websocket, "blank-settings-test")

    updated = web_utils.update_settings(
        {
            "audio_providers": [""],
            "bitrate": "",
            "format": "",
            "output": "",
        },
        client=client,
        state=web_utils.app_state,
    )

    assert updated["audio_providers"] == ["youtube-music", "youtube"]
    assert updated["bitrate"] == "128k"
    assert updated["format"] == "mp3"
    assert updated["output"] == "{album-artist}/{album}/{title}.{output-ext}"


def test_client_normalizes_legacy_web_defaults(monkeypatch):
    monkeypatch.setattr(web_utils, "Downloader", FakeDownloader)

    web_utils.app_state.web_settings = {
        "host": "127.0.0.1",
        "port": 8800,
        "keep_alive": True,
        "web_use_output_dir": False,
        "keep_sessions": True,
    }
    web_utils.app_state.downloader_settings = DownloaderOptions(
        **create_settings_type(
            Namespace(config=False),
            {
                "audio_providers": ["youtube-music"],
                "output": "{artists} - {title}.{output-ext}",
            },
            DOWNLOADER_OPTIONS,
        )
    )
    web_utils.app_state.loop = asyncio.new_event_loop()

    websocket = FakeWebSocket()
    client = web_utils.Client(websocket, "legacy-settings-test")

    assert client.downloader_settings["audio_providers"] == [
        "youtube-music",
        "youtube",
    ]
    assert (
        client.downloader_settings["output"]
        == "{album-artist}/{album}/{title}.{output-ext}"
    )


def test_finish_query_download_deduplicates_bundle_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(web_utils, "Downloader", FakeDownloader)
    monkeypatch.setattr(web_utils, "get_spotdl_path", lambda: Path(tmp_path))

    web_utils.app_state.web_settings = {
        "host": "127.0.0.1",
        "port": 8800,
        "keep_alive": True,
        "web_use_output_dir": False,
        "keep_sessions": True,
    }
    web_utils.app_state.downloader_settings = DownloaderOptions(
        **create_settings_type(Namespace(config=False), {}, DOWNLOADER_OPTIONS)
    )
    web_utils.app_state.loop = asyncio.new_event_loop()

    websocket = FakeWebSocket()
    client = web_utils.Client(websocket, "bundle-dedupe-test")
    song = _build_song()

    output_dir = Path(client.get_output_root())
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "Dashboard Song.mp3"
    output_file.write_bytes(b"fake audio bytes")

    asyncio.run(
        client.finish_query_download([(song, output_file), (song, output_file)], [], 0)
    )

    snapshot = client.get_state_snapshot()
    bundle = snapshot["bundle"]

    assert len(snapshot["downloads"]) == 1

    with zipfile.ZipFile(bundle["path"]) as archive:
        assert archive.namelist() == ["Dashboard Song.mp3"]


def test_client_get_download_output_uses_session_template(monkeypatch, tmp_path):
    monkeypatch.setattr(web_utils, "Downloader", FakeDownloader)
    monkeypatch.setattr(web_utils, "get_spotdl_path", lambda: Path(tmp_path))

    web_utils.app_state.web_settings = {
        "host": "127.0.0.1",
        "port": 8800,
        "keep_alive": True,
        "web_use_output_dir": False,
        "keep_sessions": True,
    }
    web_utils.app_state.downloader_settings = DownloaderOptions(
        **create_settings_type(
            Namespace(config=False),
            {"output": "{album-artist}/{album}/{title}.{output-ext}"},
            DOWNLOADER_OPTIONS,
        )
    )
    web_utils.app_state.loop = asyncio.new_event_loop()

    websocket = FakeWebSocket()
    client = web_utils.Client(websocket, "session-output-test")

    assert client.get_output_root() == str(
        (Path(tmp_path) / "web/sessions/session-output-test").absolute()
    )
    assert client.get_download_output() == str(
        (
            Path(tmp_path)
            / "web/sessions/session-output-test/{album-artist}/{album}/{title}.{output-ext}"
        ).absolute()
    )


def test_start_download_query_clears_session_output(monkeypatch, tmp_path):
    monkeypatch.setattr(web_utils, "Downloader", FakeDownloader)
    monkeypatch.setattr(web_utils, "get_spotdl_path", lambda: Path(tmp_path))

    async def fake_run_download_query_task(_query, _job_token, _output_root):
        return None

    created_queries = []

    def fake_create_task(coro):
        created_queries.append(coro)
        coro.close()
        return type("FakeTask", (), {"done": lambda self: False})()

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    web_utils.app_state.web_settings = {
        "host": "127.0.0.1",
        "port": 8800,
        "keep_alive": True,
        "web_use_output_dir": False,
        "keep_sessions": True,
    }
    web_utils.app_state.downloader_settings = DownloaderOptions(
        **create_settings_type(Namespace(config=False), {}, DOWNLOADER_OPTIONS)
    )
    web_utils.app_state.loop = asyncio.new_event_loop()

    websocket = FakeWebSocket()
    client = web_utils.Client(websocket, "session-clear-test")
    monkeypatch.setattr(
        client, "_run_download_query_task", fake_run_download_query_task
    )

    output_dir = Path(client.get_output_root())
    output_dir.mkdir(parents=True, exist_ok=True)
    stale_file = output_dir / "stale.mp3"
    stale_file.write_bytes(b"old bytes")

    asyncio.run(client.start_download_query("ytartist: Test Artist"))

    assert not stale_file.exists()
    assert len(created_queries) == 1
    assert client.current_job["output_root"].endswith("job-1")


def test_handle_song_update_exposes_partial_downloads(monkeypatch, tmp_path):
    monkeypatch.setattr(web_utils, "Downloader", FakeDownloader)
    monkeypatch.setattr(web_utils, "get_spotdl_path", lambda: Path(tmp_path))

    web_utils.app_state.web_settings = {
        "host": "127.0.0.1",
        "port": 8800,
        "keep_alive": True,
        "web_use_output_dir": False,
        "keep_sessions": True,
    }
    web_utils.app_state.downloader_settings = DownloaderOptions(
        **create_settings_type(Namespace(config=False), {}, DOWNLOADER_OPTIONS)
    )
    web_utils.app_state.loop = asyncio.new_event_loop()

    websocket = FakeWebSocket()
    client = web_utils.Client(websocket, "partial-downloads-test")
    song = _build_song()

    output_dir = Path(client.get_output_root()) / "Debug Artist" / "Debug Album"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "Dashboard Song.mp3"
    output_file.write_bytes(b"fake audio bytes")

    asyncio.run(
        client.handle_song_update(
            0,
            {
                "song": song.json,
                "progress": 100,
                "message": "Done",
                "overall_progress": 50,
                "overall_completed": 1,
                "overall_total": 2,
            },
        )
    )

    snapshot = client.get_state_snapshot()
    assert len(snapshot["downloads"]) == 1
    assert snapshot["downloads"][0]["path"] == str(output_file.absolute())
    assert snapshot["bundle"] is not None


def test_get_client_restores_session_downloads_without_websocket(monkeypatch, tmp_path):
    monkeypatch.setattr(web_utils, "Downloader", FakeDownloader)
    monkeypatch.setattr(web_utils, "get_spotdl_path", lambda: Path(tmp_path))

    web_utils.app_state.web_settings = {
        "host": "127.0.0.1",
        "port": 8800,
        "keep_alive": True,
        "web_use_output_dir": False,
        "keep_sessions": True,
    }
    web_utils.app_state.downloader_settings = DownloaderOptions(
        **create_settings_type(Namespace(config=False), {}, DOWNLOADER_OPTIONS)
    )
    web_utils.app_state.loop = asyncio.new_event_loop()
    web_utils.app_state.clients = {}

    output_dir = (
        Path(tmp_path) / "web/sessions/restored-client/Debug Artist/Debug Album"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "Dashboard Song.mp3"
    output_file.write_bytes(b"fake audio bytes")

    restored_client = web_utils.get_client("restored-client")

    assert restored_client.websocket is None
    assert len(restored_client.completed_downloads) == 1
    assert restored_client.completed_downloads[0]["path"] == str(output_file.absolute())
    assert restored_client.download_bundle is not None
    assert web_utils.app_state.clients["restored-client"] is restored_client


def test_reconnect_preserves_existing_client_state(monkeypatch):
    monkeypatch.setattr(web_utils, "Downloader", FakeDownloader)

    web_utils.app_state.web_settings = {
        "host": "127.0.0.1",
        "port": 8800,
        "keep_alive": True,
        "web_use_output_dir": False,
        "keep_sessions": True,
    }
    web_utils.app_state.downloader_settings = DownloaderOptions(
        **create_settings_type(Namespace(config=False), {}, DOWNLOADER_OPTIONS)
    )
    web_utils.app_state.loop = asyncio.new_event_loop()
    web_utils.app_state.clients = {}

    first_socket = FakeWebSocket()
    client = web_utils.Client(first_socket, "reconnect-client")
    asyncio.run(client.connect())

    song = _build_song()
    asyncio.run(
        client.handle_song_update(
            0,
            {
                "song": song.json,
                "progress": 48,
                "message": "Downloading",
                "overall_progress": 48,
                "overall_completed": 0,
                "overall_total": 1,
            },
        )
    )
    client.detach_websocket(first_socket)

    replacement_socket = FakeWebSocket()
    restored_client = web_utils.get_client("reconnect-client")
    restored_client.attach_websocket(replacement_socket)
    asyncio.run(restored_client.connect())

    assert restored_client is client
    assert restored_client.song_states
    assert restored_client.current_job["status"] == "idle"
    assert restored_client.song_states[song.url]["message"] == "Downloading"
    assert replacement_socket.accepted is True
    assert (
        replacement_socket.messages[-1]["state"]["songs"][0]["message"] == "Downloading"
    )


def test_favicon_route_serves_bundled_asset():
    response = web_utils.favicon()
    response_path = str(response.path)

    assert response_path.endswith(
        "local-web-ui\\favicon.svg"
    ) or response_path.endswith("local-web-ui/favicon.svg")
    assert response.media_type == "image/svg+xml"


def test_cancel_download_query_marks_session_cancelled(monkeypatch):
    monkeypatch.setattr(web_utils, "Downloader", FakeDownloader)

    web_utils.app_state.web_settings = {
        "host": "127.0.0.1",
        "port": 8800,
        "keep_alive": True,
        "web_use_output_dir": False,
        "keep_sessions": True,
    }
    web_utils.app_state.downloader_settings = DownloaderOptions(
        **create_settings_type(Namespace(config=False), {}, DOWNLOADER_OPTIONS)
    )
    web_utils.app_state.loop = asyncio.new_event_loop()

    async def runner():
        websocket = FakeWebSocket()
        client = web_utils.Client(websocket, "cancel-test")
        client.current_job_token = 1
        client.current_job.update(
            {
                "status": "running",
                "query": "ytartist: Test Artist",
                "message": "Downloading",
                "job_token": 1,
            }
        )
        client.song_states["song-1"] = {
            "status": "downloading",
            "message": "Downloading",
            "updated_at": client._timestamp(),
        }

        blocker = asyncio.create_task(asyncio.sleep(60))
        client.download_task = blocker

        snapshot = await client.cancel_download_query()
        await asyncio.sleep(0)

        assert snapshot["job"]["status"] == "cancelled"
        assert snapshot["job"]["error"] == "Cancelled by user."
        assert client.song_states["song-1"]["status"] == "cancelled"
        assert client.download_task is None
        assert blocker.cancelled()
        assert client.current_job_token == 2

    asyncio.run(runner())


def test_stale_song_update_is_ignored_after_cancel(monkeypatch):
    monkeypatch.setattr(web_utils, "Downloader", FakeDownloader)

    web_utils.app_state.web_settings = {
        "host": "127.0.0.1",
        "port": 8800,
        "keep_alive": True,
        "web_use_output_dir": False,
        "keep_sessions": True,
    }
    web_utils.app_state.downloader_settings = DownloaderOptions(
        **create_settings_type(Namespace(config=False), {}, DOWNLOADER_OPTIONS)
    )
    web_utils.app_state.loop = asyncio.new_event_loop()

    websocket = FakeWebSocket()
    client = web_utils.Client(websocket, "stale-update-test")
    client.current_job_token = 2

    song = _build_song()
    asyncio.run(
        client.handle_song_update(
            1,
            {
                "song": song.json,
                "progress": 50,
                "message": "Downloading",
                "overall_progress": 50,
                "overall_completed": 0,
                "overall_total": 1,
            },
        )
    )

    assert client.song_states == {}
