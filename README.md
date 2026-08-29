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
tools that use it, e.g. `/opt/Autodesk/shared/python/`, then rescan
python hooks in Flame (`Ctrl+Shift+P+H`, or restart). One file, no other
dependencies. Distros import it guarded: where it is missing, their HUD
is simply unavailable and everything else works. The forge-takes
installer can deploy it for you (`python3 scripts/install_hook.py
--with-hud`), and never downgrades an existing copy — keep that rule if
you script your own deployment, since several FORGE tools share the one
file.

Consumers pin the **major** version: this file must bump to 2.x if the
`register/toggle/show/hide/enabled/ensure/update` contract ever breaks,
and consumers treat an incompatible major exactly like absence.

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

- **Tab-aware.** Each section declares the Flame tabs it belongs to
  (`tabs=("Batch",)` by default; falsy = all). The dock hides itself when
  the current tab matches no enabled section and reappears on return —
  a Batch HUD has no business floating over the Timeline. Flame emits
  **no event** on a tab switch — no hook exists, and the custom-drawn tab
  bar produces zero Qt focus traffic (verified live with counters on
  `focusChanged`/`focusObjectChanged`/`focusWindowChanged`) — so the
  watcher is a 600 ms heartbeat polling `flame.get_current_tab()` (a
  trivial getter). This is the **one sanctioned `QTimer`** in the FORGE
  HUD family: the crash-catalog hazard is timers firing into closing
  dialogs, and this one is parented to the session-lived dock, does a
  guarded getter-and-compare per tick, stops itself when orphaned, and is
  stopped before a reload swaps the dock. If it ever dies, the action
  checkpoints still re-apply the context — lazy hiding, never breakage.
- **Drag** anywhere to move the dock; the OS-native `startSystemMove()`
  does the work (reliable for frameless windows on every platform), with
  a manual-move fallback. Position persists per user.
- **Refresh model.** Otherwise timer-free (the crash-#16 rules from
  forge-takes apply throughout: standard widgets only, no custom
  delegates, no event filters). Row labels refresh on mouse-enter, after
  every popup, and whenever a tool calls `update()` from its action
  checkpoints. Flame has no hook for node deletion or graph edits, so
  hover-refresh is the event-driven answer to state that changes behind
  the tools' backs.
- **Reload safety.** The registry, dock reference and heartbeat handle are
  anchored on `builtins` — deliberately **not** on the `QApplication`
  instance: PySide can garbage-collect the Python wrapper around the C++
  app and mint a fresh one, silently dropping dynamic attributes (and the
  registry with them — seen live). A hook rescan that reloads `forge_hud`
  adopts the anchored state, stops the old heartbeat, closes the old
  window (its methods belong to the old module object) and rebuilds with
  the new code — no zombie pill, no lost registrations.
- **State** — position, collapsed, per-section enabled — persists in
  `~/.forge_hud.json`.

## Known consumers

| distro | section | row shows | popup |
| --- | --- | --- | --- |
| forge-wireless ≥ 1.6.0 | `wireless` | channel/get counts + health | channel palette (click = drop a Get), Relink all |
| forge-takes | `takes` | current take in its colour + batch | take switcher tree, Takes Editor… |
