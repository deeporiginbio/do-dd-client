"""
This module defines the Entity class for handling file uploads to a remote server in the context of drug discovery structures.

The Entity class provides methods to manage and upload files, such as protein structure files, to a remote storage system using the DeepOrigin FilesClient.
"""

from dataclasses import dataclass


@dataclass
class Entity:
    """
    Represents an entity with file upload capabilities to a remote server.

    This class manages the remote path and provides an upload method to ensure that the entity's file is uploaded to the remote storage if it does not already exist there. It uses the DeepOrigin FilesClient for remote file operations.
    """

    def to_hash(self) -> str:
        """computes a hash of the entity"""
        raise NotImplementedError("to_hash needs to be implemented in the child class")

    @property
    def _remote_path(self) -> str:
        """the base path for the entity on the remote server"""
        return f"{self._remote_path_base}{self.to_hash()}{self._preferred_ext}"

    def upload(self):
        """Upload the entity to the remote server.

        Overwrites the existing file if it exists."""

        from deeporigin.platform import file_api

        file_api.upload_file(
            remote_path=self._remote_path,
            local_path=self.file_path,
        )
