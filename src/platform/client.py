"""Synchronous API client for the DeepOrigin Platform.

This module provides a minimal synchronous HTTP client for interacting with the
DeepOrigin Platform API. The client includes built-in authentication, singleton
caching for connection reuse, and convenient access to platform resources like
tools, functions, clusters, files, and executions.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Dict, Optional, Set, Tuple, get_args
import uuid
import weakref

import httpx

from deeporigin.auth import get_token
from deeporigin.config import get_value
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.clusters import Clusters
from deeporigin.platform.executions import Executions
from deeporigin.platform.files import Files
from deeporigin.platform.functions import Functions
from deeporigin.platform.organizations import Organizations
from deeporigin.platform.tools import Tools
from deeporigin.utils.constants import API_ENDPOINT, ENV_VARIABLES, ENVS
from deeporigin.utils.core import _ensure_do_folder


def _generate_local_token() -> str:
    """Generate a dummy JWT token for local testing.

    Returns:
        A JWT token string for local environment testing.
    """
    import jwt

    now = int(time.time())
    one_year_seconds = 365 * 24 * 60 * 60
    decoded_token = {
        "exp": now + one_year_seconds,
        "iat": now,
        "jti": "onrtro:11f26c41-4d64-15dc-cc13-bfbbfedbd744",
        "iss": "https://local.deeporigin.io/realms/deeporigin",
        "aud": ["do-app", "auth-service"],
        "sub": "6b06d8f8-1f55-472c-a86c-f19651ba4b20",
        "typ": "Bearer",
        "azp": "pa-token-365d",
        "sid": "3516d772-185c-6422-6bd8-5f7f34cf6a71",
        "scope": "organizations:owner long-live-token",
        "email_verified": True,
        "name": "Local User",
        "given_name": "Local",
        "family_name": "User",
        "email": "user@deeporigin.com",
    }
    return jwt.encode(decoded_token, "secret")


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
        max_retries: int = 3,
        retryable_status_codes: Set[int] | None = None,
        retry_backoff_factor: float = 1.0,
        max_retry_delay: float = 60.0,
    ):
        """Initialize a DeepOrigin Platform client.

        Environment variables (DEEPORIGIN_TOKEN, DEEPORIGIN_ORG_KEY, DEEPORIGIN_ENV)
        ALWAYS override explicit parameters and configuration files. If environment
        variables are set, disk configuration is NOT read.

        If environment variables are not set, explicit parameters are used. If
        parameters are None, values are read from configuration files on disk.
        The client creates an HTTP connection pool and initializes access to
        platform resources (tools, functions, clusters, files, executions).

        Args:
            token: Authentication token. Overridden by DEEPORIGIN_TOKEN env var.
            org_key: Organization key. Overridden by DEEPORIGIN_ORG_KEY env var.
            env: Environment name (e.g., 'prod', 'staging'). Overridden by
                DEEPORIGIN_ENV env var. If None and base_url is None, reads from config.
            base_url: Base URL for the API. If None, derived from env or config.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retry attempts for failed requests.
                Defaults to 3. Set to 0 to disable retries.
            retryable_status_codes: Set of HTTP status codes that should trigger
                a retry. Defaults to {429, 500, 502, 503, 504}.
            retry_backoff_factor: Multiplier for exponential backoff between retries.
                Delay = min(retry_backoff_factor * (2 ** attempt_number), max_retry_delay).
                The delay grows exponentially but is capped at max_retry_delay to prevent
                excessive wait times. Defaults to 1.0.
            max_retry_delay: Maximum delay in seconds between retry attempts. The exponential
                backoff delay will be capped at this value. Defaults to 60.0 seconds.
        """

        # Environment variables ALWAYS override explicit parameters and skip disk reads
        if ENV_VARIABLES["access_token"] in os.environ:
            token = os.environ[ENV_VARIABLES["access_token"]]
        elif token is None:
            token = get_token()

        if ENV_VARIABLES["org_key"] in os.environ:
            org_key = os.environ[ENV_VARIABLES["org_key"]]
        elif org_key is None:
            org_key = get_value()["org_key"]

        # Handle env and base_url resolution
        if ENV_VARIABLES["env"] in os.environ:
            env = os.environ[ENV_VARIABLES["env"]]
            if env not in get_args(ENVS):
                raise ValueError(
                    f"Invalid environment in DEEPORIGIN_ENV: {env}. Must be one of: dev, prod, staging, local"
                )
            if base_url is None:
                base_url = API_ENDPOINT[env]
        elif env is None and base_url is None:
            env = get_value()["env"]
            base_url = API_ENDPOINT[env]
        elif env is None and base_url is not None:
            raise ValueError("env is required when base_url is provided")
        elif env is not None and base_url is None:
            # get the base url from the environment
            base_url = API_ENDPOINT[env]
        self.env = env

        self._org_key = org_key
        self.base_url = base_url.rstrip("/") + "/"

        self.tools = Tools(self)
        self.functions = Functions(self)
        self.clusters = Clusters(self)
        self.files = Files(self)
        self.executions = Executions(self)
        self.organizations = Organizations(self)

        # Retry configuration
        self.max_retries = max_retries
        self.retryable_status_codes = (
            retryable_status_codes
            if retryable_status_codes is not None
            else {429, 500, 502, 503, 504}
        )
        self.retry_backoff_factor = retry_backoff_factor
        self.max_retry_delay = max_retry_delay

        # Initialize _client first (before setting token property)
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Accept": "application/json",
            },
            timeout=timeout,
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
            A string showing the client's name (from token), org_key, and base_url.
        """
        from deeporigin import auth

        name = "Unknown"
        try:
            decoded_token = auth.decode_access_token(self.token)
            name = decoded_token.get("name", "Unknown")
        except Exception:
            # If token decoding fails, use "Unknown"
            pass

        return f"DeepOrigin Platform Client for {name} (org_key={self.org_key}, base_url={self.base_url})"

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
        max_retries: int = 3,
        retryable_status_codes: Set[int] | None = None,
        retry_backoff_factor: float = 1.0,
        max_retry_delay: float = 60.0,
        replace: bool = False,
    ) -> "DeepOriginClient":
        """
        Get a cached client for (base_url, token, org_key).
        If arguments are omitted, reads from config (same as __init__).
        If `replace=True`, closes and recreates the cached instance.

        Args:
            token: Authentication token. If None, reads from config.
            org_key: Organization key. If None, reads from config.
            env: Environment name (e.g., 'prod', 'staging'). If None and
                base_url is None, reads from config.
            base_url: Base URL for the API. If None, derived from env or config.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retry attempts for failed requests.
                Defaults to 3. Set to 0 to disable retries.
            retryable_status_codes: Set of HTTP status codes that should trigger
                a retry. Defaults to {429, 500, 502, 503, 504}.
            retry_backoff_factor: Multiplier for exponential backoff between retries.
                Delay = min(retry_backoff_factor * (2 ** attempt_number), max_retry_delay).
                The delay grows exponentially but is capped at max_retry_delay to prevent
                excessive wait times. Defaults to 1.0.
            max_retry_delay: Maximum delay in seconds between retry attempts. The exponential
                backoff delay will be capped at this value. Defaults to 60.0 seconds.
            replace: If True, close and recreate the cached instance.

        Returns:
            A cached DeepOriginClient instance.
        """
        # Resolve config values (same logic as __init__)
        # Environment variables ALWAYS override explicit parameters and skip disk reads
        if ENV_VARIABLES["access_token"] in os.environ:
            token = os.environ[ENV_VARIABLES["access_token"]]
        elif token is None:
            token = get_token()

        if ENV_VARIABLES["org_key"] in os.environ:
            org_key = os.environ[ENV_VARIABLES["org_key"]]
        elif org_key is None:
            org_key = get_value()["org_key"]

        # Handle env and base_url resolution
        if ENV_VARIABLES["env"] in os.environ:
            env = os.environ[ENV_VARIABLES["env"]]
            if env not in get_args(ENVS):
                raise ValueError(
                    f"Invalid environment in DEEPORIGIN_ENV: {env}. Must be one of: dev, prod, staging, local"
                )
            if base_url is None:
                base_url = API_ENDPOINT[env]
        elif env is None and base_url is None:
            env = get_value()["env"]
            base_url = API_ENDPOINT[env]
        elif env is None and base_url is not None:
            raise ValueError("env is required when base_url is provided")
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
                max_retries=max_retries,
                retryable_status_codes=retryable_status_codes,
                retry_backoff_factor=retry_backoff_factor,
                max_retry_delay=max_retry_delay,
            )

        return cls._instances[key]

    @classmethod
    def from_env(
        cls,
        env: ENVS | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        retryable_status_codes: Set[int] | None = None,
        retry_backoff_factor: float = 1.0,
        max_retry_delay: float = 60.0,
    ) -> "DeepOriginClient":
        """Create a client instance from environment configuration.

        Reads configuration from environment variables (DEEPORIGIN_TOKEN,
        DEEPORIGIN_ORG_KEY, DEEPORIGIN_ENV) or from
        disk files (~/.DeepOrigin/api_tokens.json and config.json).

        Args:
            env: Environment name (e.g., 'prod', 'staging', 'local'). If None,
                reads from DEEPORIGIN_ENV environment variable or config file.
            base_url: Base URL for the API. If None, derived from env (defaults
                to http://127.0.0.1:4931 for 'local').
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retry attempts for failed requests.
                Defaults to 3. Set to 0 to disable retries.
            retryable_status_codes: Set of HTTP status codes that should trigger
                a retry. Defaults to {429, 500, 502, 503, 504}.
            retry_backoff_factor: Multiplier for exponential backoff between retries.
                Delay = min(retry_backoff_factor * (2 ** attempt_number), max_retry_delay).
                The delay grows exponentially but is capped at max_retry_delay to prevent
                excessive wait times. Defaults to 1.0.
            max_retry_delay: Maximum delay in seconds between retry attempts. The exponential
                backoff delay will be capped at this value. Defaults to 60.0 seconds.

        Returns:
            A new DeepOriginClient instance configured from environment variables
            or files.
        """
        # Determine environment
        if env is None:
            env = os.environ.get(ENV_VARIABLES["env"]) or get_value()["env"]
            if not env:
                env = "prod"  # default

        # Validate env is a valid ENVS type
        if env not in get_args(ENVS):
            raise ValueError(
                f"Invalid environment: {env}. Must be one of: dev, prod, staging, local"
            )

        if env == "local":
            LOCAL_TOKEN = _generate_local_token()
            # short circuit for local - use dummy tokens, no disk/env reading
            # base_url can be overridden by the caller (e.g., test_server_url)
            if base_url is None:
                base_url = API_ENDPOINT["local"]
            return cls(
                token=LOCAL_TOKEN,
                org_key="deeporigin",
                env="local",
                base_url=base_url,
                timeout=timeout,
            )

        # Get token for the specified environment (reads from env vars or files)
        token = get_token(env=env)

        # Get org_key (reads from env vars or config file)
        org_key = get_value()["org_key"]

        # Get base_url
        if base_url is None:
            base_url = API_ENDPOINT[env]

        return cls(
            token=token,
            org_key=org_key,
            env=env,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            retryable_status_codes=retryable_status_codes,
            retry_backoff_factor=retry_backoff_factor,
            max_retry_delay=max_retry_delay,
        )

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

        from deeporigin import auth

        if auth.is_token_expired(self.token):
            raise DeepOriginException(
                title="Token Expired",
                message="Token is expired. Please refer to https://client-docs.deeporigin.io/how-to/auth.html to get a new token.",
                level="danger",
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
    def _should_retry(
        self,
        error: Exception,
    ) -> bool:
        """Determine if a request should be retried based on the error.

        Args:
            error: The exception that occurred.

        Returns:
            True if the request should be retried, False otherwise.
        """
        if self.max_retries == 0:
            return False

        # Retry on network errors and timeouts
        if isinstance(error, (httpx.NetworkError, httpx.TimeoutException)):
            return True

        # Retry on specific HTTP status codes
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code in self.retryable_status_codes

        return False

    def _retry_request(
        self,
        request_func: Callable[[], httpx.Response],
        method: str,
        path: str,
        body: dict | None = None,
    ) -> httpx.Response:
        """Execute an HTTP request with retry logic.

        Args:
            request_func: A callable that executes the HTTP request and returns
                a Response. Should raise httpx exceptions on failure.
            method: HTTP method name (e.g., 'GET', 'POST') for error handling.
            path: API endpoint path for error handling.
            body: Optional request body for error handling.

        Returns:
            The HTTP response object.

        Raises:
            httpx.HTTPStatusError: If the request fails after all retries.
            httpx.NetworkError: If network errors persist after all retries.
            httpx.TimeoutException: If timeouts persist after all retries.
        """
        for attempt in range(self.max_retries + 1):
            try:
                response = request_func()
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                if self._should_retry(e) and attempt < self.max_retries:
                    delay = min(
                        self.retry_backoff_factor * (2**attempt), self.max_retry_delay
                    )
                    time.sleep(delay)
                    continue
                # Not retryable or out of retries - handle HTTPStatusError specially
                self._handle_request_error(method, path, e, body=body)
            except (httpx.NetworkError, httpx.TimeoutException) as e:
                if self._should_retry(e) and attempt < self.max_retries:
                    delay = min(
                        self.retry_backoff_factor * (2**attempt), self.max_retry_delay
                    )
                    time.sleep(delay)
                    continue
                raise

    def _handle_request_error(
        self,
        method: str,
        path: str,
        error: httpx.HTTPStatusError,
        body: Optional[dict] = None,
    ) -> None:
        """Handle HTTP request errors by extracting error details and saving curl command.

        Args:
            method: HTTP method (e.g., 'POST', 'PUT').
            path: API endpoint path (relative to base_url).
            error: The HTTPStatusError that was raised.
            body: Optional JSON body that was sent with the request.

        Raises:
            DeepOriginException: Always raises with error details and curl command filepath.
        """
        # Extract error message and details from response
        error_message = None
        error_details = None
        try:
            # Try to parse JSON error response
            error_data = error.response.json()

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
        except json.JSONDecodeError:
            # Fall back to text response
            try:
                error_message = error.response.text
            except Exception:
                error_message = f"HTTP {error.response.status_code}"

        # Build curl command to reproduce the request
        full_url = self.base_url.rstrip("/") + "/" + path.lstrip("/")

        # Build curl command parts
        curl_parts = ["curl", "-X", method.upper()]

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
            f"A {method.upper()} request to the platform API failed (HTTP {error.response.status_code})."
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

        def request() -> httpx.Response:
            return self._client.get(path, **kwargs)

        return self._retry_request(request, "GET", path, body=None)

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

        def request() -> httpx.Response:
            return self._client.post(path, json=body, **kwargs)

        return self._retry_request(request, "POST", path, body=body)

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

        def request() -> httpx.Response:
            return self._client.put(path, **kwargs)

        body = kwargs.get("json")
        return self._retry_request(request, "PUT", path, body=body)

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

        def request() -> httpx.Response:
            return self._client.patch(path, **kwargs)

        body = kwargs.get("json")
        return self._retry_request(request, "PATCH", path, body=body)

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

        def request() -> httpx.Response:
            return self._client.delete(path, **kwargs)

        body = kwargs.get("json")
        return self._retry_request(request, "DELETE", path, body=body)

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
