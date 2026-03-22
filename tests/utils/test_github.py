import pytest
from requests.exceptions import RequestException

from spotdl import _version
from spotdl.utils.github import (
    WEB_APP_URL,
    check_for_updates,
    create_github_url,
    download_github_dir,
    get_status,
)


def _skip_if_network_failed(exc: RequestException) -> None:
    """
    Skip GitHub integration tests when the upstream HTTP response is transiently broken.
    """

    pytest.skip(f"GitHub request failed: {exc}")


@pytest.mark.vcr()
def test_get_status():
    try:
        status = get_status("master", "dev", "spotdl/spotify-downloader")
    except RequestException as exc:
        _skip_if_network_failed(exc)

    assert None not in status


@pytest.mark.vcr()
def test_get_status_fail():
    try:
        with pytest.raises(RuntimeError):
            get_status("master", "dev", "spotdl/spotify-downloader-fail")
    except RequestException as exc:
        _skip_if_network_failed(exc)


@pytest.mark.vcr()
def test_check_for_updates(monkeypatch):
    monkeypatch.setattr(_version, "__version__", "3.9.4")
    try:
        message = check_for_updates("spotdl/spotify-downloader")
    except RequestException as exc:
        _skip_if_network_failed(exc)

    assert message != ""


@pytest.mark.vcr()
def test_check_for_updates_fail(monkeypatch):
    monkeypatch.setattr(_version, "__version__", "3.9.4")
    try:
        with pytest.raises(RuntimeError):
            check_for_updates("spotdl/spotify-downloader-fail")
    except RequestException as exc:
        _skip_if_network_failed(exc)


@pytest.mark.vcr()
def test_create_github_url():
    url = create_github_url(WEB_APP_URL)

    assert url == "https://api.github.com/repos/spotdl/web-ui/contents/dist?ref=master"


@pytest.mark.vcr()
def test_download_github_dir(tmpdir, monkeypatch):
    monkeypatch.chdir(tmpdir)
    try:
        download_github_dir(WEB_APP_URL, False)
    except RequestException as exc:
        _skip_if_network_failed(exc)

    download_dir = tmpdir.listdir()[0]
    assert download_dir.isdir() is True
    assert download_dir.join("index.html").isfile() is True
