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


def test_list_files_returns_metadata_lv1():
    """check that list_files returns dicts with metadata."""
    client = DeepOriginClient()
    files = client.files.list_files(
        remote_path="entities/",
        recursive=True,
    )
    assert len(files) > 0, "should be some files in entities/"

    first = files[0]
    assert isinstance(first, dict), "each entry should be a dict"
    assert "Key" in first, "should contain Key"


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


def test_download_file_with_download_to_dir_lv1():
    """test the file download API with download_to_dir parameter"""
    client = DeepOriginClient()
    files = client.files.list_files_in_dir(
        remote_path="entities/",
        recursive=True,
    )
    assert len(files) > 0, "should be some files in entities/"

    # Create a temporary directory for downloads
    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = client.files.download_file(
            remote_path=files[0],
            download_to_dir=tmpdir,
        )

        # Verify the file was downloaded to the specified directory
        assert os.path.exists(local_path), "should have downloaded the file"
        assert local_path.startswith(tmpdir), "file should be in download_to_dir"

        # Verify the filename matches the basename of remote_path
        remote_basename = os.path.basename(files[0])
        assert os.path.basename(local_path) == remote_basename, (
            "filename should match remote basename"
        )


def test_download_file_local_path_takes_precedence_lv1():
    """test that local_path takes precedence over download_to_dir"""
    client = DeepOriginClient()
    files = client.files.list_files_in_dir(
        remote_path="entities/",
        recursive=True,
    )
    assert len(files) > 0, "should be some files in entities/"

    # Create temporary directories
    with (
        tempfile.TemporaryDirectory() as tmpdir1,
        tempfile.TemporaryDirectory() as tmpdir2,
    ):
        # Specify both local_path and download_to_dir
        custom_local_path = os.path.join(tmpdir1, "custom_filename.txt")
        local_path = client.files.download_file(
            remote_path=files[0],
            local_path=custom_local_path,
            download_to_dir=tmpdir2,  # This should be ignored
        )

        # Verify the file was downloaded to local_path, not download_to_dir
        assert os.path.exists(local_path), "should have downloaded the file"
        assert local_path == custom_local_path, "file should be at custom local_path"
        assert local_path.startswith(tmpdir1), "file should be in tmpdir1"
        assert not local_path.startswith(tmpdir2), "file should not be in tmpdir2"


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


def test_get_signed_url_upload_lv1():
    """test that we can get a signed upload URL for a file path."""
    client = DeepOriginClient()
    url = client.files.get_signed_url(
        "/testing-signed-url/test-upload.txt",
        upload=True,
    )
    assert isinstance(url, str), "should return a string URL"
    assert url.startswith("http"), "should be a valid URL"


def test_get_signed_url_download_lv1():
    """test that we can get a signed download URL for an existing file."""
    client = DeepOriginClient()
    files = client.files.list_files_in_dir(
        remote_path="entities/",
        recursive=True,
    )
    assert len(files) > 0, "should be some files in entities/"

    url = client.files.get_signed_url(files[0])
    assert isinstance(url, str), "should return a string URL"
    assert url.startswith("http"), "should be a valid URL"


def test_upload_files_via_signed_url_list_lv1():
    """test uploading a list of files using signed URLs."""
    client = DeepOriginClient()

    with tempfile.TemporaryDirectory() as tmpdir:
        file_a = os.path.join(tmpdir, "a.txt")
        file_b = os.path.join(tmpdir, "b.txt")
        with open(file_a, "w") as f:
            f.write("content a")
        with open(file_b, "w") as f:
            f.write("content b")

        remote_dir = "/testing-signed-url-upload/"
        results = client.files.upload_files_via_signed_url(
            local_path=[file_a, file_b],
            remote_dir=remote_dir,
        )

        assert len(results) == 2, "should have uploaded 2 files"
        assert all(r.startswith(remote_dir) for r in results), (
            "remote paths should be under remote_dir"
        )

    client.files.delete_files(
        remote_paths=[f"{remote_dir}a.txt", f"{remote_dir}b.txt"],
        skip_errors=True,
        timeout=60.0,
    )


