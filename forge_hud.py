# forge_hud.py
# ---------------------------------------------------------------------------
# FORGE HUD -- one shared, dockable HUD rail for FORGE Flame tools.
#
# Any FORGE distro (forge-takes, forge-wireless, ...) registers a *section*;
# every enabled section renders as one row in a single frameless, always-on-
# top, draggable dock. Clicking a row opens that section's own popup menu
# (built fresh by the owning tool on every click, so it can never go stale).
# The FORGE header chip collapses the rail to just the chip plus one status
# dot per section -- glanceable health even when folded away.
#
# API (what a distro calls):
#
#   import forge_hud
#   forge_hud.register(
#       "wireless",                 # stable id
#       title="Wireless",           # the row's header + "Hide Wireless HUD"
#       refresh=my_refresh,         # () -> {"html": ..., "tooltip": ...,
#                                   #        "alert": bool, "dot": "#hex"}
#       menu=my_menu,               # (QMenu, (QtCore, QtGui, QtWidgets)) -> None
#       default_enabled=False,      # first-run state (per-user file wins later)
#       tabs=("Batch",),            # Flame tabs where this section belongs
#       key=my_key)                 # optional: () -> hashable, see below
#   forge_hud.toggle("wireless")    # menu action; returns the new state
#   forge_hud.ensure()              # show the dock if any section is enabled
#   forge_hud.update()              # refresh row labels (action checkpoints)
#
# Tab awareness: the dock hides itself when the current Flame tab matches no
# enabled section's `tabs` (a Batch HUD has no business floating over the
# Timeline) and reappears on return. Flame has no tab-change hook, and --
# verified live on 2026.2.2 with counters on focusChanged /
# focusObjectChanged / focusWindowChanged -- its custom-drawn tab bar emits
# NO Qt focus traffic when the user switches tabs. The only mechanism left
# is a slow heartbeat: a 600 ms QTimer on the dock reading
# flame.get_current_tab() (a trivial getter) and re-applying the context on
# change. This is the ONE sanctioned QTimer in the FORGE HUD family -- the
# crash-#16 hazard is timers firing into closing dialogs, and this one is
# parented to a session-lived singleton, does nothing but a guarded getter
# + compare, stops itself if the anchor no longer points at its dock, and
# is stopped explicitly before a reload swaps the dock.
#
# Row anatomy is owned by the LIBRARY so every section reads the same way:
#
#     ● WIRELESS   12 ch · 31 gets
#     ● TAKE       comp_v2  GMM_260
#
# A painted 2x3 dot grip sits left of the FORGE chip -- the signpost for a
# rail that has always dragged from anywhere on itself but never said so.
# It narrows nothing: press anywhere, >5px of travel is still a drag. It
# rests at the window's border colour and brightens on hover, so the
# affordance shows up exactly when it is actionable.
#
# Brightness is the WHOLE message, because cursor shape is not available to
# us: Flame owns the pointer application-wide, and per-widget setCursor()
# (OpenHand over the chrome, PointingHand over the rows -- the obvious other
# half) is simply overridden, verified live on 2026.2.2. Note this cuts both
# ways: the blanket PointingHandCursor this dock used to set never reached
# the screen either. Do not re-add cursor handling expecting it to work; if
# you want a second channel, it has to be tooltips.
#
# dot (refresh's "dot", crimson on "alert") + the section title as a small
# muted header in its own aligned column + the section's content ("html",
# content only -- no dot, no tool name). Without the header column, a row
# whose content is a value (a take name) is unreadable next to one whose
# content is a summary.
#
# register() replaces by id, so module reloads re-register cleanly. refresh()
# and menu() must never raise for the caller's sake -- but the dock guards
# every callback anyway: a HUD must never break an action.
#
# Staleness model (timer-free apart from the heartbeat above -- the
# crash-#16 rules from forge-takes apply throughout: standard widgets only,
# no custom delegates, no event filters):
#   * popups rebuild live on click -- never stale
#   * row labels refresh on mouse-enter, after every popup, and whenever the
#     owning tool calls update() from its action checkpoints
#   * and when a section's `key` changes. A key is a trivial getter naming
#     WHAT the row is about -- forge-takes passes the current batch group's
#     name -- read by the heartbeat on every tick while the dock is visible.
#     A changed key redraws the rows. This exists because Flame has no hook
#     for a batch group switch either: the takes row went on naming the
#     previous group until something else happened to redraw it
#     (forge-takes#2). The key must be as cheap as get_current_tab(), because
#     it runs at the same rate; refresh() is NOT, and is only called when a
#     key actually moved.
# There is no Flame hook for node deletion or graph edits (verified against
# the API inventory), so hover-refresh is the event-driven answer to state
# that changes behind the tools' backs.
#
# Reload safety: everything long-lived (registry, dock reference, heartbeat
# handle) is anchored on `builtins` -- deliberately NOT the QApplication
# wrapper, which PySide can garbage-collect (taking dynamic attributes with
# it; seen live). A rescan that reloads THIS module adopts the anchored
# state, stops the old heartbeat, closes the old window (its methods belong
# to the old module object) and rebuilds with the new code -- no zombie
# pill, no lost registrations. Cold start is covered separately: an idle
# event scheduled at import raises the dock after a Flame restart (see the
# cold-start boot at the bottom).
#
# Per-user state -- position, collapsed, per-section enabled -- persists in
# ~/.forge_hud.json.
#
# Screen-aware placement: the saved position is absolute desktop
# coordinates, so a display that shrinks under it (working-resolution
# change, a monitor unplugged, Flame moved to a smaller screen) can leave a
# frameless, title-bar-less dock parked outside every screen -- invisible
# and undraggable, recoverable only by editing the state file. Every
# placement therefore runs through _place(), which clamps the window fully
# inside the available geometry of whichever screen it most overlaps (or
# the nearest one when it overlaps none), and the heartbeat re-clamps
# whenever the set of screen rectangles changes. reset_position() is the
# manual escape hatch for consumers to expose.
# ---------------------------------------------------------------------------

