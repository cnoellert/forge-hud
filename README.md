# forge-hud

One shared, dockable HUD rail for FORGE Flame tools.

Any FORGE distro (forge-takes, forge-wireless, …) registers a *section*;
every enabled section renders as one row in a single frameless,
always-on-top, draggable dock:

    FORGE ▾
    ● WIRELESS   14 ch · 31 gets
    ● TAKE       comp_v2  GMM_260

The row anatomy is owned by the library so every section reads the same
way: status dot, then the section title as a small muted header in its own
aligned column, then the section's content. Tools supply only the content.

Clicking a row opens that section's own popup menu — the channel palette
for wireless, the take switcher for takes — built fresh by the owning tool
on every click, so it can never go stale. Clicking the **FORGE** chip
collapses the rail to just the chip plus one status dot per section
(each in the colour the section reports — crimson means trouble), so a
collapsed dock still shows health at a glance.

## Install

Drop `forge_hud.py` into the same Flame python hooks path as the FORGE
tools that use it, e.g. `/opt/Autodesk/shared/python/`. Distros import it
guarded: where it is missing, their HUD is simply unavailable and
everything else works.

## API

```python
import forge_hud

forge_hud.register(
    "wireless",                # stable section id
    title="Wireless",          # used in "Hide Wireless HUD"
    refresh=my_refresh,        # () -> {"html": …, "tooltip": …,
                               #        "alert": bool, "dot": "#hex"}
    menu=my_menu,              # (QMenu, (QtCore, QtGui, QtWidgets)) -> None
    default_enabled=False,     # first-run state (per-user file wins later)
)

forge_hud.toggle("wireless")   # menu action; returns the new state
forge_hud.show("wireless")     # enable + surface the dock
forge_hud.hide("wireless")     # disable (dock hides when no sections left)
forge_hud.enabled("wireless")  # -> bool
forge_hud.ensure()             # show the dock if any section is enabled
forge_hud.update()             # refresh row labels (action checkpoints)
```

`register()` is safe at import time (no Qt is touched) and replaces by id,
so module reloads re-register cleanly. `refresh()` returns the row's
**content** as rich text (`html` — no dot, no tool name: the library
renders the dot and the `title` header itself), an optional `tooltip`, an
`alert` flag, and an optional `dot` colour used for the row dot and the
collapsed chip (`alert` alone turns it crimson). `menu()` receives an
empty styled `QMenu` and the Qt modules, and populates it; the library
appends the separator and the per-section *Hide … HUD* entry itself.

## Behaviour

- **Drag** anywhere to move the dock; the OS-native `startSystemMove()`
  does the work (reliable for frameless windows on every platform), with
  a manual-move fallback. Position persists per user.
- **Refresh model — no `QTimer`, ever** (the crash-#16 rules from
  forge-takes apply throughout: standard widgets only, no custom
  delegates, no event filters). Row labels refresh on mouse-enter, after
  every popup, and whenever a tool calls `update()` from its action
  checkpoints. Flame has no hook for node deletion or graph edits, so
  hover-refresh is the event-driven answer to state that changes behind
  the tools' backs.
- **Reload safety.** The registry, dock window and state are parked on the
  `QApplication` instance, which survives module reloads. A hook rescan
  that reloads `forge_hud` adopts the parked state, closes the old window
  (its methods belong to the old module object) and rebuilds with the new
  code — no zombie pill, no lost registrations.
- **State** — position, collapsed, per-section enabled — persists in
  `~/.forge_hud.json`.

## Known consumers

| distro | section | row shows | popup |
| --- | --- | --- | --- |
| forge-wireless ≥ 1.6.0 | `wireless` | channel/get counts + health | channel palette (click = drop a Get), Relink all |
| forge-takes | `takes` | current take in its colour + batch | take switcher tree, Takes Editor… |
