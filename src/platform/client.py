# deeporigin/client.py
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import weakref

import httpx

from deeporigin.auth import get_tokens
from deeporigin.config import get_value
from deeporigin.platform.clusters import Clusters
from deeporigin.platform.files import Files
from deeporigin.platform.functions import Functions

# Import Tools - safe because tools.py uses TYPE_CHECKING for DeepOriginClient
from deeporigin.platform.tools import Tools
from deeporigin.utils.constants import API_ENDPOINT, ENVS


class DeepOriginClient:
    """
    Minimal synchronous API client with built-in singleton cache.
    Use `DeepOriginClient.get(token=..., org_key=...)` to reuse one
    connection pool across notebook cells.
    """

    # class-level registry for singleton instances
    _instances: Dict[Tuple[str, str, str], "DeepOriginClient"] = {}

    def __init__(
        self,
        token: str | None = None,
        org_key: str | None = None,
        env: ENVS | None = None,
        base_url: str | None = None,
        timeout: float = 10.0,
        http2: bool = False,  # often faster off for simple REST
    ):
        if token is None:
            tokens = get_tokens()
            token = tokens["access"]

        if org_key is None:
            org_key = get_value()["org_key"]

        if env is None and base_url is None:
            env = get_value()["env"]
            base_url = API_ENDPOINT[env]

        elif env is not None and base_url is None:
            # get the base url from the environment
            base_url = API_ENDPOINT[env]

        self.token = token

        self.org_key = org_key
        self.base_url = base_url.rstrip("/") + "/"

        self.tools = Tools(self)
        self.functions = Functions(self)
        self.clusters = Clusters(self)
        self.files = Files(self)

        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            },
            timeout=timeout,
            http2=http2,
        )

        # ensure sockets close if GC happens
        self._finalizer = weakref.finalize(self, self._client.close)

    def __repr__(self):
        return f"DeepOrigin Platform Client(token={self.token[:5]}..., org_key={self.org_key}, base_url={self.base_url})"

    # -------- Singleton helpers --------
    @classmethod
    def get(
        cls,
        *,
        token: str,
        org_key: str,
        base_url: str = "https://api.deeporigin.io/",
        timeout: float = 10.0,
        http2: bool = False,
        replace: bool = False,
    ) -> "DeepOriginClient":
        """
        Get a cached client for (base_url, token, org_key). If `replace=True`,
        closes and recreates the cached instance.
        """
        key = (base_url.rstrip("/") + "/", token, org_key)
        if replace and key in cls._instances:
            try:
                cls._instances[key].close()
            finally:
                cls._instances.pop(key, None)
        if key not in cls._instances:
            cls._instances[key] = cls(
                token=token,
                org_key=org_key,
                base_url=base_url,
                timeout=timeout,
                http2=http2,
            )
        return cls._instances[key]

    @classmethod
    def close_all(cls) -> None:
        for inst in cls._instances.values():
            inst.close()
        cls._instances.clear()

    # Removing from registry when explicitly closed
    def _detach_from_registry(self) -> None:
        key = (self.base_url, self.token, self.org_key)
        if key in self._instances and self._instances[key] is self:
            self._instances.pop(key, None)

    # -------- Low-level helpers --------
    def _get(self, path: str, **kwargs) -> httpx.Response:
        resp = self._client.get(path, **kwargs)
        resp.raise_for_status()
        return resp

    def _post(self, path: str, json: Optional[dict] = None, **kwargs) -> httpx.Response:
        resp = self._client.post(path, json=json, **kwargs)
        resp.raise_for_status()
        return resp

    def _put(self, path: str, **kwargs) -> httpx.Response:
        resp = self._client.put(path, **kwargs)
        resp.raise_for_status()
        return resp

    def _delete(self, path: str, **kwargs) -> httpx.Response:
        resp = self._client.delete(path, **kwargs)
        resp.raise_for_status()
        return resp

    # -------- Convenience wrappers --------
    def get_json(self, path: str, **kwargs) -> Any:
        return self._get(path, **kwargs).json()

    def post_json(self, path: str, json: dict[str, Any], **kwargs) -> Any:
        return self._post(path, json=json, **kwargs).json()

    # -------- tools API methods --------
    def list_tools(self) -> Any:
        return self.get_json("/tools/protected/tools/definitions")

    def list_executions(self, limit: int = 100) -> Any:
        return self.get_json("/tools/executions", params={"limit": limit})

    # -------- Lifecycle --------
    def close(self) -> None:
        # close transport and remove from registry
        try:
            self._client.close()
        finally:
            self._detach_from_registry()

    def __enter__(self) -> "DeepOriginClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()
