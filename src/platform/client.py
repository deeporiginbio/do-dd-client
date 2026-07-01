"""Synchronous API client for the DeepOrigin Platform.

This module provides a minimal synchronous HTTP client for interacting with the
DeepOrigin Platform API. The client includes built-in authentication, singleton
caching for connection reuse, and convenient access to platform resources like
tools, clusters, files, executions, and user logs.

Construct a client using the no-arg constructor or one of three factory methods:

- ``DeepOriginClient()`` — if ``DO_AUTH_TOKEN`` and ``DO_ORG_KEY`` are set, delegates
  to :meth:`DeepOriginClient.from_env_variables` (``DO_BASE_URL`` is optional; when
  unset the API URL is inferred from the JWT issuer). Otherwise uses disk config
  or the local mock, depending on ``DO_ENV``.
- ``DeepOriginClient.from_headers(headers)`` — served tool (HTTP request headers)
- ``DeepOriginClient.from_env_variables()`` — provisioned container (OS env vars only)
- ``DeepOriginClient.from_disk(env=...)`` — interactive / Jupyter (``~/.deeporigin/``)
"""

from __future__ import annotations

import json
import os
import time
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Optional,
    Self,
    Tuple,
    cast,
    get_args,
    overload,
)
import uuid
import weakref

import httpx

from deeporigin.auth import get_token, token_to_env
from deeporigin.config import get_value
from deeporigin.exceptions import DeepOriginException
from deeporigin.utils.constants import (
    API_ENDPOINT,
    ENV_VARIABLES,
    ENVS,
    HTTP_RETRYABLE_STATUS_CODES,
)
from deeporigin.utils.env import _ensure_do_folder

if TYPE_CHECKING:
    from deeporigin.platform.billing import Billing
    from deeporigin.platform.clusters import Clusters
    from deeporigin.platform.entities import Entities
    from deeporigin.platform.executions import Executions
    from deeporigin.platform.files import Files
    from deeporigin.platform.organizations import Organizations
    from deeporigin.platform.progress_reports import ProgressReports
    from deeporigin.platform.projects import Projects
    from deeporigin.platform.results import Results
    from deeporigin.platform.tools import Tools
    from deeporigin.platform.user_logs import UserLogs

# Cache for local token to ensure consistency across calls
_LOCAL_TOKEN_CACHE: str | None = None


def _generate_local_token() -> str:
    """Generate a dummy JWT token for local testing.

    Returns:
        A JWT token string for local environment testing.
    """
    global _LOCAL_TOKEN_CACHE

    if _LOCAL_TOKEN_CACHE is not None:
        return _LOCAL_TOKEN_CACHE

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
    _LOCAL_TOKEN_CACHE = jwt.encode(decoded_token, "secret")
    return _LOCAL_TOKEN_CACHE


def _base_url_for_token(token: str) -> str:
    """Resolve platform API base URL from a JWT using its issuer claim.

    Args:
        token: Access token string.

    Returns:
        Gateway URL for the environment implied by :func:`~deeporigin.auth.token_to_env`.

    Raises:
        DeepOriginException: If the token cannot be decoded (caller should set
            ``DO_BASE_URL`` / ``base_url`` explicitly or supply a valid JWT).
    """
    import jwt

    try:
        env = token_to_env(token)
    except jwt.exceptions.PyJWTError as exc:
        raise DeepOriginException(
            title="Invalid access token",
            message=(
                "Could not infer the platform API base URL from the access token."
            ),
            fix=(
                "Set DO_BASE_URL or base_url explicitly, or provide a valid JWT "
                "with a recognizable issuer."
            ),
            level="danger",
        ) from exc
    return API_ENDPOINT[env]


