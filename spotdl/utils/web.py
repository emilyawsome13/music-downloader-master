"""
Module which contains the web server related function
FastAPI routes/classes etc.
"""

import argparse
import asyncio
import datetime
import logging
import mimetypes
import os
import shutil
import traceback
import zipfile
from argparse import Namespace
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fastapi import (
    APIRouter,
    Body,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope
from uvicorn import Server

from spotdl._version import __version__
from spotdl.download.downloader import Downloader
from spotdl.download.progress_handler import ProgressHandler, SongTracker
from spotdl.types.album import Album
from spotdl.types.artist import Artist
from spotdl.types.options import (
    DownloaderOptionalOptions,
    DownloaderOptions,
    WebOptions,
)
from spotdl.types.playlist import Playlist
from spotdl.types.song import Song
from spotdl.utils.arguments import create_parser
from spotdl.utils.config import (
    DOWNLOADER_OPTIONS,
    create_settings_type,
    get_spotdl_path,
)
from spotdl.utils.github import RateLimitError, get_latest_version, get_status
from spotdl.utils.search import get_search_results, get_simple_songs

__all__ = [
    "ALLOWED_ORIGINS",
    "SPAStaticFiles",
    "Client",
    "ApplicationState",
    "router",
    "app_state",
    "get_current_state",
    "get_client",
    "websocket_endpoint",
    "song_from_url",
    "query_search",
    "session_state",
    "download_query",
    "download_url",
    "download_file",
    "download_bundle",
    "get_settings",
    "update_settings",
    "fix_mime_types",
]

ALLOWED_ORIGINS = [
    "http://localhost:8800",
    "http://127.0.0.1:8800",
    "https://localhost:8800",
    "https://127.0.0.1:8800",
]

DEFAULT_WEB_OUTPUT_TEMPLATE = "{album-artist}/{album}/{title}.{output-ext}"
LEGACY_WEB_OUTPUT_TEMPLATE = "{artists} - {title}.{output-ext}"


def _normalize_web_audio_providers(providers: Optional[List[str]]) -> List[str]:
    """
    Expand the primary audio provider into a small fallback chain for the web UI.

    ### Arguments
    - providers: current provider list

    ### Returns
    - normalized provider list
    """

    normalized = [
        provider.strip()
        for provider in providers or []
        if isinstance(provider, str) and provider.strip()
    ]
    if len(normalized) == 0:
        normalized = ["youtube-music"]

    fallback_map = {
        "youtube-music": ["youtube-music", "youtube"],
        "youtube": ["youtube", "youtube-music"],
        "soundcloud": ["soundcloud", "youtube-music", "youtube"],
        "bandcamp": ["bandcamp", "youtube-music", "youtube"],
        "piped": ["piped", "youtube", "youtube-music"],
    }

    expanded: List[str] = []
    for provider in normalized:
        for candidate in fallback_map.get(provider, [provider]):
            if candidate not in expanded:
                expanded.append(candidate)

    return expanded


def _normalize_web_output_template(output: Optional[str]) -> str:
    """
    Normalize the output template used by the web dashboard.

    ### Arguments
    - output: requested output template

    ### Returns
    - normalized output template
    """

    if output is None:
        return DEFAULT_WEB_OUTPUT_TEMPLATE

    output = output.strip()
    if output == "" or output == LEGACY_WEB_OUTPUT_TEMPLATE:
        return DEFAULT_WEB_OUTPUT_TEMPLATE

    return output


def _normalize_web_downloader_settings(settings: Dict[str, Any]) -> DownloaderOptions:
    """
    Apply web-dashboard-specific defaults and migrations to downloader settings.

    ### Arguments
    - settings: raw downloader settings

    ### Returns
    - normalized downloader settings
    """

    settings_cpy = dict(settings)
    settings_cpy["audio_providers"] = _normalize_web_audio_providers(
        settings_cpy.get("audio_providers")
    )
    settings_cpy["output"] = _normalize_web_output_template(
        settings_cpy.get("output")
    )

    return DownloaderOptions(**settings_cpy)  # type: ignore[arg-type]


def _is_path_within_root(file_path: Path, root_path: Path) -> bool:
    """
    Check whether a file path is inside a root directory.

    ### Arguments
    - file_path: candidate file path
    - root_path: allowed root directory

    ### Returns
    - whether the file path is inside the root
    """

    try:
        file_path.resolve().relative_to(root_path.resolve())
        return True
    except ValueError:
        return False


class SPAStaticFiles(StaticFiles):
    """
    Override the static files to serve the index.html and other assets.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        """
        Serve static files from the SPA.

        ### Arguments
        - path: The path to the file.
        - scope: The scope of the request.

        ### Returns
        - returns the response.
        """

        response = await super().get_response(path, scope)
        if response.status_code == 404:
            response = await super().get_response(".", scope)

        response.headers.setdefault(
            "Cache-Control", "max-age=0, no-cache, no-store, , must-revalidate"
        )
        response.headers.setdefault("Pragma", "no-cache")
        response.headers.setdefault("Expires", "0")

        return response


class Client:
    """
    Holds the client's state.
    """

    def __init__(
        self,
        websocket: Optional[WebSocket],
        client_id: str,
    ):
        """
        Initialize the WebSocket handler.
        ### Arguments
        - websocket: The WebSocket instance.
        - client_id: The client's ID.
        - downloader_settings: The downloader settings.
        """

        self.downloader_settings = _normalize_web_downloader_settings(
            create_settings_type(
                Namespace(config=False),
                dict(app_state.downloader_settings),
                DOWNLOADER_OPTIONS,
            )  # type: ignore
        )

        self.websocket: Optional[WebSocket] = websocket
        self.client_id = client_id
        self.downloader = Downloader(
            settings=self.downloader_settings, loop=app_state.loop
        )

        self.downloader.progress_handler.web_ui = True
        self.download_task: Optional[asyncio.Task] = None
        self.events: List[Dict[str, Any]] = []
        self.song_states: Dict[str, Dict[str, Any]] = {}
        self.completed_downloads: List[Dict[str, Any]] = []
        self.download_bundle: Optional[Dict[str, Any]] = None
        self.latest_update: Optional[Dict[str, Any]] = None
        self.current_job: Dict[str, Any] = {
            "status": "idle",
            "query": None,
            "message": "Ready",
            "started_at": None,
            "finished_at": None,
            "resolved_count": 0,
            "error": None,
            "output_root": self.get_output_root(),
        }

    def attach_websocket(self, websocket: WebSocket):
        """
        Attach a websocket connection to an existing client session.

        ### Arguments
        - websocket: the websocket to attach
        """

        self.websocket = websocket

    def detach_websocket(self, websocket: WebSocket):
        """
        Detach the websocket if it is still the active one.

        ### Arguments
        - websocket: the websocket to detach
        """

        if self.websocket is websocket:
            self.websocket = None

    @staticmethod
    def _timestamp() -> str:
        """
        Get a human-readable timestamp.

        ### Returns
        - ISO formatted timestamp
        """

        return datetime.datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _song_key(song: Song) -> str:
        """
        Get a stable key for a song.

        ### Arguments
        - song: the song to identify

        ### Returns
        - stable key
        """

        if song.url:
            return song.url

        if song.song_id:
            return song.song_id

        return song.display_name

    @staticmethod
    def _normalize_status(message: str) -> str:
        """
        Normalize a progress message to a compact status string.

        ### Arguments
        - message: the human-readable message

        ### Returns
        - normalized status
        """

        mapping = {
            "processing": "queued",
            "downloading": "downloading",
            "converting": "converting",
            "embedding metadata": "embedding",
            "done": "done",
            "error": "error",
            "skipped": "skipped",
        }
        return mapping.get(message.strip().lower(), message.strip().lower())

    def get_output_root(self) -> str:
        """
        Get the output root for the current client.

        ### Returns
        - output directory root
        """

        if app_state.web_settings.get("web_use_output_dir", False):
            return str(
                Path(self.downloader_settings["output"].split("{", 1)[0]).absolute()
            )

        return str((get_spotdl_path() / f"web/sessions/{self.client_id}").absolute())

    def get_download_output(self) -> str:
        """
        Get the downloader output value for the current client.

        ### Returns
        - output template/path passed to the downloader
        """

        if app_state.web_settings.get("web_use_output_dir", False):
            return self.downloader_settings["output"]

        return str(
            (Path(self.get_output_root()) / self.downloader_settings["output"]).absolute()
        )

    def get_output_root_path(self) -> Path:
        """
        Get the current output root as a Path object.

        ### Returns
        - output root path
        """

        return Path(self.get_output_root()).absolute()

    def _create_download_record(self, file_path: Path) -> Dict[str, Any]:
        """
        Create a download record from a file on disk.

        ### Arguments
        - file_path: downloaded file path

        ### Returns
        - serializable download record
        """

        absolute_path = str(file_path.absolute())
        display_name = file_path.stem
        source_url = None

        for song_state in self.song_states.values():
            if song_state.get("path") == absolute_path:
                display_name = song_state.get("display_name") or display_name
                source_url = (song_state.get("song") or {}).get("url")
                break

        return {
            "display_name": display_name,
            "path": absolute_path,
            "url": source_url,
        }

    def _refresh_completed_downloads_from_output(self):
        """
        Refresh completed download records and zip bundle from files on disk.
        """

        output_root = self.get_output_root_path()
        output_format = self.downloader_settings["format"]

        completed_downloads = []
        seen_paths = set()
        if output_root.exists():
            for file_path in sorted(output_root.rglob(f"*.{output_format}")):
                absolute_path = str(file_path.absolute())
                if absolute_path in seen_paths:
                    continue

                seen_paths.add(absolute_path)
                completed_downloads.append(self._create_download_record(file_path))

        self.completed_downloads = completed_downloads
        self.download_bundle = self._create_download_bundle(completed_downloads)

    def _clear_session_output_root(self):
        """
        Clear this browser session's output directory when using isolated web sessions.
        """

        if app_state.web_settings.get("web_use_output_dir", False):
            return

        output_root = Path(self.get_output_root())
        if not output_root.exists():
            return

        try:
            shutil.rmtree(output_root)
        except OSError:
            app_state.logger.debug(
                "Could not remove old session output: %s", output_root
            )

    def _delete_existing_bundle(self):
        """
        Delete the active session bundle if it exists.
        """

        if self.download_bundle is None:
            return

        bundle_path = self.download_bundle.get("path")
        if bundle_path and Path(bundle_path).is_file():
            try:
                Path(bundle_path).unlink()
            except OSError:
                app_state.logger.debug("Could not remove old bundle: %s", bundle_path)

        self.download_bundle = None

    def _create_download_bundle(
        self, completed_downloads: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Create a zip bundle for the finished downloads.

        ### Arguments
        - completed_downloads: current job downloads

        ### Returns
        - bundle metadata, or None if no files are available
        """

        self._delete_existing_bundle()

        if len(completed_downloads) == 0:
            return None

        bundle_root = get_spotdl_path() / "web/bundles" / self.client_id
        bundle_root.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        bundle_name = f"spotdl-downloads-{timestamp}.zip"
        bundle_path = bundle_root / bundle_name
        output_root = Path(self.get_output_root())
        bundled_files = 0
        seen_file_paths = set()
        used_archive_names: Dict[str, int] = {}

        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for download in completed_downloads:
                file_path_str = download.get("path")
                if not file_path_str:
                    continue

                file_path = Path(file_path_str)
                if not file_path.is_file():
                    continue

                normalized_path = str(file_path.resolve())
                if normalized_path in seen_file_paths:
                    continue

                seen_file_paths.add(normalized_path)

                try:
                    archive_name = str(file_path.relative_to(output_root))
                except ValueError:
                    archive_name = file_path.name

                archive_stem = Path(archive_name).stem
                archive_suffix = Path(archive_name).suffix
                archive_key = archive_name.lower()
                duplicate_index = used_archive_names.get(archive_key, 0)
                if duplicate_index > 0:
                    archive_name = f"{archive_stem} ({duplicate_index + 1}){archive_suffix}"

                used_archive_names[archive_key] = duplicate_index + 1

                archive.write(file_path, arcname=archive_name)
                bundled_files += 1

        if bundled_files == 0:
            try:
                bundle_path.unlink()
            except OSError:
                pass
            return None

        return {
            "name": bundle_name,
            "path": str(bundle_path.absolute()),
            "count": bundled_files,
            "created_at": self._timestamp(),
        }

    def _append_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Append an event to diagnostics history.

        ### Arguments
        - event: event payload

        ### Returns
        - the event
        """

        self.events.append(event)
        self.events = self.events[-200:]
        self.latest_update = event
        return event

    def _ensure_song_state(
        self,
        song: Song,
        queue_position: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Ensure a song has a state entry.

        ### Arguments
        - song: the song to track
        - queue_position: optional queue position

        ### Returns
        - mutable song state dictionary
        """

        key = self._song_key(song)
        song_state = self.song_states.get(key)
        if song_state is None:
            song_state = {
                "key": key,
                "display_name": song.display_name,
                "progress": 0,
                "message": "Queued",
                "status": "queued",
                "queue_position": queue_position or (len(self.song_states) + 1),
                "path": None,
                "updated_at": self._timestamp(),
                "song": song.json,
            }
            self.song_states[key] = song_state
        elif queue_position is not None:
            song_state["queue_position"] = queue_position

        return song_state

    def get_state_snapshot(self) -> Dict[str, Any]:
        """
        Get the current state snapshot for the client.

        ### Returns
        - serializable state snapshot
        """

        song_list = sorted(
            self.song_states.values(),
            key=lambda state: state.get("queue_position", 0),
        )

        completed = len(
            [song for song in song_list if song.get("status") == "done"]
        )
        failed = len([song for song in song_list if song.get("status") == "error"])
        skipped = len([song for song in song_list if song.get("status") == "skipped"])
        active = len(
            [
                song
                for song in song_list
                if song.get("status") not in {"done", "error", "skipped"}
            ]
        )
        progress = (
            round(
                sum(song.get("progress", 0) for song in song_list) / len(song_list), 1
            )
            if song_list
            else 0.0
        )

        return {
            "client_id": self.client_id,
            "job": self.current_job,
            "stats": {
                "total": len(song_list),
                "resolved": self.current_job.get("resolved_count", 0),
                "completed": completed,
                "failed": failed,
                "skipped": skipped,
                "active": active,
                "progress": progress,
            },
            "songs": song_list,
            "downloads": self.completed_downloads[-20:],
            "bundle": self.download_bundle,
            "events": self.events[-80:],
            "latest_update": self.latest_update,
            "server": {
                "version": __version__,
                "host": app_state.web_settings["host"],
                "port": app_state.web_settings["port"],
                "keep_alive": app_state.web_settings["keep_alive"],
                "web_use_output_dir": app_state.web_settings["web_use_output_dir"],
                "output_root": self.get_output_root(),
            },
        }

    async def push_state(self, event: Optional[Dict[str, Any]] = None):
        """
        Push the current state snapshot to the websocket client.

        ### Arguments
        - event: optional event that triggered the update
        """

        await self.send_update(
            {
                "type": "state",
                "state": self.get_state_snapshot(),
                "event": event,
            }
        )

    async def add_event(
        self,
        level: str,
        message: str,
        kind: str = "system",
        details: Optional[Any] = None,
        broadcast: bool = True,
    ) -> Dict[str, Any]:
        """
        Add an event to the diagnostics stream.

        ### Arguments
        - level: event severity level
        - message: event message
        - kind: event category
        - details: optional structured details
        - broadcast: whether to immediately push state

        ### Returns
        - event payload
        """

        event = self._append_event(
            {
                "timestamp": self._timestamp(),
                "level": level,
                "kind": kind,
                "message": message,
                "details": details,
            }
        )

        if broadcast:
            await self.push_state(event=event)

        return event

    async def handle_song_update(self, update: Dict[str, Any]):
        """
        Apply a song progress update and broadcast it.

        ### Arguments
        - update: serialized progress update
        """

        song_data = update["song"]
        song = Song.from_dict(song_data)
        song_state = self._ensure_song_state(song)

        previous_message = song_state.get("message")
        previous_progress = song_state.get("progress", 0)
        current_progress = int(update["progress"])
        current_message = update["message"]

        song_state.update(
            {
                "display_name": song.display_name,
                "progress": current_progress,
                "message": current_message,
                "status": self._normalize_status(current_message),
                "updated_at": self._timestamp(),
                "song": song_data,
            }
        )

        event = None
        if (
            previous_message != current_message
            or current_message in {"Done", "Error", "Skipped"}
        ):
            event = self._append_event(
                {
                    "timestamp": self._timestamp(),
                    "level": "error" if current_message == "Error" else "info",
                    "kind": "song",
                    "message": f"{song.display_name}: {current_message}",
                    "details": {
                        "song": song_data,
                        "progress": current_progress,
                        "overall_progress": update["overall_progress"],
                        "overall_completed": update["overall_completed"],
                        "overall_total": update["overall_total"],
                    },
                }
            )

        if current_message in {"Done", "Skipped"}:
            self._refresh_completed_downloads_from_output()

        if (
            previous_message != current_message
            or abs(current_progress - previous_progress) >= 2
            or current_progress in {0, 100}
        ):
            await self.push_state(event=event)

    def log_event(
        self,
        level: str,
        message: str,
        kind: str = "system",
        details: Optional[Any] = None,
        broadcast: bool = True,
    ):
        """
        Thread-safe wrapper for adding an event.

        ### Arguments
        - level: event severity level
        - message: event message
        - kind: event category
        - details: optional structured details
        - broadcast: whether to immediately push state
        """

        asyncio.run_coroutine_threadsafe(
            self.add_event(level, message, kind=kind, details=details, broadcast=broadcast),
            app_state.loop,
        )

    async def mark_query_resolved(
        self,
        query: str,
        songs: List[Song],
        output_root: str,
    ):
        """
        Mark a query as resolved and initialize queue state.

        ### Arguments
        - query: original query
        - songs: resolved songs
        - output_root: output directory root
        """

        self.current_job.update(
            {
                "status": "running",
                "query": query,
                "message": "Downloading",
                "resolved_count": len(songs),
                "error": None,
                "output_root": output_root,
            }
        )

        for index, song in enumerate(songs, start=1):
            song_state = self._ensure_song_state(song, queue_position=index)
            song_state.update(
                {
                    "message": "Queued",
                    "status": "queued",
                    "progress": 0,
                    "updated_at": self._timestamp(),
                }
            )

        await self.add_event(
            "info",
            f"Resolved {len(songs)} songs for query.",
            kind="job",
            details={"query": query, "output_root": output_root},
        )

    async def finish_query_download(
        self,
        results: List[Any],
        errors: List[str],
    ):
        """
        Finalize a query download and store result metadata.

        ### Arguments
        - results: downloader results
        - errors: downloader error strings
        """

        for song, path in results:
            song_state = self._ensure_song_state(song)
            absolute_path = str(path.absolute()) if path is not None else None
            if absolute_path:
                song_state["path"] = absolute_path
                song_state["status"] = "done"
                song_state["message"] = "Done"
                song_state["progress"] = 100
        self._refresh_completed_downloads_from_output()
        self.current_job.update(
            {
                "status": "complete-with-errors" if errors else "complete",
                "message": "Finished",
                "finished_at": self._timestamp(),
                "error": errors[0] if errors else None,
            }
        )

        for error in errors:
            self._append_event(
                {
                    "timestamp": self._timestamp(),
                    "level": "error",
                    "kind": "diagnostic",
                    "message": error,
                    "details": None,
                }
            )

        await self.add_event(
            "info",
            f"Download finished with {len(self.completed_downloads)} file(s) and {len(errors)} error(s).",
            kind="job",
            details={
                "downloads": self.completed_downloads[-10:],
                "errors": errors,
                "bundle": self.download_bundle,
            },
        )

    async def fail_query_download(self, query: str, exception: Exception):
        """
        Mark the current query as failed.

        ### Arguments
        - query: original query
        - exception: the exception raised
        """

        self.current_job.update(
            {
                "status": "error",
                "query": query,
                "message": "Failed",
                "finished_at": self._timestamp(),
                "error": str(exception),
            }
        )

        await self.add_event(
            "error",
            f"Download failed: {exception}",
            kind="job",
            details=traceback.format_exc(),
        )

    async def start_download_query(self, query: str) -> Dict[str, Any]:
        """
        Start downloading a full query in the background.

        ### Arguments
        - query: the query to resolve and download

        ### Returns
        - state snapshot
        """

        if self.download_task and not self.download_task.done():
            raise HTTPException(
                status_code=409,
                detail="A download is already running for this browser session.",
            )

        self._delete_existing_bundle()
        self._clear_session_output_root()
        self.events = []
        self.song_states = {}
        self.completed_downloads = []
        self.latest_update = None
        self.current_job = {
            "status": "starting",
            "query": query,
            "message": "Resolving query",
            "started_at": self._timestamp(),
            "finished_at": None,
            "resolved_count": 0,
            "error": None,
            "output_root": self.get_output_root(),
        }

        await self.add_event(
            "info",
            "Download queued.",
            kind="job",
            details={"query": query, "output_root": self.get_output_root()},
        )

        self.download_task = asyncio.create_task(self._run_download_query_task(query))
        return self.get_state_snapshot()

    async def _run_download_query_task(self, query: str):
        """
        Run a query download in a worker thread.

        ### Arguments
        - query: the query to process
        """

        try:
            await asyncio.to_thread(self._run_download_query_sync, query)
        except Exception as exception:
            await self.fail_query_download(query, exception)

    def _run_download_query_sync(self, query: str):
        """
        Synchronous worker that resolves and downloads a query.

        ### Arguments
        - query: the query to process
        """

        settings_dict = dict(self.downloader_settings)
        if not app_state.web_settings.get("web_use_output_dir", False):
            settings_dict["output"] = self.get_download_output()

        settings_dict["simple_tui"] = True
        downloader = Downloader(settings=settings_dict)
        downloader.progress_handler = ProgressHandler(
            simple_tui=True,
            update_callback=self.song_update,
        )
        downloader.progress_handler.web_ui = True

        self.log_event(
            "info",
            "Resolving query against supported providers.",
            kind="diagnostic",
            details={"query": query},
            broadcast=False,
        )

        queries = [line.strip() for line in query.splitlines() if line.strip()]
        if len(queries) == 0:
            queries = [query]

        songs = get_simple_songs(
            queries,
            use_ytm_data=downloader.settings["ytm_data"],
            playlist_numbering=downloader.settings["playlist_numbering"],
            album_type=downloader.settings["album_type"],
            playlist_retain_track_cover=downloader.settings[
                "playlist_retain_track_cover"
            ],
        )

        if len(songs) == 0:
            raise ValueError("No songs were found for this query.")

        asyncio.run_coroutine_threadsafe(
            self.mark_query_resolved(query, songs, self.get_output_root()),
            app_state.loop,
        ).result()

        results = downloader.download_multiple_songs(songs)

        asyncio.run_coroutine_threadsafe(
            self.finish_query_download(results, list(downloader.errors)),
            app_state.loop,
        ).result()

    async def connect(self):
        """
        Called when a new client connects to the websocket.
        """

        if self.websocket is None:
            raise RuntimeError("Cannot connect a dashboard client without a websocket.")

        await self.websocket.accept()

        # Add the connection to the list of connections
        app_state.clients[self.client_id] = self
        app_state.logger.info("Client %s connected", self.client_id)
        await self.add_event(
            "info",
            "Dashboard connected.",
            kind="system",
        )

    async def send_update(self, update: Dict[str, Any]):
        """
        Send an update to the client.

        ### Arguments
        - update: The update to send.
        """

        if self.websocket is None:
            return

        try:
            await self.websocket.send_json(update)
        except (RuntimeError, WebSocketDisconnect):
            self.websocket = None

    def song_update(self, progress_handler: SongTracker, message: str):
        """
        Called when a song updates.

        ### Arguments
        - progress_handler: The progress handler.
        - message: The message to send.
        """

        update_message = {
            "song": progress_handler.song.json,
            "progress": progress_handler.progress,
            "message": message,
            "overall_progress": round(
                (
                    progress_handler.parent.overall_progress
                    / progress_handler.parent.overall_total
                    * 100
                )
                if progress_handler.parent.overall_total
                else 0,
                1,
            ),
            "overall_completed": progress_handler.parent.overall_completed_tasks,
            "overall_total": progress_handler.parent.song_count,
        }

        asyncio.run_coroutine_threadsafe(
            self.handle_song_update(update_message), app_state.loop
        )

    @classmethod
    def get_instance(cls, client_id: str) -> Optional["Client"]:
        """
        Get the WebSocket instance for a client.

        ### Arguments
        - client_id: The client's ID.

        ### Returns
        - returns the WebSocket instance.
        """

        instance = app_state.clients.get(client_id)
        if instance:
            return instance

        app_state.logger.debug("Client %s not found in active dashboard sessions", client_id)

        return None


class ApplicationState:
    """
    Class that holds the application state.
    """

    api: FastAPI
    server: Server
    loop: asyncio.AbstractEventLoop
    web_settings: WebOptions
    downloader_settings: DownloaderOptions
    clients: Dict[str, Client] = {}
    logger: logging.Logger


router = APIRouter()
app_state: ApplicationState = ApplicationState()


def get_current_state() -> ApplicationState:
    """
    Get the current state of the application.

    ### Returns
    - returns the application state.
    """

    return app_state


def get_client(client_id: Union[str, None] = Query(default=None)) -> Client:
    """
    Get the client's state.

    ### Arguments
    - client_id: The client's ID.

    ### Returns
    - returns the client's state.
    """

    if client_id is None:
        raise HTTPException(status_code=400, detail="client_id is required")

    instance = Client.get_instance(client_id)
    if instance is None:
        instance = Client(None, client_id)
        instance._refresh_completed_downloads_from_output()
        app_state.clients[client_id] = instance

    return instance


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    Websocket endpoint.

    ### Arguments
    - websocket: The WebSocket instance.
    """

    client = Client.get_instance(client_id)
    if client is None:
        client = Client(websocket, client_id)
    else:
        client.attach_websocket(websocket)

    await client.connect()

    try:
        while True:
            await websocket.receive_json()
    except WebSocketDisconnect:
        client.detach_websocket(websocket)

        if (
            len([session for session in app_state.clients.values() if session.websocket])
            == 0
            and app_state.web_settings["keep_alive"] is False
        ):
            app_state.logger.debug(
                "No active connections, waiting 1s before shutting down"
            )

            await asyncio.sleep(1)

            # Wait 1 second before shutting down
            # This is to prevent the server from shutting down when a client
            # disconnects and reconnects quickly (e.g. when refreshing the page)
            if len(
                [session for session in app_state.clients.values() if session.websocket]
            ) == 0:
                # Perform a clean exit
                app_state.logger.info("Shutting down server, no active connections")
                app_state.server.force_exit = True
                app_state.server.should_exit = True
                await app_state.server.shutdown()


# Deprecated
@router.get("/api/song/url", response_model=None)
def song_from_url(url: str) -> Song:
    """
    Search for a song on spotify using url.

    ### Arguments
    - url: The url to search.

    ### Returns
    - returns the first result as a Song object.
    """

    return Song.from_url(url)


@router.get("/api/url", response_model=None)
def songs_from_url(url: str) -> List[Song]:
    """
    Search for a song, playlist, artist or album on spotify using url.

    ### Arguments
    - url: The url to search.

    ### Returns
    - returns a list with Song objects to be downloaded.
    """

    if "playlist" in url:
        playlist = Playlist.from_url(url)
        return list(map(Song.from_url, playlist.urls))
    if "album" in url:
        album = Album.from_url(url)
        return list(map(Song.from_url, album.urls))
    if "artist" in url:
        artist = Artist.from_url(url)
        return list(map(Song.from_url, artist.urls))

    return [Song.from_url(url)]


@router.get("/api/version", response_model=None)
def version() -> str:
    """
    Get the current version
    This method is created to ensure backward compatibility of the web app,
    as the web app is updated with the latest regardless of the backend version

    ### Returns
    -  returns the version of the app
    """

    return __version__


@router.on_event("shutdown")
async def shutdown_event():
    """
    Called when the server is shutting down.
    """

    if (
        not app_state.web_settings["keep_sessions"]
        and not app_state.web_settings["web_use_output_dir"]
    ):
        app_state.logger.info("Removing sessions directories")
        sessions_dir = Path(get_spotdl_path(), "web/sessions")
        if sessions_dir.exists():
            shutil.rmtree(sessions_dir)


@router.get("/api/songs/search", response_model=None)
def query_search(query: str) -> List[Song]:
    """
    Parse search term and return list of Song objects.

    ### Arguments
    - query: The query to parse.

    ### Returns
    - returns a list of Song objects.
    """

    return get_search_results(query)


@router.get("/api/session/state", response_model=None)
def session_state(
    client: Client = Depends(get_client),
) -> Dict[str, Any]:
    """
    Get the current dashboard state for a client.

    ### Arguments
    - client: the client's state

    ### Returns
    - state snapshot
    """

    return client.get_state_snapshot()


@router.post("/api/download/query", response_model=None)
async def download_query(
    query: str = Body(..., embed=True),
    client: Client = Depends(get_client),
) -> Dict[str, Any]:
    """
    Resolve a query and download all matching songs in the background.

    ### Arguments
    - query: the query string to download
    - client: the client's state

    ### Returns
    - current state snapshot
    """

    stripped_query = query.strip()
    if stripped_query == "":
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    return await client.start_download_query(stripped_query)


@router.post("/api/download/url")
async def download_url(
    url: str,
    client: Client = Depends(get_client),
    state: ApplicationState = Depends(get_current_state),
) -> Optional[str]:
    """
    Download songs using Song url.

    ### Arguments
    - url: The url to download.

    ### Returns
    - returns the file path if the song was downloaded.
    """

    if state.web_settings.get("web_use_output_dir", False):
        client.downloader.settings["output"] = client.downloader_settings["output"]
    else:
        client.downloader.settings["output"] = client.get_download_output()

    client.downloader.progress_handler = ProgressHandler(
        simple_tui=True,
        update_callback=client.song_update,
    )

    try:
        # Fetch song metadata
        song = Song.from_url(url)

        # Download Song
        _, path = await client.downloader.pool_download(song)

        if path is None:
            state.logger.error(f"Failure downloading {song.name}")

            raise HTTPException(
                status_code=500, detail=f"Error downloading: {song.name}"
            )

        return str(path.absolute())

    except Exception as exception:
        state.logger.error(f"Error downloading! {exception}")

        raise HTTPException(
            status_code=500, detail=f"Error downloading: {exception}"
        ) from exception


@router.get("/api/download/file")
async def download_file(
    file: str,
    client: Client = Depends(get_client),
    state: ApplicationState = Depends(get_current_state),
):
    """
    Download file using path.

    ### Arguments
    - file: The file path.
    - client: The client's state.

    ### Returns
    - returns the file response, filename specified to return as attachment.
    """

    file_path = Path(file).absolute()
    expected_root = Path(get_spotdl_path() / "web/sessions").absolute()
    if state.web_settings.get("web_use_output_dir", False):
        expected_root = Path(
            client.downloader_settings["output"].split("{", 1)[0]
        ).absolute()

    if file_path.suffix.lower() != f".{client.downloader_settings['format']}".lower():
        raise HTTPException(status_code=400, detail="Invalid download path.")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="The requested file is missing.")

    if not _is_path_within_root(file_path, expected_root):
        raise HTTPException(status_code=400, detail="Invalid download path.")

    return FileResponse(
        file_path,
        filename=os.path.basename(file_path),
    )


@router.get("/api/download/bundle")
def download_bundle(
    client: Client = Depends(get_client),
):
    """
    Download the current session bundle as a zip archive.

    ### Arguments
    - client: The client's state.

    ### Returns
    - bundle file response
    """

    if client.download_bundle is None:
        client._refresh_completed_downloads_from_output()

    bundle = client.download_bundle
    if bundle is None:
        raise HTTPException(status_code=404, detail="No download bundle is ready yet.")

    bundle_path = bundle.get("path")
    if not bundle_path or not Path(bundle_path).is_file():
        raise HTTPException(status_code=404, detail="The download bundle is missing.")

    return FileResponse(
        bundle_path,
        filename=bundle.get("name", "spotdl-downloads.zip"),
        media_type="application/zip",
    )


@router.get("/api/settings")
def get_settings(
    client: Client = Depends(get_client),
) -> DownloaderOptions:
    """
    Get client settings.

    ### Arguments
    - client: The client's state.

    ### Returns
    - returns the settings.
    """

    return client.downloader_settings


@router.post("/api/settings/update")
def update_settings(
    settings: DownloaderOptionalOptions,
    client: Client = Depends(get_client),
    state: ApplicationState = Depends(get_current_state),
) -> DownloaderOptions:
    """
    Update client settings, and re-initialize downloader.

    ### Arguments
    - settings: The settings to change.
    - client: The client's state.
    - state: The application state.

    ### Returns
    - returns True if the settings were changed.
    """

    def is_blank(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip() == ""

        if isinstance(value, list):
            return len(value) == 0 or all(
                isinstance(item, str) and item.strip() == "" for item in value
            )

        return False

    # Create shallow copy of settings
    settings_cpy = client.downloader_settings.copy()

    # Update settings with new settings that are not None
    settings_cpy.update({k: v for k, v in settings.items() if v is not None})  # type: ignore

    for key, default_value in DOWNLOADER_OPTIONS.items():
        if is_blank(settings_cpy.get(key)):
            settings_cpy[key] = default_value

    new_settings = _normalize_web_downloader_settings(settings_cpy)
    state.logger.info("Applying settings: %s", dict(new_settings))

    # Re-initialize downloader
    client.downloader_settings = new_settings
    client.downloader = Downloader(
        new_settings,
        loop=state.loop,
    )

    return new_settings


@router.get("/api/check_update")
def check_update() -> bool:
    """
    Check for update.

    ### Returns
    - returns True if there is an update.
    """

    try:
        _, ahead, _ = get_status(__version__, "master")
        if ahead > 0:
            return True
    except RuntimeError:
        latest_version = get_latest_version()
        latest_tuple = tuple(latest_version.replace("v", "").split("."))
        current_tuple = tuple(__version__.split("."))
        if latest_tuple > current_tuple:
            return True
    except RateLimitError:
        return False

    return False


@router.get("/api/options_model")
def get_options() -> Dict[str, Any]:
    """
    Get options model (possible settings).

    ### Returns
    - returns the options.
    """

    parser = create_parser()

    # Forbidden actions
    forbidden_actions = [
        "help",
        "operation",
        "version",
        "config",
        "user_auth",
        "client_id",
        "client_secret",
        "auth_token",
        "cache_path",
        "no_cache",
        "cookie_file",
        "ffmpeg",
        "archive",
        "host",
        "port",
        "keep_alive",
        "enable_tls",
        "key_file",
        "cert_file",
        "ca_file",
        "allowed_origins",
        "web_use_output_dir",
        "keep_sessions",
        "log_level",
        "simple_tui",
        "headless",
        "download_ffmpeg",
        "generate_config",
        "check_for_updates",
        "profile",
        "version",
    ]

    options = {}
    for action in parser._actions:  # pylint: disable=protected-access
        if action.dest in forbidden_actions:
            continue

        default = app_state.downloader_settings.get(action.dest, None)
        choices = list(action.choices) if action.choices else None

        type_name = ""
        if action.type is not None:
            if hasattr(action.type, "__objclass__"):
                type_name: str = action.type.__objclass__.__name__  # type: ignore
            else:
                type_name: str = action.type.__name__  # type: ignore

        if isinstance(
            action, argparse._StoreConstAction  # pylint: disable=protected-access
        ):
            type_name = "bool"

        if choices is not None and action.nargs == "*":
            type_name = "list"

        options[action.dest] = {
            "type": type_name,
            "choices": choices,
            "default": default,
            "help": action.help,
        }

    return options


def fix_mime_types():
    """Fix incorrect entries in the `mimetypes` registry.
    On Windows, the Python standard library's `mimetypes` reads in
    mappings from file extension to MIME type from the Windows
    registry. Other applications can and do write incorrect values
    to this registry, which causes `mimetypes.guess_type` to return
    incorrect values, which causes spotDL to fail to render on
    the frontend.
    This method hard-codes the correct mappings for certain MIME
    types that are known to be either used by TensorBoard or
    problematic in general.
    """

    # Known to be problematic when Visual Studio is installed:
    # <https://github.com/tensorflow/tensorboard/issues/3120>
    # https://github.com/spotDL/spotify-downloader/issues/1540
    mimetypes.add_type("application/javascript", ".js")

    # Not known to be problematic, but used by spotDL:
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("image/svg+xml", ".svg")
    mimetypes.add_type("text/html", ".html")
