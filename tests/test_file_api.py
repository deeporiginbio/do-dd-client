"""this module tests the file API"""

import os

from tests.utils import client  # noqa: F401


def test_get_all_files(client):  # noqa: F811
    """check that there are some files in entities/"""

    files = client.files.list_files_in_dir(
        file_path="entities/",
        recursive=True,
    )
    assert len(files) > 0, "should be some files in entities/"

    print(f"Found {len(files)} files")


def test_download_file(client):  # noqa: F811
    """test the file download API"""

    files = client.files.list_files_in_dir(
        file_path="entities/",
        recursive=True,
    )
    assert len(files) > 0, "should be some files in entities/"

    local_path = client.files.download_file(
        remote_path=files[0],
    )

    assert os.path.exists(local_path), "should have downloaded the file"


def test_download_files_with_list(client):  # noqa: F811
    """test the download_files API with a list input."""

    files = client.files.list_files_in_dir(
        file_path="entities/",
        recursive=True,
    )
    assert len(files) > 0, "should be some files in entities/"

    # Test with a list (first file only)
    local_paths = client.files.download_files(
        files=[files[0]],
    )

    assert len(local_paths) == 1, "should have downloaded one file"
    assert os.path.exists(local_paths[0]), "should have downloaded the file"


def test_download_files_with_dict(client):  # noqa: F811
    """test the download_files API with a dict input."""

    files = client.files.list_files_in_dir(
        file_path="entities/",
        recursive=True,
    )
    assert len(files) > 0, "should be some files in entities/"

    # Test with a dict
    local_paths = client.files.download_files(
        files={files[0]: None},
    )

    assert len(local_paths) == 1, "should have downloaded one file"
    assert os.path.exists(local_paths[0]), "should have downloaded the file"