class _DeepOriginMeta(type):
    """Metaclass that owns singleton caching and the no-arg priority chain.

    **Why a metaclass instead of __new__ + __init__?**

    Python always calls ``__init__`` after ``__new__``, *even when ``__new__``
    returns an already-initialized cached instance*.  A plain ``__new__``-based
    singleton therefore forces ``__init__`` to carry awkward early-return guards:

    .. code-block:: python

        def __init__(self, ...):
            if base_url is None:   # no-arg path already handled by __new__
                return
            if hasattr(self, "_client"):  # returned from cache, already set up
                return
            ...  # actual initialisation

    Those guards make ``__init__`` hard to reason about because it has three
    distinct entry points bundled into one method.

    The metaclass ``__call__`` runs *before* ``__new__`` and ``__init__`` and
    can return an existing object without ever invoking ``__init__``.  This
    keeps ``__init__`` a clean, unconditional initialiser that always runs
    exactly once per new instance:

    .. code-block:: text

        _DeepOriginMeta.__call__
        │
        ├── no-arg path  → delegates to from_env_variables / from_local / from_disk
        │                  returns directly; __init__ is never called
        │
        ├── cache hit    → returns cls._instances[key]
        │                  __init__ is never called
        │
        └── cache miss   → super().__call__(...)  # __new__ + __init__ run exactly once
                           stores result in cache, returns
    """

    def __call__(
        cls,
        *,
        base_url: str | None = None,
        token: str | None = None,
        org_key: str | None = None,
        project_id: str | None = None,
        _app: str = "python-client",
        _session: str | None = None,
        **kwargs: Any,
    ) -> "DeepOriginClient":
        """Intercept construction to handle caching and the no-arg priority chain.

        Args:
            base_url: API base URL. When ``None`` (with no other core fields),
                triggers the no-arg priority chain. When ``None`` but ``token`` is
                explicitly provided, the URL is inferred from the token issuer (see
                :func:`~deeporigin.auth.token_to_env`). The no-arg path that reads
                OS env vars uses :meth:`~DeepOriginClient.from_env_variables` when
                ``DO_AUTH_TOKEN`` and ``DO_ORG_KEY`` are set; ``DO_BASE_URL`` may be
                omitted in that case.
            token: Authentication token.
            org_key: Organization key.
            project_id: Data platform project id.
            _app: Internal app identifier; part of the cache key.
            _session: Internal session identifier; part of the cache key.
            **kwargs: Forwarded to ``__init__`` for new instances.

        Returns:
            A ``DeepOriginClient`` instance (cached or newly created).
        """
        # ---- no-arg priority chain ----
        if base_url is None and token is None and org_key is None:
            env_token = os.environ.get(ENV_VARIABLES["access_token"])
            env_org = os.environ.get(ENV_VARIABLES["org_key"])
            if env_token and env_org:
                instance = cls.from_env_variables()
            else:
                # Route to from_local when DO_ENV=local; pass hint to from_disk otherwise
                # (from_disk itself never reads environment variables)
                env_hint = os.environ.get(ENV_VARIABLES["env"]) or None
                if env_hint == "local":
                    instance = cls.from_local()
                else:
                    instance = cls.from_disk(env_hint)
            if project_id is not None:
                instance.project_id = project_id
            return instance

        # ---- singleton cache lookup ----
        if base_url is None:
            if token is None:
                raise ValueError(
                    "base_url is required when constructing with explicit credentials "
                    "unless token is provided (base URL is inferred from the token)."
                )
            base_url = _base_url_for_token(token)
        normalized_base_url = base_url.rstrip("/") + "/"
        # project_id is intentionally excluded from the cache key: it is a
        # mutable field updated by projects.load() and must not create duplicate
        # singletons.
        key = (normalized_base_url, token, org_key, _app, _session)

        if key in cls._instances:
            return cls._instances[key]

        # ---- first-time construction: __new__ + __init__ run exactly once ----
        instance = super().__call__(
            base_url=base_url,
            token=token,
            org_key=org_key,
            project_id=project_id,
            _app=_app,
            _session=_session,
            **kwargs,
        )
        instance._cache_key = key
        cls._instances[key] = instance
        return instance


def _get_header_value(headers: Any, name: str) -> Any:
    """Return header *name* from *headers* using case-insensitive fallback.

    Starlette/FastAPI ``Headers`` implement case-insensitive ``.get``. Plain
    ``dict(request.headers)`` uses lowercase keys only, so canonical names like
    ``X-Do-Auth-Token`` do not match without trying ``name.lower()``.

    Args:
        headers: Mapping with ``.get`` (e.g. Starlette ``Headers`` or ``dict``).
        name: Canonical header name (e.g. ``X-Do-Auth-Token``).

    Returns:
        The header value, or ``None`` if missing or empty.
    """
    if headers is None:
        return None
    for key in (name, name.lower(), name.upper()):
        v = headers.get(key)
        if v not in (None, ""):
            return v
    return None


