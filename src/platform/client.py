"""Synchronous API client for the DeepOrigin Platform.

This module provides a minimal synchronous HTTP client for interacting with the
DeepOrigin Platform API. The client includes built-in authentication, singleton
caching for connection reuse, and convenient access to platform resources like
tools, functions, clusters, files, and executions.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple
import uuid
import weakref

import httpx

from deeporigin.auth import get_tokens
from deeporigin.config import get_value
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.clusters import Clusters
from deeporigin.platform.executions import Executions
from deeporigin.platform.files import Files
from deeporigin.platform.functions import Functions
from deeporigin.platform.organizations import Organizations

# Import Tools - safe because tools.py uses TYPE_CHECKING for DeepOriginClient
from deeporigin.platform.tools import Tools
from deeporigin.utils.constants import API_ENDPOINT, ENVS
from deeporigin.utils.core import _ensure_do_folder


class DeepOriginClient:
    """
    Minimal synchronous API client with built-in singleton cache.
    Use `DeepOriginClient.get()` to reuse one connection pool across notebook cells.
    If called without arguments, reads config from disk. Can also pass explicit
    token, org_key, and base_url parameters.
    """

    # class-level registry for singleton instances
    _instances: Dict[Tuple[str, str, str], "DeepOriginClient"] = {}

    def __init__(
        self,
        *,
        token: str | None = None,
        org_key: str | None = None,
        env: ENVS | None = None,
        base_url: str | None = None,
        timeout: float = 10.0,
        http2: bool = False,  # often faster off for simple REST
        refresh_token: str | None = None,
    ):
        """Initialize a DeepOrigin Platform client.

        If token, org_key, or env/base_url are not provided, they will be read
        from the configuration on disk. The client creates an HTTP connection
        pool and initializes access to platform resources (tools, functions,
        clusters, files, executions).

        Args:
            token: Authentication token. If None, reads from config.
            org_key: Organization key. If None, reads from config.
            env: Environment name (e.g., 'prod', 'staging'). If None and
                base_url is None, reads from config.
            base_url: Base URL for the API. If None, derived from env or config.
            timeout: Request timeout in seconds.
            http2: Whether to enable HTTP/2.
            refresh_token: Refresh token. If None and token is None, reads from config file.
        """

        if token is None:
            tokens = get_tokens()
            token = tokens["access"]

            if refresh_token is None:
                refresh_token = tokens.get("refresh")

        if org_key is None:
            org_key = get_value()["org_key"]

        if env is None and base_url is None:
            env = get_value()["env"]
            base_url = API_ENDPOINT[env]

        elif env is None and base_url is not None:
            raise ValueError("env is required when base_url is provided")

        elif env is not None and base_url is None:
            # get the base url from the environment
            base_url = API_ENDPOINT[env]

        self.refresh_token = refresh_token
        self.env = env

        self._org_key = org_key
        self.base_url = base_url.rstrip("/") + "/"

        self.tools = Tools(self)
        self.functions = Functions(self)
        self.clusters = Clusters(self)
        self.files = Files(self)
        self.executions = Executions(self)
        self.organizations = Organizations(self)

        # Initialize _client first (before setting token property)
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Accept": "application/json",
            },
            timeout=timeout,
            http2=http2,
        )

        # Set token property which will update headers automatically
        self.token = token

        # ensure sockets close if GC happens
        self._finalizer = weakref.finalize(self, self._client.close)

    @property
    def org_key(self) -> str:
        """Get the organization key.

        Returns:
            The organization key string.

        Raises:
            DeepOriginException: If org_key is not set
        """
        if self._org_key is None or self._org_key == "":
            raise DeepOriginException(
                title="Organization Key Required",
                message="The organization key is not set or is empty. Please configure it before using the client, using the `config` module.",
                fix="Use `config.set_org(org_key)` to set the organization key.",
                level="danger",
            )
        return self._org_key

    @property
    def token(self) -> str:
        """Get the authentication token.

        Returns:
            The authentication token string.
        """
        return self._token

    @token.setter
    def token(self, value: str) -> None:
        """Set the authentication token and update the Authorization header.

        Args:
            value: The new authentication token.
        """
        self._token = value
        if hasattr(self, "_client"):
            self._client.headers["Authorization"] = f"Bearer {value}"

    def __repr__(self) -> str:
        """Return a string representation of the client.

        Returns:
            A string showing the client's token (truncated), org_key, and base_url.
        """
        return f"DeepOrigin Platform Client(token={self.token[:5]}..., org_key={self.org_key}, base_url={self.base_url})"

    # -------- Singleton helpers --------
    @classmethod
    def get(
        cls,
        *,
        token: str | None = None,
        org_key: str | None = None,
        env: ENVS | None = None,
        base_url: str | None = None,
        timeout: float = 10.0,
        http2: bool = False,
        replace: bool = False,
    ) -> "DeepOriginClient":
        """
        Get a cached client for (base_url, token, org_key).
        If arguments are omitted, reads from config (same as __init__).
        If `replace=True`, closes and recreates the cached instance.
        """
        # Resolve config values (same logic as __init__)
        if token is None:
            tokens = get_tokens()
            token = tokens["access"]
            refresh_token = tokens.get("refresh")
        else:
            refresh_token = None

        if org_key is None:
            org_key = get_value()["org_key"]

        if env is None and base_url is None:
            env = get_value()["env"]
            base_url = API_ENDPOINT[env]

        elif env is not None and base_url is None:
            # get the base url from the environment
            base_url = API_ENDPOINT[env]

        # Normalize base_url for the key
        normalized_base_url = base_url.rstrip("/") + "/"
        key = (normalized_base_url, token, org_key)

        if replace and key in cls._instances:
            try:
                cls._instances[key].close()
            finally:
                cls._instances.pop(key, None)

        if key not in cls._instances:
            cls._instances[key] = cls(
                token=token,
                org_key=org_key,
                env=env,
                base_url=base_url,
                timeout=timeout,
                http2=http2,
                refresh_token=refresh_token,
            )

        return cls._instances[key]

    @classmethod
    def close_all(cls) -> None:
        """Close all cached client instances and clear the registry.

        This method closes all HTTP connections for cached client instances
        and removes them from the singleton registry. Useful for cleanup or
        when switching between different configurations.
        """
        for inst in cls._instances.values():
            inst.close()
        cls._instances.clear()

    def check_token(self) -> None:
        """Check if the token is expired."""

        if self.env in ["dev", "local"]:
            # no check for these envs
            return
        from deeporigin import auth

        if auth.is_token_expired(auth.decode_access_token(self.token, env=self.env)):
            if self.refresh_token is None:
                raise DeepOriginException(
                    title="Refresh Token Required",
                    message="The refresh token is not set. Please set it before using the client, using the `config` module.",
                    fix="Use `config.set_refresh_token(refresh_token)` to set the refresh token.",
                    level="danger",
                )

            # at this point, if we have a refresh token, we can assume that it's safe to cache to disk
            self.token = auth.refresh_tokens(self.refresh_token, env=self.env)
            auth.cache_tokens(
                tokens={
                    "access": self.token,
                    "refresh": self.refresh_token,
                },
                env=self.env,
            )

    # Removing from registry when explicitly closed
    def _detach_from_registry(self) -> None:
        """Remove this instance from the singleton registry.

        This is called automatically when the client is closed to ensure
        the registry doesn't hold references to closed clients.
        """
        key = (self.base_url, self.token, self.org_key)
        if key in self._instances and self._instances[key] is self:
            self._instances.pop(key, None)

    # -------- Low-level helpers --------
    def _get(self, path: str, **kwargs) -> httpx.Response:
        """Perform a GET request and raise on error.

        Args:
            path: API endpoint path (relative to base_url).
            **kwargs: Additional arguments passed to httpx.Client.get().

        Returns:
            The HTTP response object.

        Raises:
            httpx.HTTPStatusError: If the response status code indicates an error.
        """
        self.check_token()
        resp = self._client.get(path, **kwargs)
        resp.raise_for_status()
        return resp

    def _post(self, path: str, body: Optional[dict] = None, **kwargs) -> httpx.Response:
        """Perform a POST request and raise on error.

        Args:
            path: API endpoint path (relative to base_url).
            body: JSON data to send in the request body.
            **kwargs: Additional arguments passed to httpx.Client.post().

        Returns:
            The HTTP response object.

        Raises:
            httpx.HTTPStatusError: If the response status code indicates an error.
        """
        self.check_token()
        resp = self._client.post(path, json=body, **kwargs)

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Extract error message and details from response
            error_message = None
            error_details = None
            try:
                # Try to parse JSON error response
                error_data = e.response.json()
                # Common error message fields in API responses
                if isinstance(error_data, dict):
                    error_message = (
                        error_data.get("message")
                        or error_data.get("error")
                        or error_data.get("detail")
                    )
                    # Extract errors array if present
                    if "errors" in error_data:
                        error_details = json.dumps(error_data["errors"], indent=2)
                if error_message is None:
                    # Fallback to string representation of entire error_data
                    error_message = str(error_data)
            except (json.JSONDecodeError, ValueError):
                # Fall back to text response
                try:
                    error_message = e.response.text
                except Exception:
                    error_message = f"HTTP {e.response.status_code}"

            # Build curl command to reproduce the request
            full_url = self.base_url.rstrip("/") + "/" + path.lstrip("/")

            # Build curl command parts
            curl_parts = ["curl", "-X", "POST"]

            # Add headers (include Content-Type for JSON if body is present)
            headers = dict(self._client.headers)
            if body is not None and not any(
                key.lower() == "content-type" for key in headers.keys()
            ):
                headers["Content-Type"] = "application/json"

            # Redact sensitive headers before writing to disk
            sanitized_headers = {}
            for header_name, header_value in headers.items():
                if header_name.lower() == "authorization":
                    sanitized_headers[header_name] = "Bearer [REDACTED]"
                else:
                    sanitized_headers[header_name] = header_value

            for header_name, header_value in sanitized_headers.items():
                escaped_value = str(header_value).replace('"', '\\"')
                curl_parts.extend(["-H", f'"{header_name}: {escaped_value}"'])

            # Add JSON body if present
            if body is not None:
                body_json = json.dumps(body)
                curl_parts.extend(["-d", f"'{body_json}'"])

            # Add URL
            curl_parts.append(f'"{full_url}"')

            # Combine into full curl command
            curl_command = " \\\n  ".join(curl_parts)

            # Save to file with UUID name
            file_uuid = str(uuid.uuid4())
            filename = f"{file_uuid}.txt"
            filepath = _ensure_do_folder() / filename

            with open(filepath, "w") as f:
                f.write(curl_command)

            # Build message with error details
            message_parts = [
                f"A POST request to the platform API failed (HTTP {e.response.status_code})."
            ]
            if error_message:
                message_parts.append(f"Error message: {error_message}")
            if error_details:
                message_parts.append(f"Validation errors:\n{error_details}")
            message_parts.append(
                f"Curl command to reproduce the request saved to: {filepath}"
            )

            raise DeepOriginException(
                title="Request to platform API failed.",
                message=" ".join(message_parts),
                fix="Please contact support at https://help.deeporigin.com and provide this text file.",
                level="danger",
            ) from None

        return resp

    def _put(self, path: str, **kwargs) -> httpx.Response:
        """Perform a PUT request and raise on error.

        Args:
            path: API endpoint path (relative to base_url).
            **kwargs: Additional arguments passed to httpx.Client.put().

        Returns:
            The HTTP response object.

        Raises:
            httpx.HTTPStatusError: If the response status code indicates an error.
        """
        self.check_token()
        resp = self._client.put(path, **kwargs)
        resp.raise_for_status()
        return resp

    def _patch(self, path: str, **kwargs) -> httpx.Response:
        """Perform a PATCH request and raise on error.

        Args:
            path: API endpoint path (relative to base_url).
            **kwargs: Additional arguments passed to httpx.Client.patch().

        Returns:
            The HTTP response object.

        Raises:
            httpx.HTTPStatusError: If the response status code indicates an error.
        """
        self.check_token()
        resp = self._client.patch(path, **kwargs)
        resp.raise_for_status()
        return resp

    def _delete(self, path: str, **kwargs) -> httpx.Response:
        """Perform a DELETE request and raise on error.

        Args:
            path: API endpoint path (relative to base_url).
            **kwargs: Additional arguments passed to httpx.Client.delete().

        Returns:
            The HTTP response object.

        Raises:
            httpx.HTTPStatusError: If the response status code indicates an error.
        """
        self.check_token()
        resp = self._client.delete(path, **kwargs)
        resp.raise_for_status()
        return resp

    # -------- Convenience wrappers --------
    def get_json(self, path: str, **kwargs) -> Any:
        """Perform a GET request and return the JSON response.

        Args:
            path: API endpoint path (relative to base_url).
            **kwargs: Additional arguments passed to httpx.Client.get().

        Returns:
            The JSON-decoded response body.

        Raises:
            httpx.HTTPStatusError: If the response status code indicates an error.
        """
        return self._get(path, **kwargs).json()

    def post_json(self, path: str, body: dict[str, Any], **kwargs) -> Any:
        """Perform a POST request and return the JSON response.

        Args:
            path: API endpoint path (relative to base_url).
            body: JSON data to send in the request body.
            **kwargs: Additional arguments passed to httpx.Client.post().

        Returns:
            The JSON-decoded response body.

        Raises:
            httpx.HTTPStatusError: If the response status code indicates an error.
        """
        return self._post(path, body=body, **kwargs).json()

    # -------- Lifecycle --------
    def close(self) -> None:
        """Close the HTTP client connection and remove from registry.

        This method closes the underlying HTTP transport and removes this
        instance from the singleton registry. After calling close(), the
        client should not be used for further requests.
        """
        # close transport and remove from registry
        try:
            self._client.close()
        finally:
            self._detach_from_registry()

    def __enter__(self) -> "DeepOriginClient":
        """Enter the context manager.

        Returns:
            The client instance itself.
        """
        return self

    def __exit__(self, *args) -> None:
        """Exit the context manager and close the client.

        Args:
            *args: Exception information (ignored).
        """
        self.close()
