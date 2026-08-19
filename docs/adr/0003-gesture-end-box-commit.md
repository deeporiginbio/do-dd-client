---
status: accepted
---

# Gesture-end box commit (no Apply button)

DDOS-6934/6935 put an **Apply to notebook** button in the SDK iframe HTML as a
second gate after molstar rotation. Molstar `onDockingBoxChange` already fires
on slider release, drag end, and reset — the same moment Apply used to post
`rotation_deg` to Python. The extra click was the ugly UX.

Interactive `show_box` now treats that gesture-end as a **box commit**: the
kernel writes **session rotation** when `rotationDeg` actually changed. A thin
overlay shows `Synced rotation_deg=…` (and Comm errors) because the Jupyter
bridge can fail. Printed cell output stays frozen until re-run.

Rejected: per-frame sync while dragging (Comm spam, half-drag into `run()`);
keeping Apply; persisting center/size on Pocket or as session state.
