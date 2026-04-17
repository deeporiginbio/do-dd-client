"""Functions API wrapper for DeepOriginClient."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from deeporigin.exceptions import DeepOriginException
from deeporigin.utils.constants import FUNCTION_RUN_POST_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


class Functions:
    """Functions API wrapper.

    Provides access to functions-related endpoints through the DeepOriginClient.
    """

    def __init__(self, client: DeepOriginClient) -> None:
        """Initialize Functions wrapper.

        Args:
            client: The DeepOriginClient instance to use for API calls.
        """
        self._c = client
        self._definitions: list[dict] | None = None

    def list(self) -> list[dict]:
        """Get all function definitions.

        The result is cached per instance after the first call.

        Returns:
            List of function definition dictionaries.
        """
        if self._definitions is None:
            self._definitions = self._c.get_json(
                "/tools/protected/functions/definitions"
            )
        return self._definitions

    def run(
        self,
        *,
        key: str,
        params: dict,
        version: str | None = None,
        cluster_id: str | None = None,
        tag: str | None = None,
        quote: bool = False,
    ) -> dict:
        """Run a function.

        Args:
            key: Key of the function to run.
            params: Function execution parameters (sent in the request body as
                ``inputs``, matching ``FunctionExecutionParams`` in tools-service).
            version: Version of the function to run. If None, runs the latest
                enabled version.
            cluster_id: Cluster ID to run the function on. If None, uses the
                default cluster ID (first non-dev cluster, cached).
            tag: Optional tag for the execution.
            quote: Whether to request a quote instead of running the function.

        Note:
            If :attr:`~deeporigin.platform.client.DeepOriginClient.project_id` is
            set on the client, it is sent in the JSON body as ``projectId``
            (``FunctionExecutionParams`` in tools-service).

            The underlying HTTP client uses
            :data:`~deeporigin.utils.constants.FUNCTION_RUN_POST_TIMEOUT_SECONDS`
            (600s) for this request so long-running synchronous runs are not cut
            off by the default API timeout.

        Returns:
            Dictionary containing the execution response from the API.
        """
        if cluster_id is None:
            cluster_id = self._c.clusters.get_default_cluster_id()

        # Use client's default tag if tag parameter is None
        if tag is None:
            tag = self._c.tag

        body: dict[str, dict | Any] = {
            "inputs": params,
            "clusterId": cluster_id,
        }
        if tag is not None:
            body["tag"] = tag

        if quote:
            body["approveAmount"] = 0

        # functions need a longer timeout than default API calls (see FUNCTION_RUN_POST_TIMEOUT_SECONDS)
        original_timeout = self._c._client.timeout
        self._c._client.timeout = FUNCTION_RUN_POST_TIMEOUT_SECONDS

        # Build endpoint URL based on whether version is provided
        if version is None:
            endpoint = f"/tools/{self._c.org_key}/functions/{key}"
            check_version = "latest"
        else:
            endpoint = f"/tools/{self._c.org_key}/functions/{key}/{version}"
            check_version = version

        body["app"] = self._c._app
        body["session"] = self._c._session

        proj_id = self._c.project_id
        if proj_id is not None:
            body["projectId"] = proj_id

        response = self._c.post_json(
            endpoint,
            body=body,
            retry=False,
        )
        self._c._client.timeout = original_timeout

        _check_response(response, key, check_version, quote)

        if self._c.record:
            import json
            from pathlib import Path

            from deeporigin.utils.hashing import hash_dict, normalize_function_body

            normalized_body = normalize_function_body(body)
            body_hash = hash_dict(normalized_body)

            # Write response to fixture file for testing
            fixture_path = (
                Path(__file__).parent.parent.parent
                / "tests"
                / "fixtures"
                / "function-runs"
                / key
                / f"{body_hash}.json"
            )
            fixture_path.parent.mkdir(parents=True, exist_ok=True)
            with open(fixture_path, "w") as f:
                json.dump(response, f, indent=4)

        return response


def _check_response(
    response: dict,
    key: str,
    version: str,
    quote: bool,
) -> None:
    if "quotationResult" in response and (
        response["quotationResult"]["anyFailed"] or response["status"] == "NotApproved"
    ):
        raise DeepOriginException(
            title=f"Failed to run function: {key}/{version}",
            message="Failed to run function. This function run was not approved. ",
            fix="Please contact support at https://help.deeporigin.com.",
        ) from None

    # Get cost from quotationResult if available, otherwise use None
    cost = None
    if (
        "quotationResult" in response
        and "successfulQuotations" in response["quotationResult"]
    ):
        successful_quotations = response["quotationResult"]["successfulQuotations"]
        if successful_quotations and len(successful_quotations) > 0:
            cost = successful_quotations[0].get("priceTotal")

    if not quote:
        if response["status"] == "Approved":
            cost_msg = (
                f"Check that the approveAmount is set to a non-zero value greater than ${cost}. "
                if cost is not None
                else ""
            )
            raise DeepOriginException(
                title=f"Failed to run function: {key}/{version}",
                message="Failed to run function. Function did not succeed.",
                fix=f"{cost_msg}Otherwise, Please contact support at https://help.deeporigin.com.",
            ) from None

        # we expect a functionOutputs key in the response
        if "functionOutputs" not in response:
            cost_msg = (
                f"Check that the approveAmount is set to a non-zero value greater than ${cost}. "
                if cost is not None
                else ""
            )
            raise DeepOriginException(
                title=f"Failed to run function: {key}/{version}",
                message="Failed to run function. No functionOutputs key in response.",
                fix=cost_msg,
            ) from None

        # the only valid status can be Completed
        if response["status"] != "Completed":
            raise DeepOriginException(
                title=f"Failed to run function: {key}/{version}",
                message="Failed to run function. Function did not succeed.",
                fix="Please contact support at https://help.deeporigin.com.",
            ) from None
