---
status: accepted
---

# Admet properties come from the live tool definition

A new `Admet` run copies its endpoint list from the
`deeporigin.admet-properties` tool definition (`tools.get` at construct time)
instead of a baked client tuple. Callers trim `properties` on the instance;
the constructor does not take `properties=`. `tool_version` is pinned to the
tool major (`"2"`), not snapped to the fetched definition's full semver.
`from_dto` restores recorded inputs and does not refetch. `duplicate()` of a rehydrated instance fetches
the live enum so the new draft can assign `properties`. If recorded
`properties` were omitted, the draft is filled from that enum.

Baking drifted (`Fu_regression` landed on the tool while the client still had
59 names). Fetching at construct and sending the instance list keeps the CLI
catalog aligned with the definition the user can see. The baked
`ADMET_PROPERTY_NAMES` / `ADMET_PROPERTY_KEYS` constants in
`deeporigin.utils.constants` are removed; callers should read
`Admet(...).properties` instead of importing those names. Pinning the resolved
semver would couple the draft to one patch release; pinning the major keeps
the 2.x input schema (`ligands_file`, project runs) stable while accepting
that construct-time enum and execute-time minor/patch resolution can differ.
