"""this module contains network related utility functions"""

import functools
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from beartype import beartype
from packaging.version import Version
import requests

from deeporigin import __version__
from deeporigin.exceptions import DeepOriginException


@functools.cache
def check_for_updates():
    """check if a new version is available. If so, print an message"""

    try:
        latest_pypi_version = Version(_get_pypi_version())
        if Version(__version__) < latest_pypi_version and __version__ != "0.0.0.dev0":
            print(
                f"🎈 A new version of Deep Origin is available. You have version {__version__}. The latest version is {latest_pypi_version}. Please update to the newest version."
            )

    except Exception:
        pass


@beartype
def download_sync(
    url: str | dict,
    save_path: str | Path,
) -> None:
    """Concrete method to download a resource using GET and save to disk

    Args:
        url (str): url to download
        save_path (str): path to save file
    """

    with requests.get(url, stream=True) as response:
        if response.status_code != 200:
            raise DeepOriginException(
                message=f"File could not be downloaded from {url}. The message is {response.text}",
                title=f"Deep Origin Error: [{response.status_code}]",
            ) from None

        with open(save_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:  # Filter out keep-alive new chunks
                    file.write(chunk)


def _get_pypi_version() -> str | None:
    """determines the latest version on PyPI"""

    response = requests.get("https://pypi.org/pypi/deeporigin/json")

    if response.status_code == 200:
        data = response.json()
        return data["info"]["version"]
    else:
        return None


@beartype
def _parse_params_from_url(url: str) -> dict:
    """Utility function to extract params from a URL query

    Warning: Internal function
        Do not use this function

    Args:
        url: URL

    Returns:
        A dictionary of params
    """

    query = urlparse(url).query
    params = parse_qs(query)
    params = {key: value[0] for key, value in params.items()}
    return params