def test_upload_files_via_signed_url_directory_lv1():
    """test uploading a local directory using signed URLs, preserving structure."""
    client = DeepOriginClient()

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a nested directory structure
        subdir = os.path.join(tmpdir, "sub")
        os.makedirs(subdir)
        file_a = os.path.join(tmpdir, "root.txt")
        file_b = os.path.join(subdir, "nested.txt")
        with open(file_a, "w") as f:
            f.write("root content")
        with open(file_b, "w") as f:
            f.write("nested content")

        remote_dir = "/testing-signed-url-upload-dir/"
        results = client.files.upload_files_via_signed_url(
            local_path=tmpdir,
            remote_dir=remote_dir,
        )

        assert len(results) == 2, "should have uploaded 2 files"
        remote_names = sorted(r.removeprefix(remote_dir) for r in results)
        assert remote_names == ["root.txt", "sub/nested.txt"], (
            "should preserve subdirectory structure"
        )

    client.files.delete_files(
        remote_paths=[
            f"{remote_dir}root.txt",
            f"{remote_dir}sub/nested.txt",
        ],
        skip_errors=True,
        timeout=60.0,
    )


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


def test_get_file_lv1():
    """test direct file download via GET endpoint."""
    client = DeepOriginClient()
    files = client.files.list_files_in_dir(
        remote_path="entities/",
        recursive=True,
    )
    assert len(files) > 0, "should be some files in entities/"

    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = client.files.get_file(
            files[0],
            download_to_dir=tmpdir,
        )

        assert os.path.exists(local_path), "should have downloaded the file"
        assert os.path.getsize(local_path) > 0, "downloaded file should not be empty"


def test_head_file_lv1():
    """test HEAD request returns metadata headers."""
    client = DeepOriginClient()
    files = client.files.list_files_in_dir(
        remote_path="entities/",
        recursive=True,
    )
    assert len(files) > 0, "should be some files in entities/"

    headers = client.files.head_file(files[0])

    assert isinstance(headers, dict), "should return a dict of headers"
    assert "content-type" in headers, "should contain content-type header"


def test_upload_file_from_url_lv1():
    """test uploading a file by having the server fetch a URL."""
    client = DeepOriginClient()

    remote_path = "testing-upload-from-url/robots.txt"
    result = client.files.upload_file_from_url(
        remote_path,
        source_url="https://www.google.com/robots.txt",
    )

    assert isinstance(result, dict), "should return a dict response"

    # Clean up
    client.files.delete_file(remote_path=remote_path, timeout=60.0)


def test_download_as_zip_lv1():
    """test downloading a remote directory as a ZIP archive."""
    client = DeepOriginClient()

    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = client.files.download_as_zip(
            "entities/",
            download_to_dir=tmpdir,
        )

        assert os.path.exists(local_path), "ZIP file should exist"
        assert local_path.endswith(".zip"), "should have .zip extension"
        assert os.path.getsize(local_path) > 0, "ZIP should not be empty"


def test_upload_directory_bulk_lv1():
    """Upload ~100MB directory (100 x 1MB files), verify listing, then clean up."""
    client = DeepOriginClient()

    if client.env == "local":
        pytest.skip("Requires a real file service (use --env dev/staging/prod)")

    remote_dir = "/testing-bulk-upload/"
    num_files = 10
    file_size = 1024 * 1024  # 1 MB

    with tempfile.TemporaryDirectory() as tmpdir:
        # Generate 100 x 1MB files with random bytes
        expected_names = []
        for i in range(num_files):
            name = f"file_{i:03d}.bin"
            expected_names.append(name)
            path = os.path.join(tmpdir, name)
            with open(path, "wb") as f:
                f.write(os.urandom(file_size))

        # Upload the entire directory (lower concurrency to avoid write timeouts)
        results = client.files.upload_files_via_signed_url(
            local_path=tmpdir,
            remote_dir=remote_dir,
            max_workers=5,
            max_retries=5,
            retry_backoff_factor=2.0,
        )

        assert len(results) == num_files, (
            f"expected {num_files} uploads, got {len(results)}"
        )

    # Verify uploaded files are visible via list_files_in_dir
    remote_files = client.files.list_files_in_dir(
        remote_path=remote_dir,
        recursive=True,
    )

    uploaded_basenames = sorted(os.path.basename(f) for f in remote_files)
    assert uploaded_basenames == sorted(expected_names), (
        "listed files should match uploaded files"
    )

    # Clean up remote files
    client.files.delete_files(remote_paths=remote_files, skip_errors=True)


