import uuid

import pytest

from deeporigin.platform.client import DeepOriginClient


def test_billing_tag_end_to_end_lv2():
    """Test that the billing tag end to end works

    we do so by running a few functions with some unique tag, and then comparing our estimate of cost vs what was reported by the platform."""

    tag = str(uuid.uuid4())
    client = DeepOriginClient.get()

    if client.env == "local":
        # can't run on local, so skip
        pytest.skip("Can't run this test on local")
    client.tag = tag

    # first, run a function a few times with the tag
    client_total_cost = 0
    for _ in range(3):
        response = client.functions.run(
            key="deeporigin.mol-props-logd",
            params={
                "smiles_list": ["O=c1c(Oc2ccc(F)cc2F)cc2cnc(NC3CCOCC3)nc2n1C[C@H](O)CO"]
            },
        )

        client_total_cost += response["quotationResult"]["successfulQuotations"][0][
            "priceTotal"
        ]

    response = client.billing.get_usage_by_tag(tag=tag)
    items = response["items"]
    platform_total_cost = sum(item["total_cost"] for item in items)
    assert platform_total_cost == client_total_cost, (
        f"Client and platform total costs should match, but platform reports {platform_total_cost} and client reports {client_total_cost}"
    )
