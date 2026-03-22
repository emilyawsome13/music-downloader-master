import os
import platform
from pathlib import Path
from types import SimpleNamespace

import pytest

from spotdl.utils.config import *


def expected_spotdl_path(base_dir: Path) -> Path:
    """
    Return the default config path for the current platform.
    """

    if platform.system() == "Linux":
        return base_dir / ".config" / "spotdl"

    return base_dir / ".spotdl"


@pytest.fixture()
def setup(tmpdir, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda *_: tmpdir)
    data = SimpleNamespace()
    data.directory = tmpdir
    yield data


def test_get_spotdl_path(setup):
    """
    Tests that the spotdl path is created if it does not exist.
    """

    spotdl_path = expected_spotdl_path(Path(setup.directory))

    assert get_spotdl_path() == spotdl_path
    assert spotdl_path.exists()


def test_get_spotdl_path_env_override(tmpdir, monkeypatch):
    """
    Tests that SPOTDL_DATA_DIR overrides the default config location.
    """

    override_dir = Path(tmpdir, "render-data")
    monkeypatch.setenv("SPOTDL_DATA_DIR", str(override_dir))

    assert get_spotdl_path() == override_dir
    assert override_dir.exists()


def test_get_config_path(setup):
    """
    Tests if the path to config file is correct.
    """

    assert (
        get_config_file() == expected_spotdl_path(Path(setup.directory)) / "config.json"
    )


def test_get_cache_path(setup):
    """
    Tests if the path to the cache file is correct.
    """

    assert get_cache_path() == expected_spotdl_path(Path(setup.directory)) / ".spotipy"


def test_get_temp_path(setup):
    """
    Tests if the path to the temp folder is correct.
    """

    assert get_temp_path() == expected_spotdl_path(Path(setup.directory)) / "temp"


def test_get_config_not_created(setup):
    """
    Tests if exception is raised if config file does not exist.
    """

    with pytest.raises(ConfigError):
        get_config()