import json
import os

__version__ = "1.7.0"

STATE_PATH = os.path.join(os.path.expanduser("~"), ".forge_hud.json")

# FORGE family theme (byte-compatible with forge-wireless / forge-takes).
EMBER = "#E87E24"
# The drag grip: resting at the window's own border colour (present, but it
# asks for nothing), brightening to the row-title grey under the cursor.
GRIP_REST = "#3a3f4f"
GRIP_HOVER = "#8a93a4"
MENU_SS = (
    "QMenu { background: #23262f; color: #ccc; border: 1px solid #3a3f4f; "
    "  font-size: 12px; padding: 4px; }"
    "QMenu::item { padding: 5px 24px 5px 8px; border-radius: 3px; }"
    "QMenu::item:selected { background: #2d4f7a; }"
    "QMenu::item:disabled { color: #888; }"
    "QMenu::separator { height: 1px; background: #3a3f4f; margin: 4px 6px; }"
)


def _qt():
    from PySide6 import QtCore, QtGui, QtWidgets   # Flame 2025+
    return QtCore, QtGui, QtWidgets


# --- the drag grip ----------------------------------------------------------
#
# Six dots in a 2x3 grid, the universal "this moves" mark. PAINTED, not a
# glyph: the obvious spellings (braille U+283F, a double U+22EE) are at the
# mercy of whatever fonts the host happens to carry, and a tofu box in the
# corner of the rail is worse than no grip at all. A pixmap renders the same
# on every Flame box there is.
#
# It is a signpost, not a hit target -- the whole dock still drags, exactly
# as it always has. _click() ignores the grip label precisely because a
# handle that does something when clicked is a button pretending to be a
# handle.

_GRIP_DOT = 2       # dot diameter, px
_GRIP_PITCH = 4     # dot centre-to-centre, px
_GRIP_COLS = 2
_GRIP_ROWS = 3
_GRIP_W = _GRIP_PITCH * _GRIP_COLS - (_GRIP_PITCH - _GRIP_DOT)
_GRIP_H = _GRIP_PITCH * _GRIP_ROWS - (_GRIP_PITCH - _GRIP_DOT)


