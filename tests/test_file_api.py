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
