"""
This module defines the Entity class for handling file uploads to a remote server in the context of drug discovery structures.

The Entity class provides methods to manage file uploads, such as protein structure files, to a remote storage system using the DeepOrigin FilesClient.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient


@dataclass
class Entity(ABC):
    """
    Represents an entity with file upload capabilities to a remote server.

    ``local_path`` is set when the entity was created from a local file or after
    :meth:`download`. ``remote_path`` is set when created from platform metadata or
    after :meth:`upload`. Call :meth:`upload` before passing paths to remote tools;
    call :meth:`download` when you need a local file for display or analysis.
    """

    id: str | None = field(default=None, kw_only=True)
    remote_path: str | None = field(default=None, kw_only=True)
    local_path: str | None = field(default=None, kw_only=True)

    @abstractmethod
    def to_hash(self) -> str:
        """computes a hash of the entity"""
        ...

    @abstractmethod
    def to_file(self, file_path: Optional[str | Path] = None) -> str:
        """Dump state to a file"""
        ...

    @abstractmethod
    def sync(
        self,
        *,
        lazy: bool = False,
        client: Optional[DeepOriginClient] = None,
        remote_path: Optional[str] = None,
    ) -> None:
        """Sync this entity to the data platform (upload and/or register as needed).

        Subclasses define how records are created or linked; all share the
        convention that ``lazy=True`` may skip work when an ID is already set.

        Args:
            lazy: If True, implementations may return early when already synced.
            client: DeepOrigin client. If None, implementations typically use
                ``DeepOriginClient.get()``.
            remote_path: Optional explicit remote storage path for uploads.
        """
        ...

    def ensure_remote_path(
        self,
        *,
        client: DeepOriginClient,
        label: str,
    ) -> None:
        """Ensure :attr:`remote_path` is set after a lazy :meth:`sync` may have no-oped.

        If the entity already has a platform ``id`` but ``remote_path`` was never
        populated (e.g. rehydrated metadata only), ``sync(lazy=True)`` returns
        early. This performs a full sync when needed, then raises if the path is
        still missing.

        Args:
            client: Authenticated client for sync/upload.
            label: Human-readable name for error messages (e.g. ``"Protein"``).

        Raises:
            ValueError: If ``remote_path`` cannot be determined after sync.
        """
        if self.remote_path:
            return
        self.sync(lazy=False, client=client)
        if not self.remote_path:
            raise ValueError(
                f"{label} remote_path is not set and could not be synchronized. "
                "Ensure the structure has been uploaded or created via the "
                "Deep Origin API before calling this function."
            )

    def _assert_rehydrated_for_file_export(
        self,
        *,
        entity_label: str,
        format_name: str,
    ) -> None:
        """Require a local file when :attr:`remote_path` is set.

        Subclasses use this for :meth:`to_file` and format-specific writers that do
        not perform network I/O. Call :meth:`download` first (or use
        ``from_id(..., download=True)``).

        Args:
            entity_label: Class name for errors (e.g. ``Ligand`` or ``Protein``).
            format_name: Format label for errors (e.g. ``SDF`` or ``PDB``).

        Raises:
            DeepOriginException: If :attr:`remote_path` is set but neither
                ``file_path`` (when present on the subclass) nor :attr:`local_path`
                is set.
        """
        if self.remote_path is None:
            return
        remote_path = getattr(self, "remote_path", None)
        if remote_path is not None or self.local_path is not None:
            return
        raise DeepOriginException(
            title=f"{entity_label} not rehydrated",
            message=(
                f"Cannot write {format_name}: remote_path is set but no local file is available. "
                f"Call {entity_label}.download() to fetch the structure file, or use "
                "from_id(..., download=True)."
            ),
        )

    def download(
        self,
        *,
        lazy: bool = True,
        client: DeepOriginClient | None = None,
    ) -> str:
        """Download the entity file from remote storage.

        No-ops if ``local_path`` is already set.

        Args:
            client: DeepOriginClient instance. If None, uses DeepOriginClient.get().

        Returns:
            The local file path.

        Raises:
            ValueError: If neither local_path nor remote_path is available.
        """
        if self.local_path is not None:
            return self.local_path
        if self.remote_path is None:
            raise ValueError("No local_path or remote_path available")
        if client is None:
            client = DeepOriginClient.get()
        self.local_path = client.files.download(
            remote_path=self.remote_path,
            lazy=lazy,
            local_path=self.local_path,
        )
        return self.local_path

    def upload(
        self,
        *,
        client: DeepOriginClient | None = None,
        remote_path: str | None = None,
    ) -> None:
        """Upload the entity to the remote server.

        Args:
            client: DeepOriginClient instance. If None, uses DeepOriginClient.get().
            remote_path: Custom remote path to upload to. When provided, sets
                :attr:`remote_path` before uploading. If :attr:`remote_path` is
                still unset, it is set to the default hash-based path.
        """

        if client is None:
            client = DeepOriginClient.get()

        if remote_path is not None:
            self.remote_path = remote_path
        if self.remote_path is None:
            self.remote_path = (
                f"{self._remote_path_base}{self.to_hash()}{self._preferred_ext}"
            )

        client.files.upload(
            self.to_file(),
            remote_path=self.remote_path,
        )
