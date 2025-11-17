"""this module tests the file API"""

import os

import pytest

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


def test_delete_file(client):  # noqa: F811
    """test the delete_file API."""

    # First upload a file to delete
    test_file_path = "test_delete_file.txt"
    local_test_file = "/tmp/test_upload_delete.txt"
    with open(local_test_file, "w") as f:
        f.write("test content")

    # Upload the file
    client.files.upload_file(
        local_path=local_test_file,
        remote_path=test_file_path,
    )

    # Delete the file (should succeed without raising)
    client.files.delete_file(file_path=test_file_path)

    # Try to delete a non-existent file (should raise RuntimeError)
    with pytest.raises(RuntimeError, match="Failed to delete file"):
        client.files.delete_file(file_path="nonexistent_file.txt")

    # Clean up local test file
    if os.path.exists(local_test_file):
        os.remove(local_test_file)


def test_delete_file_with_special_chars(client):  # noqa: F811
    """test the delete_file API with special characters in path."""

    # Test with a path that contains special characters (like the example)
    test_file_path = "function-runs/system-prep/test123/bsm_system.xml"

    # First upload a file to delete
    local_test_file = "/tmp/test_upload_delete_special.txt"
    with open(local_test_file, "w") as f:
        f.write("test content")

    # Upload the file
    client.files.upload_file(
        local_path=local_test_file,
        remote_path=test_file_path,
    )

    # Delete the file (should handle URL encoding correctly and succeed)
    client.files.delete_file(file_path=test_file_path)

    # Clean up local test file
    if os.path.exists(local_test_file):
        os.remove(local_test_file)


def test_delete_files(client):  # noqa: F811
    """test the delete_files API."""

    # Upload multiple files to delete
    test_file_paths = [
        "test_delete_files_1.txt",
        "test_delete_files_2.txt",
        "test_delete_files_3.txt",
    ]
    local_test_files = []

    for i, test_file_path in enumerate(test_file_paths):
        local_test_file = f"/tmp/test_upload_delete_{i}.txt"
        local_test_files.append(local_test_file)
        with open(local_test_file, "w") as f:
            f.write(f"test content {i}")

        # Upload the file
        client.files.upload_file(
            local_path=local_test_file,
            remote_path=test_file_path,
        )

    # Delete all files (should succeed without raising)
    client.files.delete_files(test_file_paths)

    # Clean up local test files
    for local_test_file in local_test_files:
        if os.path.exists(local_test_file):
            os.remove(local_test_file)


def test_delete_files_with_errors(client):  # noqa: F811
    """test the delete_files API with errors."""

    # Upload one file
    test_file_path = "test_delete_files_error.txt"
    local_test_file = "/tmp/test_upload_delete_error.txt"
    with open(local_test_file, "w") as f:
        f.write("test content")

    client.files.upload_file(
        local_path=local_test_file,
        remote_path=test_file_path,
    )

    # Try to delete a mix of existing and non-existent files
    file_paths = [test_file_path, "nonexistent_file_1.txt", "nonexistent_file_2.txt"]

    # Should raise RuntimeError by default
    with pytest.raises(RuntimeError, match="Some deletions failed in delete_files"):
        client.files.delete_files(file_paths)

    # With skip_errors=True, should not raise
    client.files.delete_files(file_paths, skip_errors=True)

    # Clean up local test file
    if os.path.exists(local_test_file):
        os.remove(local_test_file)


def test_delete_files_empty_list(client):  # noqa: F811
    """test the delete_files API with empty list."""

    # Should succeed without doing anything
    client.files.delete_files([])
