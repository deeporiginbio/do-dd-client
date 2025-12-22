"""Functions API wrapper for DeepOriginClient."""

from __future__ import annotations

from typing import TYPE_CHECKING

from deeporigin.exceptions import DeepOriginException

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

    def list(self) -> list[dict]:
        """Get all function definitions.

        Returns:
            List of function definition dictionaries.
        """
        return self._c.get_json("/tools/protected/functions/definitions")

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
            params: Function execution parameters.
            version: Version of the function to run. If None, runs the latest
                enabled version.
            cluster_id: Cluster ID to run the function on. If None, uses the
                default cluster ID (first non-dev cluster, cached).
            tag: Optional tag for the execution.
            quote: Whether to request a quote instead of running the function.

        Returns:
            Dictionary containing the execution response from the API.
        """
        if cluster_id is None:
            cluster_id = self._c.clusters.get_default_cluster_id()

        body: dict[str, dict | str] = {
            "params": params,
            "inputs": params,  # we're sending both params and inputs because the APIs across dev/staging/prod are different
            "clusterId": cluster_id,
        }
        if tag is not None:
            body["tag"] = tag

        if quote:
            body["approveAmount"] = 0

        # functions need a longer timeout
        original_timeout = self._c._client.timeout
        self._c._client.timeout = 600

        # Build endpoint URL based on whether version is provided
        if version is None:
            endpoint = f"/tools/{self._c.org_key}/functions/{key}"
            check_version = "latest"
        else:
            endpoint = f"/tools/{self._c.org_key}/functions/{key}/{version}"
            check_version = version

        response = self._c.post_json(
            endpoint,
            body=body,
        )
        self._c._client.timeout = original_timeout

        _check_response(response, key, check_version, quote)

        if self._c.record:
            import json
            from pathlib import Path

            from deeporigin.utils.core import hash_dict

            # Hash the request body to create a unique filename
            # Normalize body by excluding environment-specific fields (clusterId, tag)
            # params and inputs are the same, so just use inputs for hashing
            normalized_body = {
                "inputs": body.get("inputs", body.get("params", {})),
            }
            if "approveAmount" in body:
                normalized_body["approveAmount"] = body["approveAmount"]
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
