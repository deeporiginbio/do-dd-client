from deeporigin.drug_discovery import PocketFinder


def test_pocket_finder_quote_lv1(registered_protein):
    """test that we can get a quote for the pocket finder"""
    pf = PocketFinder(protein=registered_protein)
    pf.quote()
    assert pf.estimate is not None, "Estimate should be set"
    assert pf.cost is None, (
        "Cost should be None because the pocket finder is not run yet"
    )


def test_pocket_finder_run_lv2(registered_protein):
    """test that we can run the pocket finder"""
    pf = PocketFinder(
        protein=registered_protein,
        pocket_count=1,
        pocket_min_size=30,
    )
    pockets = pf.run()
    assert len(pockets) > 0, "Expected at least one pocket"
    assert pf.cost is not None, "Cost should be set"
    assert pf.id is not None, "ID should be set"
    assert pf.status is not None, "Status should be set"
    assert pf.status == "Completed", "Status should be Completed"
