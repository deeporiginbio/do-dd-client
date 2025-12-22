"""this module tests the file API"""

import os
import tempfile

import pytest

from deeporigin.platform.client import DeepOriginClient


def test_get_all_files_lv1():
    """check that there are some files in entities/"""
    client = DeepOriginClient()
    files = client.files.list_files_in_dir(
        remote_path="entities/",
        recursive=True,
    )
    assert len(files) > 0, "should be some files in entities/"

    print(f"Found {len(files)} files")


def test_download_file_lv1():
    """test the file download API"""
    client = DeepOriginClient()
    files = client.files.list_files_in_dir(
        remote_path="entities/",
        recursive=True,
    )
    assert len(files) > 0, "should be some files in entities/"

    local_path = client.files.download_file(
        remote_path=files[0],
    )

    assert os.path.exists(local_path), "should have downloaded the file"


def test_download_files_with_list_lv1():
    """test the download_files API with a list input."""
    client = DeepOriginClient()
    files = client.files.list_files_in_dir(
        remote_path="entities/",
        recursive=True,
    )
    assert len(files) > 0, "should be some files in entities/"

    # Test with a list (first file only)
    local_paths = client.files.download_files(
        files=[files[0]],
    )

    assert len(local_paths) == 1, "should have downloaded one file"
    assert os.path.exists(local_paths[0]), "should have downloaded the file"


def test_download_files_with_dict_lv1():
    """test the download_files API with a dict input."""
    client = DeepOriginClient()
    files = client.files.list_files_in_dir(
        remote_path="entities/",
        recursive=True,
    )
    assert len(files) > 0, "should be some files in entities/"

    # Test with a dict
    local_paths = client.files.download_files(
        files={files[0]: None},
    )

    assert len(local_paths) == 1, "should have downloaded one file"
    assert os.path.exists(local_paths[0]), "should have downloaded the file"


def test_delete_file_lv1():
    """test the delete_file API."""
    client = DeepOriginClient()
    # First upload a file to delete
    test_file_path = "test_delete_file.txt"
    local_test_file = os.path.join(tempfile.gettempdir(), "test_upload_delete.txt")
    with open(local_test_file, "w") as f:
        f.write("test content")

    # Upload the file
    client.files.upload_file(
        local_test_file,
        remote_path=test_file_path,
    )

    # Delete the file (should succeed without raising)
    client.files.delete_file(remote_path=test_file_path, timeout=60.0)

    # Try to delete a non-existent file (should raise RuntimeError)
    with pytest.raises(RuntimeError, match="Failed to delete file"):
        client.files.delete_file(remote_path="nonexistent_file.txt", timeout=10.0)

    # Clean up local test file
    if os.path.exists(local_test_file):
        os.remove(local_test_file)


def test_delete_files_empty_list_lv1():
    """test the delete_files API with empty list."""
    client = DeepOriginClient()
    # Should succeed without doing anything
    client.files.delete_files(remote_paths=[])