def _grip_pixmap(QtCore, QtGui, colour, ratio=1.0):
    """A 2x3 dot grid in *colour*, crisp at *ratio* (hidpi device pixels).

    The pixmap is allocated in DEVICE pixels and then told its ratio, but every
    drawing coordinate below is LOGICAL. That is not a style choice: once a
    pixmap carries a device pixel ratio, QPainter scales drawing operations by
    it automatically, so multiplying coordinates by the ratio as well applies
    it twice. On a retina display that put four of the six dots outside a
    6x10 pixmap and clipped the rest to a couple of blobs in one column.

    It also hid: __init__ paints before the widget is shown, when the ratio
    still reads 1.0 and the arithmetic is accidentally right. Only the first
    hover - which repaints at the real ratio - revealed it.
    """
    ratio = max(1.0, float(ratio or 1.0))
    pm = QtGui.QPixmap(int(_GRIP_W * ratio), int(_GRIP_H * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    try:
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(colour))
        for col in range(_GRIP_COLS):
            for row in range(_GRIP_ROWS):
                p.drawEllipse(
                    QtCore.QRectF(col * _GRIP_PITCH, row * _GRIP_PITCH,
                                  _GRIP_DOT, _GRIP_DOT))
    finally:
        # an unended QPainter on a pixmap that then gets reused is a live
        # Qt warning storm; end it even if the loop above threw
        p.end()
    return pm


# --- process-global anchor (survives reloads) ------------------------------

def _anchor():
    """The one registry+dock holder for this process, parked on `builtins`.

    NOT on the QApplication instance: PySide can garbage-collect the
    Python *wrapper* around the C++ QApplication and mint a fresh one,
    taking any dynamic attributes (and with them the registry and the dock
    reference) silently with it -- seen live on 2026.2.2 as a dock that
    would not come back and a registry that had emptied itself. A builtins
    attribute is plain Python: immune to wrapper GC, to importlib.reload,
    and to a rescan that builds a new module object.
    """
    import builtins               # noqa: PLC0415
    held = getattr(builtins, "_forge_hud_state", None)
    if held is None:
        held = {"sections": {}, "order": [], "dock": None}
        builtins._forge_hud_state = held
    return held


# --- per-user state file ----------------------------------------------------

def _state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(**changes):
    try:
        state = _state()
        state.update(changes)
        with open(STATE_PATH, "w") as f:
            json.dump(state, f)
    except Exception:
        pass                      # a HUD must never break an action


def _set_enabled(sid, value):
    state = _state()
    enabled = state.get("enabled", {})
    enabled[sid] = bool(value)
    _save_state(enabled=enabled)


# --- screen-aware placement -------------------------------------------------

def _screen_rects():
    """Available geometry of every screen as (x, y, w, h) -- [] outside Qt."""
    try:
        _c, QtGui, _w = _qt()
        app = QtGui.QGuiApplication.instance()
        if app is None:
            return []
        out = []
        for scr in app.screens():
            g = scr.availableGeometry()
            out.append((g.x(), g.y(), g.width(), g.height()))
        return out
    except Exception:
        return []


def _clamp_to_screens(x, y, w, h):
    """Nudge a w*h window at (x, y) fully onto a real screen.

    Home screen = the one it overlaps most; if it overlaps none (the usual
    case after a resolution drop) the nearest by top-left distance. A dock
    larger than its screen pins to the top-left rather than hanging off the
    far edge.
    """
    rects = _screen_rects()
    if not rects:
        return x, y

    def overlap(r):
        rx, ry, rw, rh = r
        return (max(0, min(x + w, rx + rw) - max(x, rx))
                * max(0, min(y + h, ry + rh) - max(y, ry)))

    best = max(rects, key=overlap)
    if overlap(best) <= 0:
        best = min(rects,
                   key=lambda r: (r[0] - x) ** 2 + (r[1] - y) ** 2)
    rx, ry, rw, rh = best
    x = min(max(x, rx), rx + max(0, rw - w))
    y = min(max(y, ry), ry + max(0, rh - h))
    return x, y


def _place(dock, x=None, y=None):
    """Move the dock to (x, y) -- its saved spot by default -- on-screen.

    A no-op when the window is already fully visible, so it is safe to call
    on every show, every resize and every heartbeat that sees the screen
    layout change. Pass explicit coordinates to clamp the dock where it
    is now; omit them to restore the saved spot.

    A window that has never been shown reports a stale size AND a stale
    sizeHint (its labels are filled but the layout has not run), so the
    layout is activated first -- measuring too small parks the dock by a
    left edge that is already past the screen's right edge.
    """
    try:
        state = _state()
        if x is None:
            x = state.get("x", 80)
        if y is None:
            y = state.get("y", 80)
        try:
            lay = dock.layout()
            if lay is not None:
                lay.activate()
        except Exception:
            pass
        hint = dock.sizeHint()
        w = max(dock.width(), hint.width(), 1)
        h = max(dock.height(), hint.height(), 1)
        nx, ny = _clamp_to_screens(int(x), int(y), w, h)
        dock._screens = _screen_rects()
        if (nx, ny) != (dock.x(), dock.y()):
            dock.move(nx, ny)     # moveEvent persists the correction
    except Exception:
        pass                      # a HUD must never break an action


# --- public API -------------------------------------------------------------

def register(sid, title, refresh, menu, default_enabled=False,
             tabs=("Batch",), key=None):
    """Add or replace a HUD section. Safe to call at import time (no Qt is
    touched); safe to call again on module reload (replaces by id).
    `tabs` names the Flame tabs the section belongs to (falsy = all).
    `key`, when given, is a cheap () -> hashable the heartbeat polls; the
    rows redraw when it changes (see the staleness model)."""
    st = _anchor()
    if sid not in st["order"]:
        st["order"].append(sid)
    st["sections"][sid] = {
        "title": title,
        "refresh": refresh,
        "menu": menu,
        "default": bool(default_enabled),
        "tabs": tuple(tabs) if tabs else (),
        "key": key,
    }
    dock = st.get("dock")
    if dock is not None:
        try:
            dock.rebuild()
        except Exception:
            pass


def enabled(sid):
    sec = _anchor()["sections"].get(sid)
    default = sec["default"] if sec else False
    return bool(_state().get("enabled", {}).get(sid, default))


def show(sid):
    _set_enabled(sid, True)
    ensure()


def hide(sid):
    _set_enabled(sid, False)
    st = _anchor()
    dock = st.get("dock")
    if dock is None:
        return
    try:
        if any(enabled(s) for s in st["order"]):
            dock.rebuild()
        else:
            dock.hide()
    except Exception:
        pass


def toggle(sid):
    """Flip one section; returns the new enabled state."""
    now = not enabled(sid)
    (show if now else hide)(sid)
    return now


def reset_position():
    """Park the dock back at the default corner; True if one was placed.

    The escape hatch for a dock lost off-screen -- placement is clamped
    automatically, but a user who has already lost one needs a way back
    that does not involve editing ~/.forge_hud.json.
    """
    _save_state(x=80, y=80)
    st = _anchor()
    if st.get("dock") is None:
        ensure()                  # no-op when every section is hidden
    dock = st.get("dock")
    if dock is None:
        return False
    _place(dock, 80, 80)
    return True


def ensure():
    """Surface the dock if any enabled section belongs on the current tab."""
    st = _anchor()
    if not any(enabled(s) for s in st["order"] if s in st["sections"]):
        return
    dock = st.get("dock")
    if dock is None:
        try:
            dock = _make_dock()
        except Exception:
            return                # headless / no QApplication
        st["dock"] = dock
        _start_heartbeat(dock)
    try:
        dock.rebuild()
    except Exception:
        pass
    # after rebuild, so the clamp measures the rail at its real size
    _place(dock)
    _apply_context(force=True)


def update():
    """Refresh row labels; cheap no-op when the dock is hidden or absent."""
    _apply_context()              # cached tab compare -- cheap when unchanged
    dock = _anchor().get("dock")
    if dock is None:
        return
    try:
        if dock.isVisible():
            dock.refresh_labels()
    except Exception:
        pass


# --- tab context ------------------------------------------------------------
# The dock belongs to specific Flame tabs (each section declares its own;
# Batch by default). No hook announces a tab change and the custom-drawn
# tab bar emits no Qt focus signals (verified live), so the dock's
# heartbeat timer is the trigger; the action checkpoints re-apply the
# context too, so a stopped timer degrades to lazy hiding, never breakage.

def _current_tab():
    """The current Flame tab name, or None outside Flame (fail open)."""
    try:
        import flame              # noqa: PLC0415
        return str(flame.get_current_tab())
    except Exception:
        return None


def _apply_context(force=False):
    """Show/hide the dock for the current tab; filter rows to it."""
    st = _anchor()
    dock = st.get("dock")
    if dock is None:
        return
    try:
        tab = _current_tab()
        if not force and tab == dock._last_tab:
            return
        dock._last_tab = tab
        dock._apply_collapse()    # re-filter rows for the new tab
        here = any(dock._row_on_tab(sid, tab) for sid in dock._titles)
        if here:
            if not dock.isVisible():
                _place(dock)      # never surface it off-screen
                dock.show()
            dock.refresh_labels()
        else:
            dock.hide()
    except Exception:
        pass                      # a HUD must never break an action


def _section_keys(dock):
    """{section id: key()} for every shown row whose section has a key.
    A key that raises reads as None -- a HUD must never break anything."""
    st = _anchor()
    keys = {}
    for sid in dock._titles:
        getter = (st["sections"].get(sid) or {}).get("key")
        if getter is None:
            continue
        try:
            keys[sid] = getter()
        except Exception:
            keys[sid] = None
    return keys


def _keys_moved(dock):
    """True when any shown section's key differs from the last tick's.
    The first reading after a rebuild only records: refresh_labels() has
    just run then anyway."""
    keys = _section_keys(dock)
    before = getattr(dock, "_keys", None)
    dock._keys = keys
    return before is not None and keys != before


def _start_heartbeat(dock):
    """The dock's 600 ms tab watcher -- see the module header for why this
    is the one sanctioned QTimer. Parented to the dock (dies with it),
    stops itself if the anchor no longer points at its dock."""
    try:
        QtCore, _g, _w = _qt()
        timer = QtCore.QTimer(dock)
        timer.setInterval(600)

        def tick():
            try:
                if _anchor().get("dock") is not dock:
                    timer.stop()
                    return
                if _current_tab() != dock._last_tab:
                    _apply_context(force=True)
                elif dock.isVisible() and _keys_moved(dock):
                    dock.refresh_labels()
                # a display that shrank (or vanished) under the dock leaves
                # a frameless window stranded off-screen with no title bar
                # to drag it back -- re-clamp when the layout changes
                if _screen_rects() != getattr(dock, "_screens", None):
                    _place(dock)
            except Exception:
                pass              # a HUD must never break anything

        timer.timeout.connect(tick)
        timer.start()
        dock._tab_timer = timer
    except Exception:
        pass


# --- the dock ---------------------------------------------------------------

def _make_dock():
    QtCore, QtGui, QtWidgets = _qt()
    st = _anchor()

    class Dock(QtWidgets.QWidget):
        def __init__(self):
            super().__init__(
                None,
                QtCore.Qt.FramelessWindowHint
                | QtCore.Qt.WindowStaysOnTopHint
                | QtCore.Qt.Tool,
            )
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
            # no setCursor anywhere in this class: Flame overrides it (see
            # the module header). The grip's brightness is the affordance.
            self._press = None
            self._offset = None
            self._moved = False
            self._manual_drag = False
            self._last_tab = "\x00uninitialised"
            self._rows = {}                       # QLabel -> section id
            self._titles = {}                     # section id -> header QLabel
            self._contents = {}                   # section id -> content QLabel
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(14, 7, 14, 9)
            lay.setSpacing(4)
            # the window tracks its content size automatically -- rows come
            # and go (enable/disable/collapse) and labels change width
            lay.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
            # header row: the drag grip, then the FORGE chip. The grip sits
            # left of the chip so it holds the same spot collapsed or not.
            self._grips = {}                      # colour -> QPixmap cache
            self.grip = QtWidgets.QLabel("", self)
            self.grip.setToolTip("Drag anywhere on the rail to move it")
            self.grip.setStyleSheet("background: transparent;")
            self.header = QtWidgets.QLabel("", self)
            self.header.setTextFormat(QtCore.Qt.RichText)
            self.header.setToolTip("Drag to move \u00b7 click to collapse")
            self.header.setStyleSheet(
                "color: #ddd; font-size: 11px; font-weight: bold; "
                "background: transparent;")
            hrow = QtWidgets.QHBoxLayout()
            hrow.setContentsMargins(0, 0, 0, 0)
            hrow.setSpacing(7)
            hrow.addWidget(self.grip, 0, QtCore.Qt.AlignVCenter)
            # the chip takes the rest of the row, so a click anywhere right
            # of the grip still collapses -- as it did when the header label
            # spanned the whole rail
            hrow.addWidget(self.header, 1)
            lay.addLayout(hrow)
            self._set_grip(GRIP_REST)
            # two aligned columns: "● TITLE" headers left, content right
            self._grid = QtWidgets.QGridLayout()
            self._grid.setHorizontalSpacing(10)
            self._grid.setVerticalSpacing(4)
            lay.addLayout(self._grid)

        # -- structure ------------------------------------------------------

        def rebuild(self):
            """Recreate one row per enabled section, in registration order."""
            while self._grid.count():
                item = self._grid.takeAt(0)
                w = item.widget()
                if w is not None:
                    # hide + unparent IMMEDIATELY: deleteLater alone is
                    # deferred, and a rebuild triggered from a popup or a
                    # hook left old labels alive and painting over the new
                    # row (seen live: a 'ghost' takes row on 2026.2.2)
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
            self._rows = {}
            self._titles = {}
            self._contents = {}
            r = 0
            for sid in st["order"]:
                if sid not in st["sections"] or not enabled(sid):
                    continue
                title = QtWidgets.QLabel("", self)
                title.setTextFormat(QtCore.Qt.RichText)
                title.setStyleSheet("background: transparent;")
                content = QtWidgets.QLabel("", self)
                content.setTextFormat(QtCore.Qt.RichText)
                content.setStyleSheet(
                    "color: #ddd; font-size: 13px; font-weight: bold; "
                    "background: transparent;")
                self._grid.addWidget(title, r, 0)
                self._grid.addWidget(content, r, 1)
                # a click on either half of the row opens the section menu
                self._rows[title] = sid
                self._rows[content] = sid
                self._titles[sid] = title
                self._contents[sid] = content
                r += 1
            self._apply_collapse()

        def _row_on_tab(self, sid, tab):
            sec = st["sections"].get(sid) or {}
            wants = sec.get("tabs")
            return tab is None or not wants or tab in wants

        def _apply_collapse(self):
            collapsed = bool(_state().get("collapsed"))
            tab = _current_tab()
            for lbl, sid in self._rows.items():
                lbl.setVisible(not collapsed and self._row_on_tab(sid, tab))
            self.refresh_labels()

        # -- content --------------------------------------------------------

        def _set_grip(self, colour):
            """Repaint the grip in *colour* (cached per colour + ratio)."""
            try:
                ratio = float(self.devicePixelRatioF())
            except Exception:
                ratio = 1.0
            key = (colour, ratio)
            pm = self._grips.get(key)
            if pm is None:
                pm = _grip_pixmap(QtCore, QtGui, colour, ratio)
                self._grips[key] = pm
            self.grip.setPixmap(pm)

        def refresh_labels(self):
            collapsed = bool(_state().get("collapsed"))
            dots = []
            for sid in st["order"]:
                if sid not in self._titles:
                    continue
                sec = st["sections"].get(sid)
                if sec is None:
                    continue
                try:
                    d = sec["refresh"]() or {}
                except Exception:
                    d = {"html": '<span style="color: #666;">(error)</span>'}
                dot = (d.get("dot")
                       or ("#C0392B" if d.get("alert") else "#777"))
                self._titles[sid].setText(
                    '<span style="color: {0}; font-size: 13px;">●</span>'
                    '&nbsp;<span style="color: #8a93a4; font-size: 10px; '
                    'font-weight: bold;">{1}</span>'.format(
                        dot, sec["title"].upper()))
                self._contents[sid].setText(d.get("html", ""))
                tip = d.get("tooltip", "")
                self._titles[sid].setToolTip(tip)
                self._contents[sid].setToolTip(tip)
                dots.append(dot)
            arrow = "▸" if collapsed else "▾"
            chip = ('<span style="color: {0};">FORGE</span>'
                    '&nbsp;<span style="color: #666;">{1}</span>'
                    .format(EMBER, arrow))
            if collapsed:
                chip += "&nbsp;" + "".join(
                    '<span style="color: {0};">●</span>'.format(c)
                    for c in dots)
            self.header.setText(chip)

        # -- painting -------------------------------------------------------

        def paintEvent(self, _event):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            p.setBrush(QtGui.QColor(20, 22, 28, 235))
            p.setPen(QtGui.QPen(QtGui.QColor(58, 63, 79), 1))
            p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 9, 9)

        # -- drag / click ---------------------------------------------------
        #
        # Press anywhere; >5px of travel is a drag, a clean release is a
        # click on whatever row it landed on. Dragging prefers the OS-native
        # startSystemMove() (reliable on every platform for frameless
        # windows); the manual move() path is the fallback. During a system
        # move Qt delivers no further mouse events, so the position persists
        # from moveEvent instead of the release.

        def mousePressEvent(self, event):
            if event.button() == QtCore.Qt.LeftButton:
                self._press = event.globalPosition().toPoint()
                self._offset = self._press - self.frameGeometry().topLeft()
                self._moved = False
                self._manual_drag = False

        def mouseMoveEvent(self, event):
            if self._press is None:
                return
            here = event.globalPosition().toPoint()
            if not self._moved and (here - self._press).manhattanLength() < 5:
                return
            if not self._moved:
                self._moved = True
                started = False
                try:
                    handle = self.windowHandle()
                    if handle is not None:
                        started = bool(handle.startSystemMove())
                except Exception:
                    started = False
                if started:
                    # the WM owns the drag now; no release will arrive
                    self._press = None
                    return
                self._manual_drag = True
            if self._manual_drag:
                self.move(here - self._offset)

        def mouseReleaseEvent(self, _event):
            if self._press is None:
                return
            press_pos = self.mapFromGlobal(self._press)
            self._press = None
            if self._moved:
                self._moved = False
                _save_state(x=self.x(), y=self.y())
                return
            self._click(press_pos)

        def moveEvent(self, _event):
            if self.isVisible():
                _save_state(x=self.x(), y=self.y())

        def showEvent(self, event):
            # the first show is the first time the rail has a real size --
            # re-clamp with it (a pre-show hint can be an underestimate)
            super().showEvent(event)
            _place(self, self.x(), self.y())

        def resizeEvent(self, event):
            # rows grow with their content ("14 ch . 31 gets"); a dock
            # parked against the right edge must not grow off it
            super().resizeEvent(event)
            if self.isVisible():
                _place(self, self.x(), self.y())

        def enterEvent(self, _event):
            # hover is the refresh signal for state that changed behind the
            # tools' backs (hand-deleted nodes) -- no QTimer, ever
            self.refresh_labels()
            # ...and the moment the affordance is actionable is the moment
            # it becomes visible: the grip lights up under the cursor
            self._set_grip(GRIP_HOVER)

        def leaveEvent(self, _event):
            # a plain override, not an event filter -- crash #16 rules hold.
            # No "did it really leave?" guard is needed, and this is
            # confirmed live, not just reasoned from Qt's enter/leave
            # ancestor-chain pruning: crossing from the rail onto one of its
            # own labels sends the dock nothing, so the grip stays lit for
            # the whole hover and dims only on a real exit.
            self._set_grip(GRIP_REST)

        # -- click targets --------------------------------------------------

        def _click(self, pos):
            target = self.childAt(pos)
            # the grip deliberately matches nothing below: it is a handle,
            # and a handle that acts on click is a button in disguise
            if target is self.header:
                _save_state(collapsed=not bool(_state().get("collapsed")))
                self._apply_collapse()
                return
            sid = self._rows.get(target)
            if sid is not None:
                self._open_menu(sid, target)

        def _open_menu(self, sid, lbl):
            sec = st["sections"].get(sid)
            if sec is None:
                return
            popup = QtWidgets.QMenu(self)
            popup.setStyleSheet(MENU_SS)
            try:
                sec["menu"](popup, (QtCore, QtGui, QtWidgets))
            except Exception:
                err = popup.addAction("(menu failed -- see console)")
                err.setEnabled(False)
                import traceback
                traceback.print_exc()
            popup.addSeparator()
            # every section's popup carries the same footer: park the rail
            # back at the default corner, or fold this section away
            reset_act = popup.addAction("Reset HUD position")
            reset_act.triggered.connect(lambda _c=False: reset_position())
            hide_act = popup.addAction("Hide {0} HUD".format(sec["title"]))
            hide_act.triggered.connect(lambda _c=False, s=sid: hide(s))
            popup.exec(lbl.mapToGlobal(lbl.rect().bottomLeft()))
            self.refresh_labels()

    return Dock()


