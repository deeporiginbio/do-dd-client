"""
This module defines the Entity class for handling file uploads to a remote server in the context of drug discovery structures.

The Entity class provides methods to manage file uploads, such as protein structure files, to a remote storage system using the DeepOrigin FilesClient.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Optional

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

    ``project_id`` optionally pins the data platform project for this row. When
    unset, pass the :class:`~deeporigin.platform.client.DeepOriginClient` into
    :meth:`resolved_project_id` so the id comes from the client.

    ``tags`` is optional data-platform metadata (jsonb object on the row).
    When set, :meth:`sync` / :meth:`register` include it on create.
    """

    id: str | None = field(default=None, kw_only=True)
    remote_path: str | None = field(default=None, kw_only=True)
    local_path: str | None = field(default=None, kw_only=True)
    project_id: str | None = field(default=None, kw_only=True)
    tags: dict[str, Any] | None = field(default=None, kw_only=True)

    _remote_path_base: ClassVar[str] = ""
    _preferred_ext: ClassVar[str] = ""

    def resolved_project_id(self, client: DeepOriginClient | None = None) -> str | None:
        """Data platform project id for API calls.

        Returns :attr:`project_id` when set; otherwise ``client.project_id`` when
        ``client`` is given; otherwise ``None``. Does not read the filesystem.

        Args:
            client: Optional platform client (e.g. the one passed to
                :meth:`sync`).

        Returns:
            Project id string, or None if neither the entity nor the client
            provides one.
        """

        if self.project_id is not None:
            return self.project_id
        if client is not None:
            return client.project_id
        return None

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
                ``DeepOriginClient()``.
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
            DeepOriginException: If :attr:`remote_path` is set but
                :attr:`local_path` is not set.
        """
        if self.remote_path is None:
            return
        if self.local_path is not None:
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
            client: DeepOriginClient instance. If None, uses DeepOriginClient().

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
            client = DeepOriginClient()
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

        Serializes via :meth:`to_file` with :attr:`remote_path` temporarily
        cleared so subclasses that guard exports when only remote metadata is
        present (e.g. :meth:`Ligand.to_sdf`) still write from in-memory state
        on repeat uploads.

        Args:
            client: DeepOriginClient instance. If None, uses DeepOriginClient().
            remote_path: Custom remote path to upload to. When provided, sets
                :attr:`remote_path` before uploading. If :attr:`remote_path` is
                still unset, it is set to the default hash-based path.
        """

        stashed_remote_path = self.remote_path
        self.remote_path = None
        try:
            local_file = self.to_file()
        finally:
            self.remote_path = stashed_remote_path

        if client is None:
            client = DeepOriginClient()

        if remote_path is not None:
            self.remote_path = remote_path
        if self.remote_path is None:
            self.remote_path = (
                f"{self._remote_path_base}{self.to_hash()}{self._preferred_ext}"
            )

        client.files.upload(
            local_file,
            remote_path=self.remote_path,
        )
