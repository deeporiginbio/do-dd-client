"""
This module defines the Entity class for handling file uploads to a remote server in the context of drug discovery structures.

The Entity class provides methods to manage file uploads, such as protein structure files, to a remote storage system using the DeepOrigin FilesClient.
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