def test_upload_files_multipart_lv1():
    """Test parallel multipart upload via upload_files."""
    client = DeepOriginClient()

    if client.env == "local":
        pytest.skip("Requires a real file service (use --env dev/staging/prod)")

    remote_dir = "testing-multipart-upload"
    num_files = 10

    with tempfile.TemporaryDirectory() as tmpdir:
        file_map: dict[str, str] = {}
        for i in range(num_files):
            name = f"mp_{i:03d}.bin"
            local = os.path.join(tmpdir, name)
            with open(local, "wb") as f:
                f.write(os.urandom(64 * 1024))
            file_map[local] = f"{remote_dir}/{name}"

        results = client.files.upload_files(files=file_map)

        assert len(results) == num_files, (
            f"expected {num_files} results, got {len(results)}"
        )
        assert all(isinstance(r, dict) for r in results), "each result should be a dict"

    # Verify via listing
    remote_files = client.files.list_files_in_dir(
        remote_path=f"{remote_dir}/",
        recursive=True,
    )
    listed_basenames = sorted(os.path.basename(f) for f in remote_files)
    expected_basenames = sorted(f"mp_{i:03d}.bin" for i in range(num_files))
    assert listed_basenames == expected_basenames, (
        "listed files should match uploaded files"
    )

    # Clean up
    client.files.delete_files(remote_paths=remote_files, timeout=120.0)


def test_round_trip_content_integrity_lv1():
    """Upload files via signed URL, download them, and verify bytes match."""
    client = DeepOriginClient()

    if client.env == "local":
        pytest.skip("Requires a real file service (use --env dev/staging/prod)")

    remote_dir = "/testing-round-trip/"
    num_files = 5
    file_size = 256 * 1024  # 256 KB each

    with tempfile.TemporaryDirectory() as upload_dir:
        originals: dict[str, bytes] = {}
        for i in range(num_files):
            name = f"rt_{i:03d}.bin"
            data = os.urandom(file_size)
            originals[name] = data
            with open(os.path.join(upload_dir, name), "wb") as f:
                f.write(data)

        results = client.files.upload_files_via_signed_url(
            local_path=upload_dir,
            remote_dir=remote_dir,
        )
        assert len(results) == num_files

    # Download each file and compare bytes
    with tempfile.TemporaryDirectory() as download_dir:
        for name, expected_bytes in originals.items():
            local_path = client.files.download_file(
                remote_path=f"{remote_dir}{name}",
                download_to_dir=download_dir,
            )
            with open(local_path, "rb") as f:
                actual_bytes = f.read()

            assert actual_bytes == expected_bytes, (
                f"content mismatch for {name}: "
                f"expected {len(expected_bytes)} bytes, got {len(actual_bytes)}"
            )

    # Clean up
    remote_files = [f"{remote_dir}{name}" for name in originals]
    client.files.delete_files(remote_paths=remote_files, timeout=120.0)


def test_list_files_metadata_size_lv1():
    """Upload known-size files, then verify Size in list_files metadata."""
    client = DeepOriginClient()

    if client.env == "local":
        pytest.skip("Requires a real file service (use --env dev/staging/prod)")

    remote_dir = "/testing-metadata-size/"
    sizes = {
        "small.bin": 1024,  # 1 KB
        "medium.bin": 100 * 1024,  # 100 KB
        "large.bin": 1024 * 1024,  # 1 MB
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        for name, size in sizes.items():
            with open(os.path.join(tmpdir, name), "wb") as f:
                f.write(os.urandom(size))

        client.files.upload_files_via_signed_url(
            local_path=tmpdir,
            remote_dir=remote_dir,
        )

    # Fetch full metadata
    file_objects = client.files.list_files(
        remote_path=remote_dir,
        recursive=True,
    )

    size_by_name = {
        os.path.basename(obj["Key"]): obj["Size"]
        for obj in file_objects
        if "Size" in obj
    }

    for name, expected_size in sizes.items():
        assert name in size_by_name, f"{name} should appear in listing"
        assert size_by_name[name] == expected_size, (
            f"Size mismatch for {name}: expected {expected_size}, got {size_by_name[name]}"
        )

    # Clean up
    remote_files = [obj["Key"] for obj in file_objects]
    client.files.delete_files(remote_paths=remote_files, timeout=120.0)


def test_health_lv1():
    """test the files service health check."""
    client = DeepOriginClient()
    result = client.files.health()
    assert isinstance(result, dict), "should return a dict"


def test_version_lv1():
    """test the files service version endpoint."""
    client = DeepOriginClient()
    result = client.files.version()
    assert isinstance(result, dict), "should return a dict"
