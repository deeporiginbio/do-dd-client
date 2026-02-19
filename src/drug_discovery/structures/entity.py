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
        """the base path for the entity on the remote server"""
        return f"{self._remote_path_base}{self.to_hash()}{self._preferred_ext}"

    def upload(self, client: DeepOriginClient | None = None):
        """Upload the entity to the remote server.

        Overwrites the existing file if it exists."""

        if client is None:
            client = DeepOriginClient.get()

        client.files.upload_file(
            self.to_file(),
            remote_path=self._remote_path,
        )