class DeepOriginClient(metaclass=_DeepOriginMeta):
    """Minimal synchronous API client with built-in singleton cache.

    ``base_url`` and ``token`` are fixed after construction (though ``token``
    may be reassigned via the ``token`` setter). ``org_key`` and ``project_id``
    may be updated on the instance; use :func:`deeporigin.config.set_org` to
    persist a default organization. Other mutable attributes (``tag``,
    ``record``, ``max_retries``, etc.) can also be changed after construction.

    The singleton cache keys on ``(base_url, token, org_key, _app, _session)``.
    Calling the constructor multiple times with the same resolved values returns
    the same cached instance and reuses the underlying connection pool.
    Changing ``org_key`` or ``project_id`` on an instance does not change the
    cache key — use :func:`deeporigin.projects.load` for project selection
    workflows that coordinate with the projects API.

    Examples:
        # No-arg: prefers OS env vars, falls back to ~/.deeporigin/
        client = DeepOriginClient()

        # Served tool — reads from HTTP request headers
        client = DeepOriginClient.from_headers(request.headers)

        # Provisioned container — DO_AUTH_TOKEN and DO_ORG_KEY required; DO_BASE_URL optional
        client = DeepOriginClient.from_env_variables()

        # Interactive / Jupyter — reads from ~/.deeporigin/ config files
        client = DeepOriginClient.from_disk(env="prod")
    """

    tools: Tools | None
    clusters: Clusters | None
    files: Files  # client always has files
    executions: Executions | None
    user_logs: UserLogs | None
    organizations: Organizations | None
    billing: Billing | None
    entities: Entities | None
    results: Results  # client always has results
    progress_reports: ProgressReports | None
    projects: Projects | None

    # Singleton registry — managed by _DeepOriginMeta.__call__.
    # Key: (base_url, token, org_key, _app, _session)
    # project_id is NOT part of the key because it is mutable (updated by
    # projects.load()) — including it would create duplicate singletons.
    _instances: Dict[
        Tuple[str, str | None, str | None, str, str | None],
        "DeepOriginClient",
    ] = {}

    def __new__(cls, **_kwargs: Any) -> "DeepOriginClient":
        """Allocate a bare instance.

        All caching and the no-arg priority chain live in
        ``_DeepOriginMeta.__call__``.  By the time ``__new__`` is reached we
        already know this is a first-time construction, so just allocate.
        """
        return super().__new__(cls)

    @overload
    def __init__(
        self,
        *,
        project_id: str | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        *,
        token: str,
        org_key: str | None = None,
        project_id: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_backoff_factor: float = 1.0,
        max_retry_delay: float = 60.0,
        record: bool = False,
        tag: str | None = None,
        billing_tag: str | None = None,
        _app: str = "python-client",
        _session: str | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        org_key: str | None = None,
        project_id: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_backoff_factor: float = 1.0,
        max_retry_delay: float = 60.0,
        record: bool = False,
        tag: str | None = None,
        billing_tag: str | None = None,
        _app: str = "python-client",
        _session: str | None = None,
    ) -> None: ...

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        org_key: str | None = None,
        project_id: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_backoff_factor: float = 1.0,
        max_retry_delay: float = 60.0,
        record: bool = False,
        tag: str | None = None,
        billing_tag: str | None = None,
        _app: str = "python-client",
        _session: str | None = None,
    ) -> None:
        """Initialize a new ``DeepOriginClient`` instance.

        Called exactly once per unique ``(base_url, token, org_key, project_id,
        _app, _session)`` tuple.  Caching and the no-arg priority chain are
        handled by ``_DeepOriginMeta.__call__`` before this method is ever
        reached.

        Prefer ``DeepOriginClient()`` or a factory class method over calling
        this method directly.

        Args:
            base_url: API base URL (required whenever this initializer runs).
            token: Authentication token, or ``None`` if requests do not use bearer auth.
            org_key: Organization key.
            project_id: Data platform project id. Optional.
            timeout: Request timeout in seconds.
            max_retries: Maximum retry attempts. Set to 0 to disable.
            retry_backoff_factor: Multiplier for exponential backoff between retries.
                Delay = min(retry_backoff_factor * (2 ** attempt), max_retry_delay).
            max_retry_delay: Maximum delay in seconds between retry attempts.
            record: Whether to record tool execution responses for testing.
            tag: Optional billing tag applied to all tool executions (``tag`` field).
            billing_tag: Optional runtime billing tag (``billing`` field).
                Distinct from :attr:`billing`, the billing API wrapper.
            _app: Internal app identifier. Part of the singleton cache key.
            _session: Internal session identifier. Part of the singleton cache key.
                A UUID v4 is generated when ``None``.
        """
        if base_url is None:
            raise RuntimeError(
                "DeepOriginClient.__init__ requires base_url. Use DeepOriginClient() "
                "for automatic configuration."
            )
        self._base_url = base_url.rstrip("/") + "/"
        self._org_key = org_key
        self._project_id = project_id

        _client = cast(
            Any, self
        )  # ``self`` is ``Self``; wrappers expect ``DeepOriginClient``

        # tools is always available, needed for tools SDK to resolve
        # output schemas
        from deeporigin.platform.tools import Tools

        self.tools = Tools(_client)

        try:
            from deeporigin.platform.clusters import Clusters

            self.clusters = Clusters(_client)
        except ImportError:
            self.clusters = None

        # files is always available
        from deeporigin.platform.files import Files

        self.files = Files(_client)

        try:
            from deeporigin.platform.executions import Executions

            self.executions = Executions(_client)
        except ImportError:
            self.executions = None

        try:
            from deeporigin.platform.user_logs import UserLogs

            self.user_logs = UserLogs(_client)
        except ImportError:
            self.user_logs = None

        try:
            from deeporigin.platform.organizations import Organizations

            self.organizations = Organizations(_client)
        except ImportError:
            self.organizations = None

        try:
            from deeporigin.platform.billing import Billing

            self.billing = Billing(_client)
        except ImportError:
            self.billing = None

        try:
            from deeporigin.platform.entities import Entities

            self.entities = Entities(_client)
        except ImportError:
            self.entities = None

        from deeporigin.platform.results import Results

        self.results = Results(_client)

        try:
            from deeporigin.platform.progress_reports import ProgressReports

            self.progress_reports = ProgressReports(_client)
        except ImportError:
            self.progress_reports = None

        try:
            from deeporigin.platform.projects import Projects

            self.projects = Projects(_client)
        except ImportError:
            self.projects = None

        self.max_retries = max_retries
        self.retryable_status_codes = HTTP_RETRYABLE_STATUS_CODES
        self.retry_backoff_factor = retry_backoff_factor
        self.max_retry_delay = max_retry_delay
        self.record = record
        self.tag = tag
        self.billing_tag = billing_tag
        self._app = _app
        self._session = str(uuid.uuid4()) if _session is None else _session

        self._client = httpx.Client(
            base_url=self._base_url,
            headers={"Accept": "application/json"},
            timeout=timeout,
        )

        if token is None:
            self._token = None
        else:
            self.token = token

        self._finalizer = weakref.finalize(self, self._client.close)

    # -------- Core properties --------

    @property
    def base_url(self) -> str:
        """Get the API base URL.

        Returns:
            The base URL string.
        """
        return self._base_url

    @property
    def org_key(self) -> str:
        """Get the organization key.

        Returns:
            The organization key string.

        Raises:
            DeepOriginException: If org_key is not set.
        """
        if self._org_key is None or self._org_key == "":
            raise DeepOriginException(
                title="Organization Key Required",
                message="The organization key is not set or is empty. Please configure it before using the client, using the `config` module.",
                fix=(
                    "Assign `client.org_key = ...` for this session, or use "
                    "`config.set_org(org_key)` to persist the default organization."
                ),
                level="danger",
            )
        return self._org_key

    @org_key.setter
    def org_key(self, value: str | None) -> None:
        """Set the organization key for subsequent API calls.

        This only updates the client in memory. Use :func:`deeporigin.config.set_org`
        to persist the default organization in ``~/.deeporigin/``.

        Args:
            value: Organization key string, or ``None`` to clear (the getter will
                raise until set to a non-empty string again).
        """
        self._org_key = value

    @property
    def project_id(self) -> str | None:
        """Data platform project id for this client instance.

        Returns:
            Project id string, or ``None`` if no project is selected.
        """
        return self._project_id

    @project_id.setter
    def project_id(self, value: str | None) -> None:
        """Set the active project id.

        Use :func:`deeporigin.projects.load` instead of setting this directly.

        Args:
            value: Project id string, or ``None`` to deselect.
        """
        self._project_id = value

    @property
    def token(self) -> str | None:
        """Get the authentication token.

        Returns:
            The authentication token string, or ``None`` if unset.
        """
        return self._token

    @token.setter
    def token(self, value: str | None) -> None:
        """Set the authentication token and update the Authorization header.

        Args:
            value: The new authentication token, or ``None`` to clear bearer auth.
        """
        self._token = value
        if hasattr(self, "_client"):
            if value is None:
                self._client.headers.pop("Authorization", None)
            else:
                self._client.headers["Authorization"] = f"Bearer {value}"

    @property
    def env(self) -> ENVS:
        """Infer the deployment environment from the base URL.

        Returns:
            One of ``"dev"``, ``"staging"``, ``"local"``, ``"prod"``.
        """
        url = self._base_url
        if "dev" in url:
            return "dev"
        if "staging" in url:
            return "staging"
        if "127.0.0.1" in url or "localhost" in url:
            return "local"
        return "prod"

    def __repr__(self) -> str:
        """Return a string representation of the client.

        Returns:
            A string showing the client's name (from token), org_key, and base_url.
        """
        from deeporigin import auth

        name = "Unknown"
        try:
            if self._token is not None:
                decoded_token = auth.decode_access_token(self._token)
                name = decoded_token.get("name", "Unknown")
        except Exception:
            pass

        repr_str = f"DeepOrigin Platform Client for {name} (org_key={self._org_key}, base_url={self._base_url})"
        if self.tag is not None:
            repr_str += f" (tag={self.tag})"
        if self.billing_tag is not None:
            repr_str += f" (billing_tag={self.billing_tag})"
        return repr_str

    # -------- Factory classmethods --------

    @classmethod
    def from_headers(
        cls,
        headers: Any,
        *,
        _app: str = "python-client",
        _session: str | None = None,
    ) -> Self:
        """Create a client from HTTP request headers.

        Use this inside a served tool handler where the platform injects the
        caller's credentials and routing info as headers.

        Required headers: ``X-Do-Auth-Token``, ``X-Do-Org-Key``, ``X-Do-Base-Url``.
        Optional header: ``X-Do-Project-Id``.

        Header lookup is case-insensitive and supports plain ``dict`` values
        produced from ``dict(request.headers)`` (lowercase keys).

        Args:
            headers: HTTP request headers object (must support ``.get()``).
            _app: Internal app identifier.
            _session: Internal session identifier.

        Returns:
            A configured ``DeepOriginClient`` instance.

        Raises:
            ValueError: If any required header is missing.
        """
        required_keys = [
            "X-Do-Auth-Token",
            "X-Do-Org-Key",
            "X-Do-Base-Url",
        ]
        missing = [k for k in required_keys if not _get_header_value(headers, k)]
        if missing:
            raise ValueError(f"Missing required headers: {', '.join(missing)}")

        base_url = _get_header_value(headers, "X-Do-Base-Url")
        raw_pid = _get_header_value(headers, "X-Do-Project-Id")
        project_id = str(raw_pid).strip() if raw_pid else None

        return cls(
            token=_get_header_value(headers, "X-Do-Auth-Token"),
            org_key=_get_header_value(headers, "X-Do-Org-Key"),
            base_url=base_url,
            project_id=project_id,
            _app=_app,
            _session=_session,
        )

    @classmethod
    def from_env_variables(
        cls,
        *,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_backoff_factor: float = 1.0,
        max_retry_delay: float = 60.0,
        record: bool = False,
        _app: str = "python-client",
        _session: str | None = None,
    ) -> Self:
        """Create a client strictly from OS environment variables.

        Use this inside a provisioned container where the platform injects
        credentials as environment variables. Never falls back to disk config:
        missing variables raise immediately.

        Required variables: ``DO_AUTH_TOKEN``, ``DO_ORG_KEY``.
        ``DO_BASE_URL`` is optional if ``DO_AUTH_TOKEN`` is set — the API URL is
        inferred from the token issuer when ``DO_BASE_URL`` is unset.
        Optional variable: ``DO_PROJECT_ID``.

        Args:
            timeout: Request timeout in seconds.
            max_retries: Maximum retry attempts. Set to 0 to disable.
            retry_backoff_factor: Multiplier for exponential backoff between retries.
            max_retry_delay: Maximum delay in seconds between retry attempts.
            record: Whether to record tool execution responses for testing.
            _app: Internal app identifier.
            _session: Internal session identifier.

        Returns:
            A configured ``DeepOriginClient`` instance.

        Raises:
            ValueError: If any required environment variable is missing.
        """
        token = os.environ.get(ENV_VARIABLES["access_token"])
        org_key = os.environ.get(ENV_VARIABLES["org_key"])
        base_url = os.environ.get(ENV_VARIABLES["base_url"])
        project_id_raw = os.environ.get(ENV_VARIABLES["project_id"])

        missing: list[str] = []
        if not token:
            missing.append(ENV_VARIABLES["access_token"])
        if not org_key:
            missing.append(ENV_VARIABLES["org_key"])
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        if not base_url:
            base_url = _base_url_for_token(token)

        project_id = project_id_raw.strip() if project_id_raw else None

        return cls(
            base_url=base_url,
            token=token,
            org_key=org_key,
            project_id=project_id,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff_factor=retry_backoff_factor,
            max_retry_delay=max_retry_delay,
            record=record,
            _app=_app,
            _session=_session,
        )

    @classmethod
    def from_disk(
        cls,
        env: ENVS | None = None,
        *,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_backoff_factor: float = 1.0,
        max_retry_delay: float = 60.0,
        record: bool = False,
        _app: str = "python-client",
        _session: str | None = None,
    ) -> Self:
        """Create a client from ``~/.deeporigin/`` config files.

        Use this for interactive work in Jupyter notebooks or CLI sessions where
        credentials are stored on disk after running ``deeporigin login``.

        For local development use :meth:`from_local` instead.

        Environment selection order: explicit ``env`` parameter → value in
        ``~/.deeporigin/config.json``.

        Args:
            env: Deployment target (``"prod"``, ``"staging"``, ``"dev"``).
                When ``None``, reads from disk config. ``"local"`` is not
                accepted here — use :meth:`from_local`.
            timeout: Request timeout in seconds.
            max_retries: Maximum retry attempts. Set to 0 to disable.
            retry_backoff_factor: Multiplier for exponential backoff between retries.
            max_retry_delay: Maximum delay in seconds between retry attempts.
            record: Whether to record tool execution responses for testing.
            _app: Internal app identifier.
            _session: Internal session identifier.

        Returns:
            A configured ``DeepOriginClient`` instance.

        Raises:
            ValueError: If the resolved environment is not a valid ``ENVS`` value.
        """
        if env is None:
            env = get_value()["env"] or "prod"

        valid = [e for e in get_args(ENVS) if e != "local"]
        if env not in valid:
            raise ValueError(
                f"Invalid environment: {env!r}. Must be one of: dev, prod, staging. "
                f"For local development use DeepOriginClient.from_local()."
            )

        token = get_token(env=env)
        org_key = get_value()["org_key"]
        base_url = API_ENDPOINT[env]

        return cls(
            base_url=base_url,
            token=token,
            org_key=org_key,
            project_id=None,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff_factor=retry_backoff_factor,
            max_retry_delay=max_retry_delay,
            record=record,
            _app=_app,
            _session=_session,
        )

    @classmethod
    def from_local(
        cls,
        *,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_backoff_factor: float = 1.0,
        max_retry_delay: float = 60.0,
        record: bool = False,
        _app: str = "python-client",
        _session: str | None = None,
    ) -> Self:
        """Create a client for local development.

        Generates a dummy JWT token and points at the local mock server
        (``http://127.0.0.1:4931``). No disk reads, no environment variable
        reads — suitable for unit tests and local stack development.

        Args:
            timeout: Request timeout in seconds.
            max_retries: Maximum retry attempts. Set to 0 to disable.
            retry_backoff_factor: Multiplier for exponential backoff between retries.
            max_retry_delay: Maximum delay in seconds between retry attempts.
            record: Whether to record tool execution responses for testing.
            _app: Internal app identifier.
            _session: Internal session identifier.

        Returns:
            A configured ``DeepOriginClient`` instance pointed at the local mock server.
        """
        return cls(
            base_url=API_ENDPOINT["local"],
            token=_generate_local_token(),
            org_key="deeporigin",
            project_id=None,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff_factor=retry_backoff_factor,
            max_retry_delay=max_retry_delay,
            record=record,
            _app=_app,
            _session=_session,
        )

    # -------- Singleton helpers --------

    @classmethod
    def close_all(cls) -> None:
        """Close all cached client instances and clear the registry.

        This method closes all HTTP connections for cached client instances
        and removes them from the singleton registry. Useful for cleanup or
        when switching between different configurations.
        """
        instances = list(cls._instances.values())
        for inst in instances:
            inst.close()
        cls._instances.clear()

    def check_token(self) -> None:
        """Check if the token is expired."""
        from deeporigin import auth

        if self._token is None:
            raise DeepOriginException(
                title="Authentication Required",
                message="No access token is set on this client.",
                fix=(
                    "Configure credentials via DeepOriginClient(), "
                    "`config.set_org`, or environment variables."
                ),
                level="danger",
            )
        if auth.is_token_expired(self._token):
            raise DeepOriginException(
                title="Token Expired",
                message="Token is expired. Please refer to https://client-docs.deeporigin.io/how-to/auth.html to get a new token.",
                level="danger",
            )

    def health(self) -> dict:
        """Check health of all platform services.

        Calls each service health endpoint and returns a combined response.
        The top-level ``status`` is ``"ok"`` only when every service reports
        ``"ok"``; otherwise it is ``"error"``.

        Returns:
            Dictionary with per-service health and an aggregate ``status``.
        """
        services = {
            "billing": "/billing/health",
            "entities": "/data-platform/health",
            "files": "/files/health",
            "tools": "/tools/health",
        }
        combined: dict[str, Any] = {}
        for name, path in services.items():
            try:
                combined[name] = self.get_json(path)
            except Exception as exc:
                combined[name] = {"status": "error", "error": str(exc)}

        all_ok = all(svc.get("status") == "ok" for svc in combined.values())
        combined["status"] = "ok" if all_ok else "error"
        return combined

    def _detach_from_registry(self) -> None:
        """Remove this instance from the singleton registry.

        Called automatically when the client is closed. Uses the stored cache
        key for O(1) removal.
        """
        key = getattr(self, "_cache_key", None)
        if key is not None and self._instances.get(key) is self:
            self._instances.pop(key, None)
        else:
            for k, inst in list(self._instances.items()):
                if inst is self:
                    self._instances.pop(k, None)
        try:
            del self._cache_key  # type: ignore[attr-defined]
        except AttributeError:
            pass

    # -------- Low-level helpers --------

    def _should_retry(self, error: Exception) -> bool:
        """Determine if a request should be retried based on the error.

        Args:
            error: The exception that occurred.

        Returns:
            True if the request should be retried, False otherwise.
        """
        if self.max_retries == 0:
            return False

        if isinstance(error, (httpx.NetworkError, httpx.TimeoutException)):
            return True

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
        error_message = None
        error_details = None
        try:
            error_data = error.response.json()

            if isinstance(error_data, dict):
                error_message = (
                    error_data.get("message")
                    or error_data.get("error")
                    or error_data.get("detail")
                )
                if "errors" in error_data:
                    error_details = json.dumps(error_data["errors"], indent=2)
            if error_message is None:
                error_message = str(error_data)
        except json.JSONDecodeError:
            try:
                error_message = error.response.text
            except Exception:
                error_message = f"HTTP {error.response.status_code}"

        full_url = self._base_url.rstrip("/") + "/" + path.lstrip("/")

        curl_parts = ["curl", "-X", method.upper()]

        headers = dict(self._client.headers)
        if body is not None and not any(
            key.lower() == "content-type" for key in headers.keys()
        ):
            headers["Content-Type"] = "application/json"

        sanitized_headers = {}
        for header_name, header_value in headers.items():
            if header_name.lower() == "authorization":
                sanitized_headers[header_name] = "Bearer [REDACTED]"
            else:
                sanitized_headers[header_name] = header_value

        for header_name, header_value in sanitized_headers.items():
            escaped_value = str(header_value).replace('"', '\\"')
            curl_parts.extend(["-H", f'"{header_name}: {escaped_value}"'])

        if body is not None:
            body_json = json.dumps(body)
            curl_parts.extend(["-d", f"'{body_json}'"])

        curl_parts.append(f'"{full_url}"')

        curl_command = " \\\n  ".join(curl_parts)

        file_uuid = str(uuid.uuid4())
        filename = f"{file_uuid}.txt"
        filepath = _ensure_do_folder() / filename

        with open(filepath, "w") as f:
            f.write(curl_command)

        message_parts = [
            f"A {method.upper()} request to the platform API failed (HTTP {error.response.status_code}).",
            f"Platform API base URL: {self._base_url}",
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

    def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        """Perform a GET request and raise on error.

        Args:
            path: API endpoint path (relative to base_url).
            **kwargs: Additional arguments passed to httpx.Client.get().

        Returns:
            The HTTP response object.
        """
        self.check_token()

        def request() -> httpx.Response:
            return self._client.get(path, **kwargs)

        return self._retry_request(request, "GET", path, body=None)

    def _post(
        self,
        path: str,
        body: Optional[dict] = None,
        *,
        retry: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        """Perform a POST request and raise on error.

        Args:
            path: API endpoint path (relative to base_url).
            body: JSON data to send in the request body.
            retry: If False, perform a single HTTP attempt (no client-level retries).
                Prefer True for availability-sensitive POSTs (e.g. tool executions).
            **kwargs: Additional arguments passed to httpx.Client.post().

        Returns:
            The HTTP response object.
        """
        self.check_token()

        def request() -> httpx.Response:
            return self._client.post(path, json=body, **kwargs)

        if not retry:
            try:
                response = request()
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                self._handle_request_error("POST", path, e, body=body)

        return self._retry_request(request, "POST", path, body=body)

    def _put(self, path: str, **kwargs: Any) -> httpx.Response:
        """Perform a PUT request and raise on error.

        Args:
            path: API endpoint path (relative to base_url).
            **kwargs: Additional arguments passed to httpx.Client.put().

        Returns:
            The HTTP response object.
        """
        self.check_token()

        def request() -> httpx.Response:
            return self._client.put(path, **kwargs)

        body = kwargs.get("json")
        return self._retry_request(request, "PUT", path, body=body)

    def _patch(
        self,
        path: str,
        *,
        retry: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        """Perform a PATCH request and raise on error.

        Args:
            path: API endpoint path (relative to base_url).
            retry: If False, perform a single HTTP attempt (no client-level retries).
            **kwargs: Additional arguments passed to httpx.Client.patch().

        Returns:
            The HTTP response object.
        """
        self.check_token()

        def request() -> httpx.Response:
            return self._client.patch(path, **kwargs)

        body = kwargs.get("json")
        if not retry:
            try:
                response = request()
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                self._handle_request_error("PATCH", path, e, body=body)

        return self._retry_request(request, "PATCH", path, body=body)

    def _head(self, path: str, **kwargs: Any) -> httpx.Response:
        """Perform a HEAD request and raise on error.

        Args:
            path: API endpoint path (relative to base_url).
            **kwargs: Additional arguments passed to httpx.Client.head().

        Returns:
            The HTTP response object.
        """
        self.check_token()

        def request() -> httpx.Response:
            return self._client.head(path, **kwargs)

        return self._retry_request(request, "HEAD", path, body=None)

    def _delete(self, path: str, **kwargs: Any) -> httpx.Response:
        """Perform a DELETE request and raise on error.

        Args:
            path: API endpoint path (relative to base_url).
            **kwargs: Additional arguments passed to httpx.Client.delete().

        Returns:
            The HTTP response object.
        """
        self.check_token()

        def request() -> httpx.Response:
            return self._client.delete(path, **kwargs)

        body = kwargs.get("json")
        return self._retry_request(request, "DELETE", path, body=body)

    # -------- Convenience wrappers --------

    def get_json(self, path: str, **kwargs: Any) -> Any:
        """Perform a GET request and return the JSON response.

        Args:
            path: API endpoint path (relative to base_url).
            **kwargs: Additional arguments passed to httpx.Client.get().

        Returns:
            The JSON-decoded response body.
        """
        return self._get(path, **kwargs).json()

    def post_json(
        self,
        path: str,
        body: dict[str, Any],
        *,
        retry: bool = True,
        **kwargs: Any,
    ) -> Any:
        """Perform a POST request and return the JSON response.

        Args:
            path: API endpoint path (relative to base_url).
            body: JSON data to send in the request body.
            retry: If False, perform a single HTTP attempt (no client-level retries).
            **kwargs: Additional arguments passed to httpx.Client.post().

        Returns:
            The JSON-decoded response body.
        """
        return self._post(path, body=body, retry=retry, **kwargs).json()

    def delete_json(self, path: str, **kwargs: Any) -> Any:
        """Perform a DELETE request and return the JSON response.

        Args:
            path: API endpoint path (relative to base_url).
            **kwargs: Additional arguments passed to httpx.Client.delete().

        Returns:
            The JSON-decoded response body.
        """
        return self._delete(path, **kwargs).json()

    # -------- Lifecycle --------

    def close(self) -> None:
        """Close the HTTP client connection and remove from registry.

        After calling ``close()``, this instance should not be used for
        further requests.
        """
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

    def __exit__(self, *args: Any) -> None:
        """Exit the context manager and close the client.

        Args:
            *args: Exception information (ignored).
        """
        self.close()
