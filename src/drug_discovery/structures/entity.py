"""
This module defines the Entity class for handling file uploads to a remote server in the context of drug discovery structures.

The Entity class provides methods to manage and upload files, such as protein structure files, to a remote storage system using the DeepOrigin FilesClient.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from deeporigin.platform.client import DeepOriginClient


@dataclass
class Entity(ABC):
    """
    Represents an entity with file upload capabilities to a remote server.

    This class manages the remote path and provides an upload method to ensure that the entity's file is uploaded to the remote storage if it does not already exist there. It uses the DeepOrigin FilesClient for remote file operations.
    """

    id: str | None = field(default=None, kw_only=True)

    @abstractmethod
    def to_hash(self) -> str:
        """computes a hash of the entity"""
        ...

    @abstractmethod
    def to_file(self, file_path: Optional[str | Path] = None) -> str:
        """Dump state to a file"""
        ...

    @property
    def _remote_path(self) -> str:
        """The path for the entity on the remote server.

        Returns the override set via :meth:`upload` or :meth:`sync` if one
        exists, otherwise falls back to the default hash-based path.
        """
        override = getattr(self, "_remote_path_override", None)
        if override is not None:
            return override
        return f"{self._remote_path_base}{self.to_hash()}{self._preferred_ext}"

    def upload(
        self,
        *,
        client: DeepOriginClient | None = None,
        remote_path: str | None = None,
    ):
        """Upload the entity to the remote server.

        Args:
            client: DeepOriginClient instance. If None, uses DeepOriginClient.get().
            remote_path: Custom remote path to upload to. When provided, this
                overrides the default hash-based path for this entity
                permanently (affecting subsequent ``_remote_path`` lookups).
        """

        if client is None:
            client = DeepOriginClient.get()

        if remote_path is not None:
            self._remote_path_override = remote_path

        client.files.upload_file(
            self.to_file(),
            remote_path=self._remote_path,
        )
