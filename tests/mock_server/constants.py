"""Constants for the local mock DeepOrigin API server."""

# Stable execution ID for ``deeporigin.bulk-docking`` POST (quote) responses so
# notebooks, tests, and fixtures do not depend on a new UUID on every request.
MOCK_BULK_DOCKING_EXECUTION_ID = "bdcc1213-4aa1-48e7-ada9-fbd6331f01d9"

# Shared ``file_path`` for bulk-docking pose rows (sanitizer). Must be relative to
# the mock files root: on disk that is ``tests/fixtures/files/<this path>``.
# Do not prefix with ``tests/fixtures/files/`` — the files router already maps
# ``remote_path`` under ``<fixtures_dir>/files/``.
MOCK_BULK_DOCKING_POSES_SDF_PATH = "128poses.sdf"
