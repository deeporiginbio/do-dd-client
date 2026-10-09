"""Runtime environment utilities: folder setup, env-var parsing, and timing."""

from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import sys
from typing import Union
import warnings

from beartype import beartype


@beartype
def _ensure_do_folder() -> Path:
    """Make sure the deeporigin scratch folder exists and return its path.

    The folder is typically ~/.deeporigin. It is created if absent and
    permissions are set to ``0700`` on every call so existing installs are
    repaired.
    """
    deeporigin_path = Path.home() / ".deeporigin"
    deeporigin_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        dir_stat = deeporigin_path.stat()
        if stat.S_IMODE(dir_stat.st_mode) != 0o700:
            if (
                sys.platform != "win32"
                and hasattr(os, "geteuid")
                and dir_stat.st_uid != os.geteuid()
            ):
                # Foreign-owned cache (e.g. image builds): cannot chmod; keep import working.
                warnings.warn(
                    f"{deeporigin_path} is owned by another user and is not mode 0700; "
                    "cached data may be readable by other users.",
                    stacklevel=2,
                )
                return deeporigin_path
            os.chmod(deeporigin_path, 0o700)
    except OSError:
        if sys.platform == "win32":
            pass
        else:
            raise
    return deeporigin_path


@beartype
def get_bool_env(env_var: str, default: bool = False) -> bool:
    """Parse a boolean environment variable robustly.

    Treats "0", "false", "no", "off", and empty strings as falsy;
    returns True only for "1", "true", "yes", or "on" (all case-insensitive).

    Parameters:
        env_var: The name of the environment variable to check.
        default: Value to return when the variable is not set.
    """
    value = os.environ.get(env_var)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def elapsed_minutes(
    start: Union[str, datetime],
    end: Union[str, datetime],
) -> int:
    """Compute elapsed minutes between two ISO-8601 UTC timestamps.

    Parameters:
        start: ISO-8601 UTC string (e.g. "2025-04-16T18:03:16.154Z") or a datetime.
        end:   Same format as start.

    Returns:
        Elapsed time in whole minutes, rounded to the nearest minute.
    """

    def to_dt(ts):
        if isinstance(ts, datetime):
            return ts
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")
        return dt.replace(tzinfo=timezone.utc)

    seconds_elapsed = (to_dt(end) - to_dt(start)).total_seconds()
    return int(round(seconds_elapsed / 60))