# --- reload adoption --------------------------------------------------------
# A rescan that reloads this module leaves the previous dock running old
# code. Close it and rebuild with the new code if it was visible; the
# registry (parked on the app) carries the sections across untouched.

def _adopt_previous():
    st = _anchor()
    # disconnect a previous generation's focusChanged handler (v1.2.x used
    # one before the heartbeat replaced it) and stop its timer
    try:
        _c, _g, QtWidgets = _qt()
        app = QtWidgets.QApplication.instance()
        old_cb = st.get("focus_cb")
        if app is not None and old_cb is not None:
            app.focusChanged.disconnect(old_cb)
            st["focus_cb"] = None
    except Exception:
        pass
    try:
        st["dock"]._tab_timer.stop()
    except Exception:
        pass
    old = st.get("dock")
    if old is not None:
        try:
            old.close()
            old.deleteLater()
        except Exception:
            pass
        st["dock"] = None
    # rebuild unconditionally: the dock may have been hidden only by tab
    # context (not by the user), and ensure() + _apply_context() restore
    # the correct state either way -- created, watching focus, shown or
    # hidden for the current tab
    try:
        ensure()
    except Exception:
        pass


# --- cold-start boot --------------------------------------------------------
# Hook-scan imports run during Flame startup, before any checkpoint -- and
# entering an existing desktop batch after a restart fires NO hook at all
# (batch_setup_loaded is disk loads only), so without this the dock waited
# for the first right-click or takes action. One idle event on the main
# thread: ensure() builds the dock (hidden or shown per the current tab)
# and starts the heartbeat, which handles everything from then on.
# Idempotent; a no-op when nothing is enabled or outside Flame.

def _startup_boot():
    try:
        ensure()
    except Exception:
        pass


def _schedule_startup_boot():
    try:
        import flame              # noqa: PLC0415
        flame.schedule_idle_event(_startup_boot)
    except Exception:
        pass                      # headless / outside Flame


_adopt_previous()
_schedule_startup_boot()
