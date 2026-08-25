---
status: accepted
---

# Admet properties come from the live tool definition

A new `Admet` run copies its endpoint list from the
`deeporigin.admet-properties` tool definition (`tools.get` at construct time)
instead of a baked client tuple. Callers trim `properties` on the instance;
the constructor does not take `properties=`. `tool_version` stays `"latest"`
(not snapped to the fetched definition version). `from_dto` restores recorded
inputs and does not refetch. `duplicate()` of a rehydrated instance fetches
the live enum so the new draft can assign `properties`.

Baking drifted (`Fu_regression` landed on the tool while the client still had
59 names). Fetching at construct and sending the instance list keeps the CLI
catalog aligned with the definition the user can see. Pinning the resolved
semver would couple the draft to one version; leaving `"latest"` matches the
existing tool pin and accepts that construct-time enum and execute-time
resolution can differ.
