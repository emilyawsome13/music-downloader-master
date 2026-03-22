"""
Helpers for Render build-time setup.
"""

from pathlib import Path

from spotdl.utils.ffmpeg import download_ffmpeg, get_ffmpeg_path

__all__ = ["ensure_ffmpeg", "main"]


def ensure_ffmpeg() -> Path:
    """
    Ensure FFmpeg is available during Render builds without interactive prompts.
    """

    existing_path = get_ffmpeg_path()
    if existing_path is not None:
        print(f"Using existing FFmpeg at {existing_path}")
        return existing_path

    download_path = download_ffmpeg()
    print(f"Downloaded FFmpeg to {download_path}")
    return download_path


def main() -> None:
    """
    Render build entrypoint.
    """

    ensure_ffmpeg()


if __name__ == "__main__":
    main()
