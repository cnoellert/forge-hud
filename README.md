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
forge_hud.listen("lens", fn)   # 1.10.0+: fn(tab) on every heartbeat, rail or not
forge_hud.unlisten("lens")     # remove it; the heartbeat stops when unwanted
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

`listen(cid, fn)` (**1.10.0+**) adds a heartbeat client that is *not* a
section: it has no row and no enabled state, and `fn(tab)` is called on
every heartbeat with the current Flame tab, whether or not any rail row is
enabled. It exists for the one Lens (forge-hud#1), a window that must
follow the timeline with every row hidden. Same rules as `on_tick`: as
cheap as a key, no I/O, guarded. It replaces by id, is safe at import time
(the heartbeat starts on the next idle event), and must be called from
Flame's thread. A consumer meeting an older 1.x checks
`hasattr(forge_hud, "listen")`.

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
  dialogs, and this one is parented to the session-lived `QApplication`
  (the dock, before 1.10), does a guarded getter-and-compare per tick,
  stops itself when orphaned, and is stopped before a reload swaps the
  module. If it ever dies, the action
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

- **Rows on one tab only (1.9.1).** A row the current tab hides is not
  refreshed, its key is not read, and the folded rail shows no dot for it:
  on the Timeline the Batch rows were read on every redraw, and folded,
  the rail showed a dot for each. The heartbeat also walks a shown dock
  back onto its screen when the window system has parked it part off one
  with no move of ours (seen on 2027.1: at y −20 on a saved y 0, its top
  clipped).
- **The heartbeat outlives the rail (1.10.0).** Up to 1.9 the heartbeat
  lived on the dock, and the dock is only built when a rail row is
  enabled, so a window following the timeline (the one Lens) got no ticks
  with every row hidden. It now belongs to the session: parented to the
  `QApplication`, its handle anchored on `builtins`, running while the
  dock or any `listen()` client exists and stopping itself when neither
  does. Still the one sanctioned `QTimer`, and nothing changes for the
  rail. A reload stops the old heartbeat (or a ≤ 1.9 dock's) and starts
  one with the new code.
- **One Lens… on every row's menu (1.11.0).** When `forge_lens` is
  installed beside it, the footer every section's popup shares offers
  *One Lens…* (or *Close the Lens* while it's open), done on the idle
  queue. With forge_lens's own *FORGE › One Lens…* on Flame's main menu,
  it is the family's opener; a distro's own entry steps aside when
  `forge_lens.opener_installed()` says so.

## The one Lens (`forge_lens.py`, 0.7.4)

A second module beside the rail, for forge-hud#1: **one window that each
distro registers *areas* into** — Takes (forge-takes), Versions and Depends
(forge-streams), later the Cut and the Batch tab's lenses. Install it beside
`forge_hud.py` the same way; it needs forge_hud ≥ 1.10 for its heartbeat
(without one it still draws, and Refresh works, but it doesn't follow the
timeline). Open it from **FORGE › One Lens…** on Flame's main menu (live on
the Lens's tabs) or **One Lens…** at the foot of any rail row's menu
(forge_hud ≥ 1.11).

The window owns what the areas share, once:

- **The subject.** The last thing the artist did wins: the pin; a
  selection; a segment clicked in the timeline, until the playhead moves;
  else the playhead's top *picture* from the **focused track**
  (`primary_track`) down, tracks above ignored, as Flame's player sees it (a
  gap that only carries an effect is an adjustment layer — the subject only
  when selected or alone). Nothing at or below the focus is nothing.
  Read on the heartbeat from a handful of getters; the cut is walked only on
  a click, a sequence change, a focus on another version, or Refresh. Every area gets it as a `Ctx`: `segments`,
  `primary`, `source`, `over` (what is stacked over it), `visible`,
  `settled` (same subject, playhead still, two beats running), `playing`, `frame`, `tags`, and
  the cut, keyed exactly as forge-takes' `shot_keys` / forge-streams'
  `posting._keyed`, named by forge-takes' `segment_label` rule
  (`GMM_430 · V2` when a name repeats).
- **The spine.** The cut, small, one painter: take colours fill (from the
  areas' overlays), tones never do; a preview's marks fill, outline, dash or
  dim the rest, with a caption under it. An overlay's `dim_rest` is a standing
  filter: its shots stay lit, the rest draw at 0.22, the subject keeps its
  outline, a preview takes over while hovered, and `Mark(None, None, "dim_rest")`
  dims them all. `OLD_LOOK_COLOUR` is the reserved fill for a segment on an old
  look; no take can wear it. Sized once per subject to the cut
  plus every area's `extent`, so a preview never grows it. Two ways to
  move in time: the playhead's line (and the tab on it) drags to scrub; a
  click on a segment puts the playhead on its first frame and pins the Lens
  there. Nothing moves on the press; Flame is moved on the idle queue.
- **The Effects tab.** Flame's timeline reads nothing there, so the Lens holds
  the cut it walked before the switch, and the segment selected in Effects is the
  subject, over a pin, following you if the playbar takes you to another, until
  you return. That's the best guess at the one open, not proof: Flame can open
  another effect without the selection moving, so never write from it. It shares
  the Timeline's place. The
  spine shows the cut but moves nothing, with no playhead line, and `ctx.frame`
  is None. An area joins with `"Effects"` in its `tabs`, and reads the sequence
  from `current_sequence()`, not `flame.timeline.clip`.
- **The window.** forge-streams' `LensWindow` chrome, moved here: a
  frameless `Qt.Tool`, dragged by its header, sized by outline grips applied
  on release, narrow or wide, each placed where it was last left; hidden
  off its tabs and back; off the keyboard; areas stacked, each collapsed or
  expanded, with a chip each to jump to it or bring it back.
- **The crash rules.** No timer of its own; no event filters but the
  host's (`on_release`, `on_double`, the pen watch feeding forge_hud's pen
  log); verbs through `later()`; disk through `read()`, whose answer comes
  back through a queued-signal poster (`on_main`) — no thread ever calls
  `flame.schedule_idle_event`, which deadlocked Flame. A failing area shows
  one line and stops nothing; re-registering an id swaps it in the live
  window.

Each area gets an `AreaHost` — `LensWindow`'s own surface, per area — so a
drawing made for the standalone Segment Lens is hosted unchanged:
forge-streams' `SegmentGraph(host)` draws the Depends area pixel for pixel
as the standalone window draws it (`tests/render_lens.py` checks that, narrow
and wide). The contract is r3 on forge-hud#1; the API is in the module
header.

Two things save an area from reaching into the window:

- **`ctx.asked`** says why this refresh: `subject`, `settled`, `refresh`,
  `update`, `layout`, `fold`, `build`, `tab` or `frame`. An area that reads
  from disk only on some of them redraws on the rest, and reads on a value
  it doesn't know. `frame` (forge_lens ≥ 0.8.2) goes only to areas
  registered with `frames=True`. They get it on every beat where the
  playhead moved but the subject didn't change and nothing settled, at most
  once a beat. Every other area hears about a new frame only once the
  playhead settles. A scrub's jumps also set `ctx.playing`, the same as
  playback does.
- **`forge_lens.current_sequence()`** is the live `PySequence` the Lens last
  walked, or None. On Effects it's the one held from before the switch.
- **`forge_lens.on_double(widget, fn)`** works on any pen: Qt's double-click, or
  two releases timed here. Qt reported almost none from the Plank iPad client.
- **`forge_lens.segment(key)`** is the live `PySegment` from the Lens's last
  walk (Flame's thread), or `None` when the timeline was edited since:
  its name or record in no longer match.
- **`with forge_lens.hold():`** around anything that moves the Timeline on
  the artist's behalf (a take switch saving effect setups). While held the
  Lens reads nothing; on release it takes Flame's click, frame and
  selection as they are, as no action of the artist's. Re-entrant; a hold
  never released lets go by itself after about a minute.
- **`tabs=`** on `register_area`: an area shows and is refreshed on its own
  tabs only. Off the Timeline (Batch, say) the Lens has no spine, caption,
  subject or follow button and reads nothing from the Timeline; `ctx.tab`
  says where, and the area reads its own subject and calls `update()` when
  it changes. Each tab keeps its own layout and place. Coming to a tab
  refreshes its areas, with `ctx.asked == "tab"`. `host.window()` is a real
  parent for an area's own popout or dialog.
- **`forge_lens.popup_under(button, menu)`** drops a menu from a button and
  keeps it on the button's screen. On macOS with two screens, the system
  otherwise moves a popup off a non-primary screen about 120 ms after it
  opens. Header tools get this already; use it for a menu of your own.

The area filling most of the Lens's view holds its place on screen
(forge_lens ≥ 0.8.3; 0.8.1 held the first area whose top was in view). If
an area above it changes height, for example Takes or Depends redrawn for a
new subject, the scroll value moves to make up the difference, so the area
being read doesn't shift. The held area is chosen again on every beat from
what's on screen. At the top of the Lens with the first area filling the
view, the top stays the top. An area can still scroll the Lens itself
through its host; that scroll becomes the new place to hold. Each area is
drawn at the height it asks for (its `sizeHint`) and is never squeezed to
fit, so the Lens scrolls instead (forge_lens ≥ 0.8.5).

A saved window place, narrow or wide, comes back whole on the screen it is
mostly on (forge_lens ≥ 0.8.5). It is shrunk to fit that screen and moved
onto it; if the screen is too small even for the minimum size, the top-right
corner stays on it.

The artist orders the areas by dragging their chips along the row under
the caption (forge_lens ≥ 0.8.4). A line shows where the chip will land;
on release the area moves there. The order is saved per user and comes
back in every later session, whatever order the distros register in. An
area registering for the first time goes after the ones already ordered.
Holding a place can't help at the top of the Lens when there is little to
scroll, so an area that must not move, such as forge-courier's Notes, is
best dragged first.

On the spine, a `Mark(key, colour, "band", row)` is a thin bar in the
take's colour over that shot, in a row above the tracks (0 nearest them),
one row per take for forge-takes' groups. The spine grows by the rows the
areas' overlays use, up to four and then "+n"; a preview's bands never grow
it.

A `Mark(key, colour, "pin", at)` (forge_lens ≥ 0.8.0) sits at record frames
instead of over a whole shot. `at` is a frame (an int) or a range
`(first, last)`, both frames included like `Seg.record_in`/`record_out`. `key`
is the shot the pin is on, so pins on a dimmed shot dim with it. Pins draw in
their own lane above the bands: a small tick at a frame, a thin bar over a
range. The lane is held while any overlay has pins. A preview's pins (the one
selected or hovered) draw taller and outlined and never grow the spine, and a
pin under the pointer draws the same way. Clicking a pin moves the playhead to
its first frame, makes its shot the subject (as `focus()` does) and then calls
the area's `register_area(..., on_pin=fn)` with that Mark on the idle queue.
On Effects the playhead stays put, but the area is still told. An older
forge_lens skips pins. For Courier's notes: one pin per frame.

Tests: `pytest tests` (no Qt needed); the window itself, offscreen under
Flame's Python: `PYTHONPATH=../forge-streams/src
/opt/Autodesk/python/2027.1/bin/python3 tests/render_lens.py <out>
[<segment lens state.json>]`.

## Backlog

- **Fold the rail to a tab-like strip** (Chris, 2026-10-30): beyond the
  header chip and its dots, collapse the HUD to something that sits like a
  tab at a screen edge.

## Known consumers

| distro | section | row shows | popup |
| --- | --- | --- | --- |
| forge-wireless ≥ 1.6.0 | `wireless` | channel/get counts + health | channel palette (click = drop a Get), Relink all |
| forge-takes | `takes` | current take in its colour + batch | take switcher tree, Takes Editor… |
