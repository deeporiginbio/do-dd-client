"""End-to-end check that ``client.tag`` propagates to billing usage rows."""

import uuid

import pytest

from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


@pytest.mark.skip(reason="Temporarily skipped; fix later")
def test_billing_tag_end_to_end_lv2(client: DeepOriginClient):
    """Run a few molprops tool executions with a unique tag and check billing usage.

    Compares the sum of ``priceTotal`` values returned by ``executions.create``
    against the per-tag totals reported by ``billing.get_usage_by_tag``.
    """

    tag = str(uuid.uuid4())

    if client.env == "local":
        pytest.skip("Can't run this test on local")
    client.tag = tag

    client_total_cost = 0.0
    for _ in range(3):
        response = client.executions.create(
            tool_key="deeporigin.mol-props-logd",
            tool_version=TOOL_KEYS_AND_VERSIONS["mol_props"]["tool_version"],
            data={
                "inputs": {
                    "ligands": [
                        {
                            "id": "0",
                            "smiles": (
                                "O=c1c(Oc2ccc(F)cc2F)cc2cnc(NC3CCOCC3)nc2n1C[C@H](O)CO"
                            ),
                        }
                    ],
                },
                "outputs": {},
                "metadata": {},
                "sync": True,
            },
        )

        client_total_cost += response["quotationResult"]["successfulQuotations"][0][
            "priceTotal"
        ]

    response = client.billing.get_usage_by_tag(tag=tag)
    items = response["items"]
    platform_total_cost = sum(item["total_cost"] for item in items)
    assert platform_total_cost == client_total_cost, (
        f"Client and platform total costs should match, "
        f"but platform reports {platform_total_cost} "
        f"and client reports {client_total_cost}"
    )
