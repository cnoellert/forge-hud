# forge-hud

One shared, dockable HUD rail for FORGE Flame tools.

Any FORGE distro (forge-takes, forge-wireless, …) registers a *section*;
every enabled section renders as one row in a single frameless,
always-on-top, draggable dock:

    ⠿ FORGE ▾
    ● WIRELESS   14 ch · 31 gets
    ● TAKE       comp_v2  GMM_260

The row anatomy is owned by the library so every section reads the same
way: status dot, then the section title as a small muted header in its own
aligned column, then the section's content. Tools supply only the content.

Left of the **FORGE** chip is the drag grip — a painted 2×3 dot grid
(painted, not a font glyph, so it looks the same on every Flame box).
The rail has always dragged from anywhere on itself and the grip narrows
nothing: press anywhere, more than 5px of travel is a drag, a clean
release is a click. The grip rests at the window's own border colour and
brightens under the cursor, so the affordance appears exactly when it is
actionable, and clicking it does nothing at all — it is a handle, not a
button.

Brightness is the whole signal by necessity: **Flame owns the pointer
application-wide**, so per-widget `setCursor()` (an open hand over the
chrome, a pointing hand over the rows) never reaches the screen — verified
live on 2026.2.2. Tooltips are the only second channel available. Don't
re-add cursor handling expecting it to work.

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
    key=my_key,                # optional, 1.7.0+: () -> hashable, polled
    on_tab=my_on_tab,          # optional, 1.8.0+: (tab) -> None, on a tab change
    on_tick=my_on_tick,        # optional, 1.9.0+: () -> None, every heartbeat
)

forge_hud.toggle("wireless")   # menu action; returns the new state
forge_hud.show("wireless")     # enable + surface the dock
forge_hud.hide("wireless")     # disable (dock hides when no sections left)
forge_hud.enabled("wireless")  # -> bool
forge_hud.ensure()             # show the dock if any section is enabled
forge_hud.update()             # refresh row labels (action checkpoints)
forge_hud.reset_position()     # park the rail back at the default corner
```

`register()` is safe at import time (no Qt is touched) and replaces by id,
so module reloads re-register cleanly. `refresh()` returns the row's
**content** as rich text (`html` — no dot, no tool name: the library
renders the dot and the `title` header itself), an optional `tooltip`, an
`alert` flag, and an optional `dot` colour used for the row dot and the
collapsed chip (`alert` alone turns it crimson). `menu()` receives an
empty styled `QMenu` and the Qt modules, and populates it; the library
appends the separator, *Reset HUD position* and the per-section
*Hide … HUD* entry itself. `key()` (optional, **1.7.0+**) names what the
row is *about* — forge-takes passes the current batch group's name — and
must be as cheap as `get_current_tab()`; see *Refresh model*. A consumer
that may meet an older 1.x dock should fall back to registering without
`key` on `TypeError`. `on_tick()` (optional, **1.9.0+**) is called on every
heartbeat, on every tab, whether the dock shows or not - for a section's
own window watching something Flame fires nothing for (forge-streams'
Segment Lens follows the timeline's current segment with it). It keeps
the one-timer rule: no timer of its own, and it must be as cheap as a key,
redrawing only when what it watches moved. Fall back without it on
`TypeError`.

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
- **Screen-aware placement.** The saved position is absolute desktop
  coordinates, so a display that shrinks under the dock — a working- or
  UI-resolution change, a monitor unplugged, Flame moved to a smaller
  screen — used to strand a frameless, title-bar-less window outside
  every screen: invisible, undraggable, recoverable only by editing the
  state file. Every placement now clamps the window fully inside the
  available geometry of whichever screen it most overlaps (nearest one if
  it overlaps none), on restore, on every show, and from the heartbeat
  whenever the set of screen rectangles changes — so the dock walks back
  into view on its own. *Reset HUD position* in any section's popup (and
  `reset_position()`) is the manual way home.
- **Refresh model.** Otherwise timer-free (the crash-#16 rules from
  forge-takes apply throughout: standard widgets only, no custom
  delegates, no event filters). Row labels refresh on mouse-enter, after
  every popup, and whenever a tool calls `update()` from its action
  checkpoints. Flame has no hook for node deletion or graph edits, so
  hover-refresh is the event-driven answer to state that changes behind
  the tools' backs.
- **Keys (1.7.0).** Nor is there a hook for a Batch Group switch, so a
  takes row went on naming the previous group until something else
  redrew it (forge-takes#2). A section may register a `key`: the
  heartbeat reads it on each tick while the dock is visible, beside the
  tab getter, and redraws the rows when any key changes. The key is the
  cheap part; `refresh()` runs only when one actually moved.
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
- **Pen log (1.8.1).** A diagnostic for a Wacom wedge seen on 2027.1: a pen
  click on a FORGE window has left the driver reading every tip press as a
  right click, everywhere, until it was restarted. The rail writes each
  press, release, double-click and tablet press/release it's handed, focus
  coming and going, drags and menus, to `/var/tmp/forge_pen.log` (it
  restarts past 2 MB, keeping the last as `.1`). It is fed from the rail's
  own handlers, with no event filter. `pen_note(source, what, event=None)`
  lets a section's own windows add to the same log; the forge-streams Lens
  does.

## Known consumers

| distro | section | row shows | popup |
| --- | --- | --- | --- |
| forge-wireless ≥ 1.6.0 | `wireless` | channel/get counts + health | channel palette (click = drop a Get), Relink all |
| forge-takes | `takes` | current take in its colour + batch | take switcher tree, Takes Editor… |
