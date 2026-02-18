Implementation Status vs. Agreed-On Plan

## Desired API interface for running `protein.dock()` with quoting

```Python
results = protein.dock(ligand=ligand, quote=True)

results.poses # None
results.estimate # object -- includes dollar estimate, free actions, etc.


results = protein.dock(ligand=ligand, quote=False)

# oneliner if you don't care about cost
poses = protein.dock(ligand=ligand, quote=False).poses

results.poses
results.cost # object

# i want to use up to $100
results = protein.dock(ligand=ligand, max_cost=Cost(100))

# i want to use up to 5 docking actions
results = protein.dock(ligand=ligand, max_cost=Cost({"DO_DOCK": 5}))

# use 1 free action and $100
results = protein.dock(ligand=ligand, max_cost=Cost(100, {"DO_DOCK": 1}))
```

## What's NOT implemented (vs. the agreed-on plan)

1. Cost class — Does NOT exist
The proposal describes:
results = protein.dock(ligand=ligand, max_cost=Cost(100))
results = protein.dock(ligand=ligand, max_cost=Cost({"DO_DOCK": 5}))
results = protein.dock(ligand=ligand, max_cost=Cost(100, {"DO_DOCK": 1}))
There is no Cost class anywhere in the codebase. No max_cost parameter on any method.

2. max_cost parameter — Does NOT exist
None of the run() methods accept a max_cost parameter. The only cost control is through approve_amount: Optional[int] (on Docking/ABFE), which is a raw integer dollar amount passed directly as approveAmount in
the API payload. There's no support for action-based cost limits like Cost({"DO_DOCK": 5}).

3. results.estimate / results.cost properties — Do NOT exist on the result object
The proposal describes:
results = protein.dock(ligand=ligand, quote=True)
results.estimate  # object -- includes dollar estimate, free actions, etc.
The current implementation returns a JobList (for Docking/ABFE tools) or raw dict (for functions like pocket finder). There is no .estimate or .cost property on Job/JobList. The cost/quote data is buried inside
job._attributes["quotationResult"] and is only surfaced in the HTML visualization widget, not as a clean Python property.

4. results.poses returning None when quote=True — Not applicable
Docking.run(quote=True) returns a JobList of "Quoted" jobs. To get poses you'd call docking.get_results() separately — the proposal's results.poses pattern (where a single return object has both .poses and
.estimate) is not implemented.

5. protein.dock() doesn't support quoting — Different API surface
The Protein.dock() method (protein.py:271-376) is a local/synchronous docking function that returns a LigandSet directly. It does not have quote or max_cost parameters and doesn't use the billing system at all.
The quote=True flow only exists on the Docking class (accessible via complex.docking.run(quote=True)), not on protein.dock().


---
Summary Table

┌────────────────────────────────────┬─────────────────┬──────────────────────────────────────────────────────────────────────┐
│       Agreed-on plan feature       │     Status      │                                Notes                                 │
├────────────────────────────────────┼─────────────────┼──────────────────────────────────────────────────────────────────────┤
│ quote=True parameter               │ Implemented     │ On Docking, ABFE, pocket finder, protonation                         │
├────────────────────────────────────┼─────────────────┼──────────────────────────────────────────────────────────────────────┤
│ results.estimate property          │ Not implemented │ Cost data only in _attributes["quotationResult"], rendered in widget │
├────────────────────────────────────┼─────────────────┼──────────────────────────────────────────────────────────────────────┤
│ results.poses / results.cost       │ Not implemented │ No unified result object with both data and cost                     │
├────────────────────────────────────┼─────────────────┼──────────────────────────────────────────────────────────────────────┤
│ job.confirm()                      │ Implemented     │ Works on Job and JobList                                             │
├────────────────────────────────────┼─────────────────┼──────────────────────────────────────────────────────────────────────┤
│ job.cancel()                       │ Implemented     │ Works on Job and JobList                                             │
├────────────────────────────────────┼─────────────────┼──────────────────────────────────────────────────────────────────────┤
│ max_cost=Cost(100)                 │ Not implemented │ No Cost class, no max_cost param                                     │
├────────────────────────────────────┼─────────────────┼──────────────────────────────────────────────────────────────────────┤
│ max_cost=Cost({"DO_DOCK": 5})      │ Not implemented │ No action-based cost limits                                          │
├────────────────────────────────────┼─────────────────┼──────────────────────────────────────────────────────────────────────┤
│ max_cost=Cost(100, {"DO_DOCK": 1}) │ Not implemented │ No mixed cost limits                                                 │
├────────────────────────────────────┼─────────────────┼──────────────────────────────────────────────────────────────────────┤
│ Billing in Job widget              │ Implemented     │ Billing tab with quotationResult + billingTransaction                │
├────────────────────────────────────┼─────────────────┼──────────────────────────────────────────────────────────────────────┤
│ protein.dock(quote=...)            │ Not implemented │ protein.dock() is a different, local API without billing             |
└────────────────────────────────────┴─────────────────┴──────────────────────────────────────────────────────────────────────┘

The core quoting flow (quote=True → Quoted status → confirm()) is fully working for Docking and ABFE. The main gaps are: no Cost class, no max_cost parameter, no .estimate/.cost properties on the result, and
