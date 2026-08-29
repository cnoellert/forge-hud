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
#       default_enabled=False)      # first-run state (per-user file wins later)
#
# Row anatomy is owned by the LIBRARY so every section reads the same way:
#
#     ● WIRELESS   12 ch · 31 gets
#     ● TAKE       comp_v2  GMM_260
#
# dot (refresh's "dot", crimson on "alert") + the section title as a small
# muted header in its own aligned column + the section's content ("html",
# content only -- no dot, no tool name). Without the header column, a row
# whose content is a value (a take name) is unreadable next to one whose
# content is a summary.
#   forge_hud.toggle("wireless")    # menu action; returns the new state
#   forge_hud.ensure()              # show the dock if any section is enabled
#   forge_hud.update()              # refresh row labels (action checkpoints)
#
# register() replaces by id, so module reloads re-register cleanly. refresh()
# and menu() must never raise for the caller's sake -- but the dock guards
# every callback anyway: a HUD must never break an action.
#
# Staleness model (no QTimer -- the crash-#16 rules from forge-takes apply
# throughout: standard widgets only, no custom delegates, no event filters):
#   * popups rebuild live on click -- never stale
#   * row labels refresh on mouse-enter, after every popup, and whenever the
#     owning tool calls update() from its action checkpoints
# There is no Flame hook for node deletion or graph edits (verified against
# the API inventory), so hover-refresh is the event-driven answer to state
# that changes behind the tools' backs.
#
# Reload safety: everything long-lived (registry, dock window, state) is
# parked on the QApplication instance, which survives module reloads. A
# rescan that reloads THIS module adopts the parked state, closes the old
# window (its methods belong to the old module object), and rebuilds with
# the new code -- no zombie pill, no lost registrations.
#
# Per-user state -- position, collapsed, per-section enabled -- persists in
# ~/.forge_hud.json.
# ---------------------------------------------------------------------------

import json
import os

__version__ = "1.1.1"

STATE_PATH = os.path.join(os.path.expanduser("~"), ".forge_hud.json")

# FORGE family theme (byte-compatible with forge-wireless / forge-takes).
EMBER = "#E87E24"
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


# --- process-global anchor (survives reloads) ------------------------------

_LOCAL = {"sections": {}, "order": [], "dock": None}


def _anchor():
    """The one registry+dock holder for this process.

    Parked on the QApplication instance so a reload of this module finds
    the same dict; module-global fallback keeps headless imports working.
    """
    try:
        _c, _g, QtWidgets = _qt()
        app = QtWidgets.QApplication.instance()
        if app is None:
            return _LOCAL
        held = getattr(app, "_forge_hud_state", None)
        if held is None:
            app._forge_hud_state = _LOCAL
            return _LOCAL
        return held
    except Exception:
        return _LOCAL


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


# --- public API -------------------------------------------------------------

def register(sid, title, refresh, menu, default_enabled=False):
    """Add or replace a HUD section. Safe to call at import time (no Qt is
    touched); safe to call again on module reload (replaces by id)."""
    st = _anchor()
    if sid not in st["order"]:
        st["order"].append(sid)
    st["sections"][sid] = {
        "title": title,
        "refresh": refresh,
        "menu": menu,
        "default": bool(default_enabled),
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


def ensure():
    """Show the dock if any registered section is enabled."""
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
        state = _state()
        dock.move(int(state.get("x", 80)), int(state.get("y", 80)))
    try:
        dock.rebuild()
        if not dock.isVisible():
            dock.show()
        dock.refresh_labels()
    except Exception:
        pass


def update():
    """Refresh row labels; cheap no-op when the dock is hidden or absent."""
    dock = _anchor().get("dock")
    if dock is None:
        return
    try:
        if dock.isVisible():
            dock.refresh_labels()
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
            self.setCursor(QtCore.Qt.PointingHandCursor)
            self._press = None
            self._offset = None
            self._moved = False
            self._manual_drag = False
            self._rows = {}                       # QLabel -> section id
            self._titles = {}                     # section id -> header QLabel
            self._contents = {}                   # section id -> content QLabel
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(14, 7, 14, 9)
            lay.setSpacing(4)
            # the window tracks its content size automatically -- rows come
            # and go (enable/disable/collapse) and labels change width
            lay.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
            self.header = QtWidgets.QLabel("", self)
            self.header.setTextFormat(QtCore.Qt.RichText)
            self.header.setStyleSheet(
                "color: #ddd; font-size: 11px; font-weight: bold; "
                "background: transparent;")
            lay.addWidget(self.header)
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

        def _apply_collapse(self):
            collapsed = bool(_state().get("collapsed"))
            for lbl in self._rows:
                lbl.setVisible(not collapsed)
            self.refresh_labels()

        # -- content --------------------------------------------------------

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

        def enterEvent(self, _event):
            # hover is the refresh signal for state that changed behind the
            # tools' backs (hand-deleted nodes) -- no QTimer, ever
            self.refresh_labels()

        # -- click targets --------------------------------------------------

        def _click(self, pos):
            target = self.childAt(pos)
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
    if st is _LOCAL:
        return                    # first load in this process (or headless)
    old = st.get("dock")
    if old is None:
        return
    try:
        was_visible = old.isVisible()
        old.close()
        old.deleteLater()
    except Exception:
        was_visible = False
    st["dock"] = None
    if was_visible:
        try:
            ensure()
        except Exception:
            pass


_adopt_previous()
