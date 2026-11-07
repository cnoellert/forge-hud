"""The one Lens, offscreen, with real Qt -- run under Flame's Python:

  PYTHONPATH=../forge-streams/src /opt/Autodesk/python/2027.1/bin/python3 \\
      tests/render_lens.py <out dir> [<segment lens state.json>]

LINKTEST2's cut (forge-takes' snapshot) is the timeline. Two demo areas --
Takes from the snapshot, and a Versions area that cross-reads it with
same_as() -- plus, given a Segment Lens state (forge-streams'
seglens.snapshot, e.g. /var/tmp/forge_streams_golden/wtr090_state.json),
forge-streams' own SegmentGraph hosted as the Depends area, unchanged. Its
canvas is then compared pixel for pixel with the standalone Segment Lens's,
narrow and wide. Renders go to <out dir>; nothing is written to ~/.
"""

import json
import os
import sys
import types

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

out = sys.argv[1]
graph_state = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else None
os.makedirs(out, exist_ok=True)

# forge_hud stands in: no heartbeat (beats are driven here), no pen log
hud = types.ModuleType("forge_hud")
hud.pen_note = lambda *a, **k: None
hud.listen = hud.unlisten = lambda *a, **k: None
sys.modules["forge_hud"] = hud

import fakeflame  # noqa: E402

snap = fakeflame.linktest2()
seq = fakeflame.Sequence(snap["cut"])
flame = fakeflame.module(seq)
sys.modules["flame"] = flame

from PySide6 import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication([])
import forge_lens as fl  # noqa: E402

fl.STATE_PATH = os.path.join(out, "lens_state.json")
if os.path.exists(fl.STATE_PATH):
    os.remove(fl.STATE_PATH)


def pump():
    for _ in range(6):
        app.processEvents()
        while flame.idle:
            flame.idle.pop(0)()
        app.processEvents()


COLOURS = dict((t["take"], t["colour"] or fl.MAIN_COLOUR) for t in snap["takes"])
failures = []


def check(what, ok):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        failures.append(what)


# --- a demo Takes area, from the snapshot ---------------------------------------

def sig(rows):
    return tuple(tuple(r) for r in rows)


def takes_build(parent, ctx):
    lbl = QtWidgets.QLabel()
    lbl.setTextFormat(QtCore.Qt.RichText)
    lbl.setWordWrap(True)
    return lbl


def takes_refresh(widget, ctx, mode):
    p = ctx.primary
    seg = snap["segments"].get(p.key) if p else None
    if seg is None:
        widget.setText('<span style="color:#8a93a4;">No takes here.</span>')
        return
    lines = ['<b style="color:{0};">● {1}</b> &nbsp;<span style="color:#8a93a4;">'
             'on now</span>'.format(COLOURS.get(seg["on"], fl.MAIN_COLOUR), seg["on"])]
    for sw in seg["switch"]:
        if sw["on_now"]:
            continue
        said = ", ".join(c["text"] for c in sw["changes"]) or "relabel"
        lines.append('<span style="color:{0};">●</span> switch to {1} &nbsp;'
                     '<span style="color:#8a93a4;">{2}</span>'.format(
                         COLOURS.get(sw["take"], fl.MAIN_COLOUR), sw["take"], said))
    widget.setText("<br>".join(lines))


def takes_summary(ctx):
    p = ctx.primary
    seg = snap["segments"].get(p.key) if p else None
    if not seg:
        return {"html": "", "tone": "neutral"}
    n = sum(1 for sw in seg["switch"] if not sw["on_now"] and sw["changes"])
    return {"html": "on {0} · {1} take{2} would change it".format(seg["on"], n, "s" * (n != 1)),
            "tone": "neutral"}


def takes_overlay(ctx):
    return [fl.Mark(k, COLOURS.get(s["on"], fl.MAIN_COLOUR), "fill")
            for k, s in snap["segments"].items()]


def takes_effects(ctx):
    out_ = {}
    for s in ctx.segments:
        seg = snap["segments"].get(s.key)
        if seg:
            out_[s.key] = [("switch to " + seg["on"], sig(seg["signature"]))] + \
                [(e["label"], sig(e["signature"])) for e in seg["effects_by_switch"]]
    return out_


fl.register_area("takes.takes", "Takes", build=takes_build, refresh=takes_refresh,
                 summary=takes_summary, overlay=takes_overlay, effects=takes_effects,
                 wide=True)

# --- a demo Versions area: GMM_410 V2's three ways (r3's corrected table) ---------

MAIN = (("Timewarp", False, "35ed1e3fcb69953c"), ("Resize", False, "b991e0c441855d87"))
WAYS = [("v01 – v03", (("Timewarp", False, "4313aaaaaaaaaaaa"), MAIN[1])),
        ("v04 – v08 · v10", MAIN),
        ("v09 · v11 – v13", MAIN + (("Colour Correct", False, "d71641214d0cbb04"),))]


def versions_build(parent, ctx):
    w = QtWidgets.QLabel()
    w.setTextFormat(QtCore.Qt.RichText)
    return w


def versions_refresh(widget, ctx, mode):
    p = ctx.primary
    if p is None or p.key != "GMM_410 (track 2)":
        widget.setText('<span style="color:#8a93a4;">13 versions · 3 ways it has been</span>')
        return
    rows = []
    for name, s in WAYS:
        same = fl.same_as("streams.versions", p.key, s)
        rows.append('<span style="color:#c9d0dc;">{0}</span>{1}'.format(
            name, ''.join('&nbsp; <span style="color:#7a61ad;">= {0}</span>'.format(lbl)
                          for _a, lbl in same)))
    widget.setText("<br>".join(rows))


fl.register_area("streams.versions", "Versions", build=versions_build,
                 refresh=versions_refresh,
                 summary=lambda ctx: {"html": "13 versions · 3 ways it has been",
                                      "tone": "neutral"},
                 effects=lambda ctx: {"GMM_410 (track 2)": [("roll back to " + n, s)
                                                            for n, s in WAYS]},
                 follows=("takes.takes",))

# --- Depends: forge-streams' SegmentGraph, hosted unchanged ---------------------------

ui_lens = ui_seglens = None
if graph_state is not None:
    from forge_streams import ui_lens, ui_seglens          # noqa: E402
    from forge_streams.ui_seggraph import SegmentGraph      # noqa: E402

    ui_lens.STATE_PATH = os.path.join(out, "streams_lens_state.json")
    if os.path.exists(ui_lens.STATE_PATH):
        os.remove(ui_lens.STATE_PATH)

    def depends_build(parent, ctx):
        host = fl.host("streams.depends")
        host.STATE_PREFIX = "segment_"     # the standalone Segment Lens's folding
        host.graph = SegmentGraph(host)
        host.redraw = lambda state: host.graph.draw(ui_seglens._only(state, host.views))
        host.reveal_card = host.graph.reveal
        host.hover = host.graph.hover_link
        host.redraw(graph_state)
        return None                        # drawn through host._scroll

    def depends_refresh(widget, ctx, mode):
        fl.host("streams.depends").redraw(graph_state)

    fl.register_area("streams.depends", "Depends", build=depends_build,
                     refresh=depends_refresh,
                     summary=lambda ctx: {"html": "v004 · roto ← plate v002", "tone": "warn"},
                     wide=True)

# --- the window ------------------------------------------------------------------------

seq._now = fakeflame.Time(86600)                   # GMM_230's first frames: V2's GMM_410
seq.primary_track = seq.version.tracks[1]          # the focus on V2
win = fl.open(fl.Timeline(flame))
win.resize(400, 1200)
pump()
ctx = win.follower.ctx
check("subject: GMM_410 · V2 at the playhead, over Gap on track 3",
      ctx.primary is not None and ctx.primary.name == "GMM_410 · V2"
      and [s.name for s in ctx.over] == ["Gap on track 3"])
check("the spine holds the whole cut: 3 tracks, 86448-87167",
      win.spine.span == (86448, 87167, 3))
check("cross-reading: v04 – v08 · v10 = switch to Main",
      "= switch to Main" in win.frames["streams.versions"].content.text()
      and win.frames["streams.versions"].content.text().count("= switch to Main") == 1)
check("summary: Takes says what it holds",
      "would change it" in win.frames["takes.takes"]._summary.text())
win.grab().save(os.path.join(out, "lens_narrow.png"))

# a preview: Versions' v09 · v11 – v13 hovered
fl.preview("streams.versions", [fl.Mark("GMM_410 (track 2)", COLOURS["warmer"], "fill"),
                                 fl.Mark("GMM_410 (track 2)", None, "dim_rest")],
           ("v09 · v11 – v13 → now: 1 change", ["GMM_410 · V2   take   warmer → Main"]))
pump()
h0 = win.spine.height()
win.grab().save(os.path.join(out, "lens_narrow_preview.png"))
check("a preview never resizes the spine", win.spine.height() == h0)
fl.preview("streams.versions", None)

# a failing area shows one line and stops nothing
fl.register_area("broken.one", "Broken", build=lambda p, c: 1 / 0,
                 refresh=lambda w, c, m: None)
pump()
check("a failed build is one guard line", win.frames["broken.one"]._guard.isVisible()
      and "build failed (ZeroDivisionError)" in win.frames["broken.one"]._guard.text())
fl.unregister_area("broken.one")

# a refresh that failed once: its line goes with the next refresh that works
FAIL = [True]
def flaky_refresh(w, c, m):
    if FAIL[0]:
        raise RuntimeError("Clip does not have multiple versions to select.")
fl.register_area("flaky.one", "Flaky", build=lambda p, c: QtWidgets.QLabel("f"),
                 refresh=flaky_refresh)
pump()
line = win.frames["flaky.one"]._guard
check("a failed refresh says so", line.isVisible() and "refresh failed (RuntimeError)" in line.text())
FAIL[0] = False
fl.update("flaky.one")
pump()
check("and the next refresh that works takes the line away", line.isHidden())
fl.unregister_area("flaky.one")

# re-register: the callbacks swap in the live window
fl.register_area("streams.versions", "Versions", build=versions_build,
                 refresh=versions_refresh,
                 summary=lambda ctx: {"html": "swapped", "tone": "info"},
                 follows=("takes.takes",))
pump()
check("re-register swaps the callbacks live",
      "swapped" in win.frames["streams.versions"]._summary.text())

# the tab: off the Timeline it hides; back, it returns
fl._beat("Batch")
check("hidden off its tab", not win.isVisible())
fl._beat("Timeline")
pump()
check("back on its tab", win.isVisible())

# a tab of its own: an area on Batch shows there alone, with no timeline read
batch_asks = []
batch_tabs = []
fl.register_area("probe.batch", "Batch", build=lambda p, c: QtWidgets.QLabel("graph"),
                 refresh=lambda w, c, m: (batch_asks.append(c.asked), batch_tabs.append(c.tab)),
                 tabs=("Batch",), overlay=lambda c: [fl.Mark("GMM_400", "#123456", "fill")],
                 wide=True)
pump()
check("a Batch area on the Timeline: not shown, not refreshed, off the spine",
      not win.frames["probe.batch"].isVisible() and not batch_asks
      and "#123456" not in win.spine.fills.values())
t_rect = win.geometry()
t_uid, t_frame = win.follower.uid, seq.current_time.frame
t_subject = win.follower.ctx.subject()
walks = []
real_sequence = win.follower.tl.sequence
win.follower.tl.sequence = lambda: (walks.append(1), real_sequence())[1]
fl._beat("Batch")
pump()
check("on Batch: the window stays, its area alone shows, asked why",
      win.isVisible() and win.tab == "Batch" and win.frames["probe.batch"].isVisible()
      and not win.frames["streams.versions"].isVisible() and batch_asks == ["tab"]
      and batch_tabs == ["Batch"])
check("on Batch: no spine, no caption, no subject, no follow button",
      not win.spine.isVisible() and not win._cap_box.isVisible()
      and not win._subject.isVisible() and not win._follow_btn.isVisible())
fl._beat("Batch")
fl._beat("Batch")
check("on Batch: the Timeline is never read, the area not refreshed per beat",
      not walks and win.follower.ctx.tab == "Batch" and not win.follower.ctx.segments
      and batch_asks == ["tab"])
win.setGeometry(40, 50, 330, 500)
win.set_mode("wide")
wide_batch = win.mode
win.setGeometry(60, 70, 1000, 500)
win.remember()
fl._beat("Timeline")
pump()
win.follower.tl.sequence = real_sequence
check("back on the Timeline: its own place and layout, the subject kept",
      win.tab == "Timeline" and win.geometry() == t_rect and win.mode == "narrow"
      and wide_batch == "wide" and win.follower.ctx.subject() == t_subject
      and win.spine.isVisible() and win.frames["streams.versions"].isVisible()
      and not win.frames["probe.batch"].isVisible())
fl._beat("Media")
check("through a tab it isn't on: hidden", not win.isVisible())
fl._beat("Batch")
pump()
check("to Batch from there: Batch's own place and layout",
      win.isVisible() and win.tab == "Batch" and win.mode == "wide"
      and win.geometry() == QtCore.QRect(60, 70, 1000, 500))
host = fl.host("probe.batch")
check("the host's surface: a real parent, its width, its metrics, whether it shows",
      host.window() is win and host.width() == win.frames["probe.batch"].width()
      and host.fontMetrics().height() > 0 and host.isVisible())
win.set_mode("narrow")
fl._beat("Timeline")
fl.unregister_area("probe.batch")
pump()
check("the Batch area gone: Batch isn't a Lens tab again",
      "Batch" not in fl._tabs() and win.isVisible())

# a click in the timeline: GMM_230 (V1) selected
g230 = seq.seg("GMM_230")
g230.selected = True
flame.timeline.current_segment = g230
fl._beat("Timeline")
pump()
check("a click selects the subject", win.follower.ctx.primary.key == "GMM_230")

# the spine dragged: the positioner follows, the subject with it
win.scrub(86450, done=True)
pump()
check("the spine scrubs the positioner (from start_time)", seq.current_time.frame == 86450
      and win.follower.ctx.primary.key == "GMM_400")



# the spine by the mouse: the line drags; a segment is clicked
def mouse(kind, x, y, buttons):
    from PySide6 import QtGui
    pos = QtCore.QPointF(x, y)
    glob = QtCore.QPointF(win.spine.mapToGlobal(pos.toPoint()))
    ev = QtGui.QMouseEvent(kind, pos, glob, QtCore.Qt.LeftButton,
                           buttons, QtCore.Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(win.spine, ev)


def press_release(x0, y0, x1, y1):
    mouse(QtCore.QEvent.MouseButtonPress, x0, y0, QtCore.Qt.LeftButton)
    pump()
    mouse(QtCore.QEvent.MouseMove, x1, y1, QtCore.Qt.LeftButton)
    pump()
    mouse(QtCore.QEvent.MouseButtonRelease, x1, y1, QtCore.Qt.NoButton)
    pump()


sp = win.spine
mid = lambda s_: sp._rect(s_.track, s_.record_in, s_.record_out).center()  # noqa: E731
line = sp._x(seq.current_time.frame) + 0.5
far = sp._x(86900)
press_release(line + 2, sp.PAD + 2, far, sp.PAD + 2)
check("the spine's line drags the playhead",
      seq.current_time.frame == sp._frame_at(far) and not win.follower.pinned)
g430 = win.follower.cut.by_key["GMM_430"]
g400 = win.follower.cut.by_key["GMM_400"]
before = seq.current_time.frame
c = mid(g400)
mouse(QtCore.QEvent.MouseButtonPress, c.x(), c.y(), QtCore.Qt.LeftButton)
pump()
check("a press on a segment moves nothing", seq.current_time.frame == before)
c2 = mid(g430)
mouse(QtCore.QEvent.MouseButtonRelease, c2.x(), c2.y(), QtCore.Qt.NoButton)
pump()
check("a press that wanders to another segment does nothing",
      seq.current_time.frame == before and not win.follower.pinned)
press_release(c2.x(), c2.y(), c2.x(), c2.y())
check("a segment clicked on the spine: the playhead to its start, pinned on it",
      seq.current_time.frame == g430.record_in and win.follower.pinned == ["GMM_430"]
      and win.follower.ctx.source == "pin" and win.follower.ctx.primary.key == "GMM_430")
win._toggle_pin()
pump()
g230.selected = False
flame.timeline.current_segment = seq.seg("GMM_400")
fl._beat("Timeline")
pump()
check("a plain click in the timeline (nothing selected) leads",
      win.follower.ctx.source == "click" and win.follower.ctx.primary.key == "GMM_400")


# why each refresh was asked (ctx.asked), as an area sees it
asked = []
fl.register_area("probe.asked", "Probe", build=lambda p, c: QtWidgets.QLabel("probe"),
                 refresh=lambda w, c, m: asked.append(c.asked),
                 summary=lambda c: {"html": str(c.asked), "tone": "neutral"})
pump()
win.frames["probe.asked"].set_fold("expanded")
pump()
fl.update("probe.asked")
win.refresh_all()
seq._now = fakeflame.Time(86600)                      # GMM_410 V2: the subject moves
flame.timeline.current_segment = None
win.follower.click = None
for _ in range(4):
    fl._beat("Timeline")
pump()
win.set_mode("wide")
pump()
win.set_mode("narrow")
pump()
want = ["build", "fold", "update", "refresh", "subject", "settled", "layout"]
check("ctx.asked says why: " + ", ".join(want),
      all(w in asked for w in want) and asked[0] == "build"
      and win.follower.ctx.asked is None)
fl.unregister_area("probe.asked")
pump()

# band marks: a row per take over the tracks, the spine grown by the rows
sp = win.spine
h_before = sp.height()
BANDS = [fl.Mark("GMM_400", COLOURS["warmer"], "band", 0),
         fl.Mark("GMM_230", COLOURS["warmer"], "band", 0),
         fl.Mark("GMM_430", "#b0743a", "band", 1)]
fl.register_area("probe.bands", "Bands", build=lambda p, c: QtWidgets.QLabel("b"),
                 refresh=lambda w, c, m: None, overlay=lambda c: list(BANDS))
pump()
grown = sp.height() - h_before
img = sp.grab().toImage()
g400 = win.follower.cut.by_key["GMM_400"]
bx = int(sp._x(g400.record_in) + 3)
row0_y = sp.PAD + (sp.band_rows - 1 - 0) * (sp.BAND + sp.BAND_GAP) + 1
px = img.pixelColor(int(bx * img.width() / sp.width()), int(row0_y * img.height() / sp.height()))
check("band marks: 2 rows grow the spine by 12 px and the split, row 0 in its take colour over GMM_400",
      sp.band_rows == 2 and grown == 2 * (sp.BAND + sp.BAND_GAP) + sp.SPLIT
      and px.name() == fl._colour(COLOURS["warmer"]).name())
win.grab().save(os.path.join(out, "lens_bands.png"))
fl.preview("takes.takes", [fl.Mark("GMM_230", "#298587", "band", 3)], ("hover", []))
pump()
check("a preview's band never grows the spine", sp.height() - h_before == grown)
fl.preview("takes.takes", None)
BANDS[:] = [fl.Mark("GMM_400", "#298587", "band", r) for r in range(6)]
fl.update("probe.bands")
pump()
check("six rows: four drawn, +2 said", sp.band_rows == 6
      and sp.height() - h_before == 4 * (sp.BAND + sp.BAND_GAP) + sp.SPLIT)
win.grab().save(os.path.join(out, "lens_bands_more.png"))
fl.unregister_area("probe.bands")
pump()
check("no bands: the spine back to its height", sp.height() == h_before)


# pins: Courier's notes at record frames, in a lane of their own over the bands
def _px_at(x, y):
    img = sp.grab().toImage()
    fx, fy = img.width() / sp.width(), img.height() / sp.height()
    return img.pixelColor(int(x * fx), int(y * fy)).name()


g230 = win.follower.cut.by_key["GMM_230"]
f_one = g400.record_in + 5
was_subject, was_current = win.follower.ctx.primary.key, flame.timeline.current_segment
PINS = [fl.Mark("GMM_400", "#E87E24", "pin", f_one),
        fl.Mark("GMM_230", "#7fbf7f", "pin", (g230.record_in, g230.record_out)),
        fl.Mark("GMM_400", "#E87E24", "pin", "not a frame")]
clicked = []
fl.register_area("probe.notes", "Notes", build=lambda p, c: QtWidgets.QLabel("n"),
                 refresh=lambda w, c, m: None, overlay=lambda c: list(PINS),
                 on_pin=clicked.append)
pump()
lane = sp.height() - h_before
tick, bar = sp._pin_rect(PINS[0]), sp._pin_rect(PINS[1])
check("pins: the lane grows the spine by PIN_HI, a gap and the split; a bad at is dropped",
      sp.pin_lane and lane == sp.PIN_HI + sp.BAND_GAP + sp.SPLIT and len(sp.pins) == 2)
check("a pin at a frame is a tick there, a range a bar over it, in their colours",
      _px_at(tick.center().x(), tick.center().y()) == "#e87e24"
      and _px_at(bar.center().x(), bar.center().y()) == "#7fbf7f"
      and abs(tick.center().x() - (sp._x(f_one) + sp._x(f_one + 1)) / 2.0) < 0.01
      and abs(bar.left() - sp._x(g230.record_in)) < 0.01)
win.grab().save(os.path.join(out, "lens_pins.png"))
hi = sp._pin_rect(PINS[0], True)
above = (tick.center().x(), hi.top() + 1.5)
subject_key = win.follower.ctx.primary.key
s_rect = sp._rect(*[getattr(win.follower.cut.by_key[subject_key], f)
                    for f in ("track", "record_in", "record_out")])
stroke_before = _px_at(s_rect.center().x(), s_rect.top() + 0.6)
before_hi = _px_at(*above)
fl.preview("probe.notes", [PINS[0]], ("GMM_400 · a note", ["Not green enough"]))
pump()
check("a previewed pin draws taller and outlined, never growing the spine",
      before_hi != "#e87e24" and _px_at(*above) == "#e87e24" and sp.height() - h_before == lane)
check("a pin preview leaves the subject's outline as it was",
      _px_at(s_rect.center().x(), s_rect.top() + 0.6) == stroke_before)
win.grab().save(os.path.join(out, "lens_pins_preview.png"))
fl.preview("probe.notes", None)
pump()
mouse(QtCore.QEvent.MouseMove, tick.center().x(), tick.center().y(), QtCore.Qt.NoButton)
pump()
check("a pin hovered on the spine is drawn as a preview's",
      sp._hover_pin == ("probe.notes", PINS[0]) and _px_at(*above) == "#e87e24")
press_release(tick.center().x(), tick.center().y(), tick.center().x(), tick.center().y())
check("a pin clicked: the playhead to its frame, its shot the subject, its area told",
      seq.current_time.frame == f_one and win.follower.ctx.primary.key == "GMM_400"
      and clicked == [PINS[0]])
press_release(bar.center().x(), bar.center().y(), bar.center().x(), bar.center().y())
check("a range clicked: the playhead to its first frame, its area told",
      seq.current_time.frame == g230.record_in and clicked[-1] == PINS[1])
before = seq.current_time.frame
c = mid(g400)
press_release(tick.center().x(), tick.center().y(), c.x(), c.y())
check("a pin press that wanders into the tracks does nothing",
      seq.current_time.frame == before and len(clicked) == 2)
fl.unregister_area("probe.notes")
pump()
check("no pins: the lane gone, the spine back to its height",
      not sp.pin_lane and sp.height() == h_before)
# a pin click is a spine use, as focus() is: a click in the timeline ends it,
# leaving the timeline as the spine's own clicks above left it
other = "GMM_400" if was_subject != "GMM_400" else "GMM_230"
for current in (seq.seg(other), was_current):
    flame.timeline.current_segment = current
    fl._beat("Timeline")
    pump()
check("after the pins, a plain click in the timeline leads again",
      win.follower.spine is False and win.follower.ctx.primary.key == was_subject)


# the place held: the area in view stays put while one above changes height
GROW = [60]
fl.register_area("probe.grow", "Grows", build=lambda p, c: QtWidgets.QLabel("g"),
                 refresh=lambda w, c, m: w.setFixedHeight(GROW[0]))
MID = [80]
fl.register_area("probe.mid", "Mid", build=lambda p, c: QtWidgets.QLabel("m"),
                 refresh=lambda w, c, m: w.setFixedHeight(MID[0]))
fl.register_area("probe.below", "Below", build=lambda p, c: QtWidgets.QLabel("b"),
                 refresh=lambda w, c, m: w.setFixedHeight(900))
pump()
bar = win.scroll.verticalScrollBar()
below = win.frames["probe.below"]
bar.setValue(below.y() - 10)
pump()
screen_y = below.y() - bar.value()
GROW[0] = 180
fl.update("probe.grow")
pump()
check("an area above grows: the one in view stays where it was on screen",
      bar.value() > 0 and below.y() - bar.value() == screen_y)
GROW[0] = 20
fl.update("probe.grow")
pump()
check("and shrinks: still where it was", below.y() - bar.value() == screen_y)
GROW[0] = 60
win.beat("Timeline", force=True)
pump()
check("a subject's refresh of every area: still where it was", below.y() - bar.value() == screen_y)
bar.setValue(bar.value() + 40)
pump()
screen_y = below.y() - bar.value()
GROW[0] = 140
fl.update("probe.grow")
pump()
check("a scroll takes the place afresh, and that is held",
      below.y() - bar.value() == screen_y)
# live, 0.8.2: Depends' top the first in view, Notes under it filling most of
# the view -- Depends changed height and Notes moved. The one most in view holds.
mid = win.frames["probe.mid"]
bar.setValue(mid.y() - 20)
pump()
fl._beat("Timeline")                    # the place chosen again from the screen
pump()
screen_y = below.y() - bar.value()
mid_top_in_view = 0 <= mid.y() - bar.value() < win.scroll.viewport().height()
MID[0] = 200
fl.update("probe.mid")
pump()
check("an area changes height just above the one most in view: that one stays put",
      mid_top_in_view and win._place[0] == "probe.below"
      and below.y() - bar.value() == screen_y)
MID[0] = 80
fl.update("probe.mid")
pump()
check("and back: still where it was", below.y() - bar.value() == screen_y)
GROW[0] = win.scroll.viewport().height() + 100
fl.update("probe.grow")
pump()
bar.setValue(0)
pump()
fl._beat("Timeline")
pump()
GROW[0] += 60
fl.update("probe.grow")
pump()
check("at the top, the top area filling the view: the top stays the top", bar.value() == 0)
fl.unregister_area("probe.below")
fl.unregister_area("probe.mid")
fl.unregister_area("probe.grow")
pump()

# frames=True: an area that shows the frame hears of each one, asked "frame"
heard, deaf = [], []
fl.register_area("probe.frames", "Frames", build=lambda p, c: QtWidgets.QLabel("f"),
                 refresh=lambda w, c, m: heard.append((c.asked, c.frame, c.playing)),
                 frames=True)
fl.register_area("probe.deaf", "Deaf", build=lambda p, c: QtWidgets.QLabel("d"),
                 refresh=lambda w, c, m: deaf.append(c.asked))
pump()
f_was = seq._now
mid_400 = (g400.record_in + g400.record_out) // 2
seq._now = fakeflame.Time(mid_400)
for _ in range(4):
    fl._beat("Timeline")
    pump()
subject_was = win.follower.ctx.subject()
del heard[:], deaf[:]
seq._now = fakeflame.Time(mid_400 + 1)
fl._beat("Timeline")
pump()
check("the frame moved, nothing else: a frames area refreshed, asked \"frame\"; no other",
      win.follower.ctx.subject() == subject_was
      and heard == [("frame", mid_400 + 1, False)] and deaf == [])
seq._now = fakeflame.Time(mid_400 + 6)
fl._beat("Timeline")
pump()
check("a scrub's jump inside the shot: heard too, ctx.playing set",
      heard[-1] == ("frame", mid_400 + 6, True) and deaf == [])
del heard[:]
fl._beat("Timeline")
pump()
check("a still beat: not asked again", not any(a == "frame" for a, _f, _p in heard))
fl.unregister_area("probe.frames")
fl.unregister_area("probe.deaf")
seq._now = f_was
for _ in range(4):
    fl._beat("Timeline")
    pump()

# the order: a chip dragged along the row moves its area, and the order stays
def chip_mouse(chip, kind, x, buttons):
    from PySide6 import QtGui
    pos = QtCore.QPointF(x, chip.height() / 2)
    glob = QtCore.QPointF(chip.mapToGlobal(pos.toPoint()))
    QtWidgets.QApplication.sendEvent(chip, QtGui.QMouseEvent(
        kind, pos, glob, QtCore.Qt.LeftButton, buttons, QtCore.Qt.NoModifier))


def chip_of(area_id):
    return [c for c in win._chip_list if c.area_id == area_id][0]


def drag_chip(area_id, onto_x, held=None, via=None):
    """Press the chip, move to *onto_x* (window x), release; *held* runs
    while it is still down."""
    chip = chip_of(area_id)
    x0 = chip.width() // 2
    chip_mouse(chip, QtCore.QEvent.MouseButtonPress, x0, QtCore.Qt.LeftButton)
    x1 = onto_x - chip.mapTo(win, QtCore.QPoint(0, 0)).x()
    mid = (x0 + x1) // 2 if via is None else via - chip.mapTo(win, QtCore.QPoint(0, 0)).x()
    chip_mouse(chip, QtCore.QEvent.MouseMove, mid, QtCore.Qt.LeftButton)
    chip_mouse(chip, QtCore.QEvent.MouseMove, x1, QtCore.Qt.LeftButton)
    if held is not None:
        held()
    chip_mouse(chip, QtCore.QEvent.MouseButtonRelease, x1, QtCore.Qt.NoButton)
    pump()


def probes_order():
    return [a for a in fl._anchor()["order"] if a.startswith("probe.o")]


def stacked():
    ids = [a for a in fl._anchor()["order"] if a in win.frames and not win.frames[a].isHidden()]
    return sorted(ids, key=lambda a: win.frames[a].y())


for oid in ("probe.o1", "probe.o2", "probe.o3"):
    fl.register_area(oid, oid[-2:].upper(), build=lambda p, c: QtWidgets.QLabel("o"),
                     refresh=lambda w, c, m: None)
pump()
fl._beat("Timeline")
pump()
jumped = []
real_jump = win.jump
win.jump = lambda a: jumped.append(a)
seen = {}
o1 = chip_of("probe.o1")
o1_left = o1.mapTo(win, QtCore.QPoint(0, 0)).x()
drag_chip("probe.o3", o1_left + 2, held=lambda: seen.update(
    mark=win._chip_mark.isVisible(), x=win._chip_mark.x(), dragging=chip_of("probe.o3").dragging))
check("a chip dragged: the line shows before the one it lands before, the chip lit",
      seen.get("mark") and seen.get("dragging") and abs(seen["x"] - (o1_left - 3)) <= 1)
check("dropped before O1: O3 first in the order, its frame above O1's, the chips too",
      probes_order() == ["probe.o3", "probe.o1", "probe.o2"]
      and [a for a in stacked() if a.startswith("probe.o")] == probes_order()
      and [c.area_id for c in win._chip_list if c.area_id.startswith("probe.o")] == probes_order()
      and not win._chip_mark.isVisible())
check("a drag is no click: nothing jumped", jumped == [])
saved = fl._load_state().get("order") or []
check("the order saved", [a for a in saved if a.startswith("probe.o")] == probes_order())
o2 = chip_of("probe.o2")
o2_mid = o2.mapTo(win, QtCore.QPoint(o2.width() // 2 + 2, 0)).x()
before = list(fl._anchor()["order"])
drag_chip("probe.o2", o2_mid, via=o2_mid + 60)     # out along the row and back
check("dragged out and back where it was: nothing moves, nothing jumped",
      fl._anchor()["order"] == before and jumped == [])
last = win._chip_list[-1]
drag_chip("probe.o3", last.mapTo(win, QtCore.QPoint(last.width() + 20, 0)).x())
check("dropped past the last chip: O3 last", fl._anchor()["order"][-1] == "probe.o3"
      and probes_order() == ["probe.o1", "probe.o2", "probe.o3"])
drag_chip("probe.o2", chip_of("probe.o1").mapTo(win, QtCore.QPoint(1, 0)).x())
chip = chip_of("probe.o1")
chip_mouse(chip, QtCore.QEvent.MouseButtonPress, 5, QtCore.Qt.LeftButton)
chip_mouse(chip, QtCore.QEvent.MouseMove, 6, QtCore.Qt.LeftButton)
chip_mouse(chip, QtCore.QEvent.MouseButtonRelease, 6, QtCore.Qt.NoButton)
pump()
check("a press that barely moves is a click: it goes to the area", jumped == ["probe.o1"])
win.jump = real_jump
for oid in ("probe.o1", "probe.o2", "probe.o3"):
    fl.unregister_area(oid)
pump()
for oid in ("probe.o1", "probe.o3", "probe.o2"):     # another session, any order
    fl.register_area(oid, oid[-2:].upper(), build=lambda p, c: QtWidgets.QLabel("o"),
                     refresh=lambda w, c, m: None)
pump()
check("registered again in any order: the order dragged to comes back (O2 O1 O3)",
      probes_order() == ["probe.o2", "probe.o1", "probe.o3"]
      and [a for a in stacked() if a.startswith("probe.o")] == probes_order())
for oid in ("probe.o1", "probe.o2", "probe.o3"):
    fl.unregister_area(oid)
fl._save_state(order=[])
pump()

# an area that can shrink is never squeezed to fit: the Lens scrolls instead
class _Squashy(QtWidgets.QLabel):
    def sizeHint(self):                              # noqa: N802
        return QtCore.QSize(200, 1400)

    def minimumSizeHint(self):                       # noqa: N802
        return QtCore.QSize(20, 20)


fl.register_area("probe.squash", "Squash", build=lambda p, c: _Squashy("s"),
                 refresh=lambda w, c, m: None)
sq = win.frames["probe.squash"]
# alone, as live: a wrapping label in view sends QScrollArea down its
# height-for-width path, which never squeezed -- the live Lens had none
others = [f for a, f in win.frames.items() if a != "probe.squash"]
for f in others:
    f.setVisible(False)
sq.set_fold("collapsed")
pump()
sq.set_fold("expanded")
pump()
bar = win.scroll.verticalScrollBar()
check("an area expanded that could shrink: drawn at its height ({0}), the Lens scrolls ({1})"
      .format(sq.content.height(), bar.maximum()),
      sq.content.height() == 1400 and bar.maximum() > 0)
fl.unregister_area("probe.squash")
for a, f in win.frames.items():
    f.setVisible(win.shows(a))
pump()

# a standing filter: an overlay's dim_rest lights its shots and dims the rest
def _spine_px(key):
    s = win.follower.cut.by_key[key]
    r = sp._rect(s.track, s.record_in, s.record_out)
    img = sp.grab().toImage()
    fx, fy = img.width() / sp.width(), img.height() / sp.height()
    return img.pixelColor(int(r.center().x() * fx), int(r.center().y() * fy)).name()


def _subject_stroke_px(key):
    s = win.follower.cut.by_key[key]
    r = sp._rect(s.track, s.record_in, s.record_out)
    img = sp.grab().toImage()
    fx, fy = img.width() / sp.width(), img.height() / sp.height()
    return img.pixelColor(int(r.center().x() * fx), int((r.top() + 0.6) * fy)).name()


fl.preview("takes.takes", None)
FILTER = []
fl.register_area("probe.filter", "Filter", build=lambda p, c: QtWidgets.QLabel("f"),
                 refresh=lambda w, c, m: None, overlay=lambda c: list(FILTER))
pump()
plain_400, plain_230 = _spine_px("GMM_400"), _spine_px("GMM_230")
h_before = sp.height()
FILTER[:] = [fl.Mark("GMM_400", None, "dim_rest")]
fl.update("probe.filter")
pump()
check("a filter: its shot lit as it was, the rest dimmed, the spine the same size",
      sp.lit == {"GMM_400"} and _spine_px("GMM_400") == plain_400
      and _spine_px("GMM_230") != plain_230 and sp.height() == h_before)
dimmed_230 = _spine_px("GMM_230")
win.grab().save(os.path.join(out, "lens_filter.png"))
subject = sorted(sp.subject)[0] if sp.subject else None
check("a filter strokes no member; the subject keeps its outline",
      subject is not None and subject != "GMM_400"
      and _subject_stroke_px(subject) == "#f2f2f2"
      and _subject_stroke_px("GMM_400") == plain_400)
fl.preview("takes.takes", [fl.Mark("GMM_230", "#298587", "fill")], ("hover", []))
pump()
check("a hover takes over from the filter", _spine_px("GMM_230") == "#298587"
      and _spine_px("GMM_400") == plain_400)
fl.preview("takes.takes", [fl.Mark("GMM_230", None, "dim_rest")], ("hover", []))
pump()
check("a hover's own dim is its own: the filter's member dims under it",
      _spine_px("GMM_230") == plain_230 and _spine_px("GMM_400") != plain_400)
fl.preview("takes.takes", None)
pump()
check("the hover gone: the filter is back", _spine_px("GMM_230") == dimmed_230
      and _spine_px("GMM_400") == plain_400)
win.beat("Timeline", force=True)
pump()
check("a filter outlives a beat that clears previews", sp.lit == {"GMM_400"}
      and _spine_px("GMM_230") == dimmed_230)
FILTER[:] = [fl.Mark(None, None, "dim_rest")]
fl.update("probe.filter")
pump()
check("a filter with no members in this cut dims every segment",
      _spine_px("GMM_400") != plain_400 and _spine_px("GMM_230") == dimmed_230)
FILTER[:] = [fl.Mark("GMM_400", fl.OLD_LOOK_COLOUR, "fill")]
fl.update("probe.filter")
pump()
check("the reserved fill paints like any fill; the filter gone, nothing is dim",
      sp.lit is None and _spine_px("GMM_400") == fl.OLD_LOOK_COLOUR
      and _spine_px("GMM_230") == plain_230)
win.grab().save(os.path.join(out, "lens_old_look.png"))
FILTER[:] = [fl.Mark(subject, fl.OLD_LOOK_COLOUR, "fill")]
fl.update("probe.filter")
pump()
check("the subject on the reserved fill keeps a stroke that shows",
      _spine_px(subject) == fl.OLD_LOOK_COLOUR and _subject_stroke_px(subject) == "#1b1d24")
FILTER[:] = [fl.Mark(subject, fl.OLD_LOOK_COLOUR, "fill"), fl.Mark("GMM_400", None, "dim_rest")]
fl.update("probe.filter")
pump()
check("dimmed, it is white again: the ground is dark",
      _subject_stroke_px(subject) == "#f2f2f2")
fl.unregister_area("probe.filter")
pump()
check("the area gone: the spine as it was", sp.lit is None
      and _spine_px("GMM_400") == plain_400)

# the reserved colour is outside the band every take's colour comes from
import colorsys
_h, _s, _v = colorsys.rgb_to_hsv(*fl._colour(fl.OLD_LOOK_COLOUR).getRgbF()[:3])
check("no take can wear the reserved fill: saturation and value both off the band",
      _s < 0.44 and _v > 0.70)

# the Effects tab: Flame's timeline reads nothing; the walked cut is held
effects_asks = []
fl.register_area("probe.effects", "On Effects", build=lambda p, c: QtWidgets.QLabel("e"),
                 refresh=lambda w, c, m: effects_asks.append((c.asked, c.primary and c.primary.key,
                                                              c.source, c.frame)),
                 tabs=("Timeline", "Effects"))
fl._beat("Timeline")
pump()
e_rect = win.geometry()
e_mode = win.mode
e_seq = seq.seg("GMM_400")
e_clip, e_now = flame.timeline.clip, seq._now
win.follower.pin_keys(["GMM_230"])
fl._beat("Timeline")
check("current_sequence: the sequence walked", fl.current_sequence() is seq)
e_walks = []
e_real_walk = win.follower.tl.walk
win.follower.tl.walk = lambda s: (e_walks.append(1), e_real_walk(s))[1]
flame.timeline.clip, flame.timeline.current_segment = None, None
e_seq.selected = True
del effects_asks[:]
fl._beat("Effects")
pump()
check("on Effects: same place and layout, the spine and the cut still there",
      win.tab == "Effects" and win.isVisible() and win.geometry() == e_rect
      and win.mode == e_mode and win.spine.isVisible() and bool(win.spine.cut))
check("on Effects: the selected segment is the subject, over the pin, and says so",
      win.follower.ctx.primary.key == "GMM_400" and win.follower.ctx.source == "effect"
      and "selected in Effects" in win._subject.text()
      and effects_asks[-1] == ("tab", "GMM_400", "effect", None))
check("on Effects: no follow button, no playhead line, a Timeline-only area hidden",
      not win._follow_btn.isVisible() and win.spine.frame is None
      and not win.frames["streams.versions"].isVisible()
      and win.frames["probe.effects"].isVisible())
check("on Effects: the sequence held", fl.current_sequence() is seq)
win.grab().save(os.path.join(out, "lens_effects.png"))
e_pin = list(win.follower.pinned)
win.pick("GMM_230")
win.focus("GMM_230")
win.scrub(86600, done=True)
fl.scrub(86600)
pump()
check("on Effects: the spine and the verbs move nothing and change no pin",
      seq._now == e_now and win.follower.pinned == e_pin and win.follower.spine is False)
seq._now = fakeflame.Time(e_now.frame + 7)
del effects_asks[:]
fl._beat("Effects")
fl._beat("Effects")
fl._beat("Effects")
pump()
check("on Effects: no walk, however many beats, and the subject settles once",
      not e_walks and win.follower.ctx.settled
      and [a[0] for a in effects_asks] == ["settled"])
e_seq.selected = False
seq.seg("GMM_230").selected = True
del effects_asks[:]
fl._beat("Effects")
pump()
check("on Effects, the open segment moves: the subject and the areas follow",
      win.follower.ctx.primary.key == "GMM_230" and "GMM_230" in win._subject.text()
      and effects_asks[:1] == [("subject", "GMM_230", "effect", None)])
seq.seg("GMM_230").selected = False
fl._beat("Effects")
check("on Effects, none selected: the subject stays",
      win.follower.ctx.primary.key == "GMM_230")
seq._now = e_now
flame.timeline.clip = e_clip
fl._beat("Timeline")
pump()
check("back on the Timeline: read again once, the pin back, the place the same",
      len(e_walks) == 1 and win.follower.ctx.source == "pin"
      and win.follower.ctx.primary.key == "GMM_230" and win.tab == "Timeline"
      and win.geometry() == e_rect and win._follow_btn.isVisible()
      and win.spine.frame is not None)
# closed, then opened on Effects: another sequence may be open, so it holds none
win.follower.tl.walk = e_real_walk
win.follower.pin_keys([])
fl._beat("Timeline")
fl.close()
check("closed: no sequence held", fl.current_sequence() is None)
flame.timeline.clip = None
flame.get_current_tab = lambda: "Effects"
fl.open()
pump()
check("opened on Effects after a close: nothing held, and it says what to do",
      fl.current_sequence() is None and win.tab == "Effects"
      and not win.follower.ctx.segments and win.follower.ctx.sequence is None
      and "open the Lens on the Timeline" in win._subject.text())
del flame.get_current_tab
flame.timeline.clip = e_clip
fl._beat("Timeline")
pump()
check("a beat on the Timeline: held again", fl.current_sequence() is seq
      and win.tab == "Timeline" and win.isVisible())
win._said_follow()
fl.unregister_area("probe.effects")
fl._beat("Timeline")
pump()

# a double-click on any pen: Qt's, or two releases timed
import time as _time
from PySide6 import QtGui as _QtGui
_pad = QtWidgets.QLabel("double")
_pad.resize(100, 40)
_said = []
fl.on_release(_pad, lambda: _said.append("click"))
fl.on_double(_pad, lambda: _said.append("double"))


def _send(kind, x=10, button=QtCore.Qt.LeftButton):
    pos = QtCore.QPointF(x, 10)
    QtWidgets.QApplication.sendEvent(_pad, _QtGui.QMouseEvent(
        kind, pos, pos, button,
        QtCore.Qt.NoButton if kind == QtCore.QEvent.MouseButtonRelease else button,
        QtCore.Qt.NoModifier))


def _tap(x=10):
    _send(QtCore.QEvent.MouseButtonPress, x)
    _send(QtCore.QEvent.MouseButtonRelease, x)


def _apart():
    _time.sleep(QtWidgets.QApplication.doubleClickInterval() / 1000 + 0.05)
    del _said[:]


_apart()
_tap()
_tap()
check("a pen's two taps, plain presses: a click, then the double", _said == ["click", "double"])
_apart()
_tap()
_send(QtCore.QEvent.MouseButtonDblClick)
_send(QtCore.QEvent.MouseButtonRelease)
check("a mouse's double-click, Qt's: a click, then the double, once",
      _said == ["click", "double"])
_apart()
_tap()
_tap()
_tap()
check("a third tap starts again", _said == ["click", "double", "click"])
_apart()
_tap(10)
_tap(80)
check("two taps far apart: two clicks", _said == ["click", "click"])
_apart()
_tap()
_time.sleep(QtWidgets.QApplication.doubleClickInterval() / 1000 + 0.05)
_tap()
check("two taps slow: two clicks", _said == ["click", "click"])
_apart()
_tap()
_tap(150)
check("a second release outside it: nothing more", _said == ["click"])

# two folds: a mark each, the title toggles, a saved "minimal" reads as expanded
_folded = win.frames["takes.takes"]
_folded.set_fold("expanded")
check("an area has two marks, collapsed and expanded",
      [m.fold for m in _folded._marks] == ["collapsed", "expanded"])
_folded.cycle()
pump()
check("the title collapses it", _folded.fold == "collapsed" and not _folded.content.isVisible())
_folded.cycle()
pump()
check("and opens it again", _folded.fold == "expanded" and _folded.content.isVisible())
_saved = fl._load_state().get("fold") or {}
_saved.setdefault(win.mode, {})["takes.takes"] = "minimal"
fl._save_state(fold=_saved)
check("a saved minimal reads as expanded", _folded.fold == "expanded")
_folded.cycle()
pump()
check("and the next click collapses it, nothing raised", _folded.fold == "collapsed")
_folded.set_fold("expanded")
pump()

# a mark from a newer area, or a broken one, is skipped -- never raised
fl.register_area("probe.odd", "Odd", build=lambda p, c: QtWidgets.QLabel("o"),
                 refresh=lambda w, c, m: None,
                 overlay=lambda c: [fl.Mark("GMM_400", "#ffffff", "sparkle", {"x": 1}),
                                    ("too", "many", "fields", "for", "a", "mark"),
                                    fl.Mark("GMM_400", "#298587", "fill")])
fl.preview("probe.odd", [fl.Mark("GMM_400", None, "outline", 7)], None)
pump()
win.grab()
check("unknown marks are skipped, the good one still drawn",
      win.frames["probe.odd"]._guard.isHidden() and sp.fills.get("GMM_400") == "#298587")
fl.preview("probe.odd", None)
fl.unregister_area("probe.odd")
pump()

# a menu's window: only Cocoa has an NSView behind winId() to message
class SpyMenu(QtWidgets.QMenu):
    asked = 0

    def winId(self):
        SpyMenu.asked += 1
        return QtWidgets.QMenu.winId(self)


spy_btn = QtWidgets.QPushButton("Views", win)
spy = SpyMenu(spy_btn)
spy.addAction("In Flight")
fl.popup_under(spy_btn, spy)
pump()
check("off Cocoa popup_under opens the menu and leaves its window alone",
      spy.isVisible() and SpyMenu.asked == 0)
spy.close()
spy_btn.setParent(None)
spy_btn.deleteLater()

# hold(): a tool acting on the Timeline -- Flame's moves are not the artist's
flame.timeline.current_segment = seq.seg("GMM_230")
fl._beat("Timeline")
pump()
before = (win.follower.ctx.source, win.follower.ctx.primary.key)
with fl.hold():
    flame.timeline.current_segment = seq.seg("GMM_400")   # the switch's saves
    seq._now = fakeflame.Time(86452)
    for _ in range(3):
        fl._beat("Timeline")
    during = (win.follower.ctx.source, win.follower.ctx.primary.key)
pump()
after = (win.follower.ctx.source, win.follower.ctx.primary.key)
check("hold(): nothing moves while held, and the release takes none of it as a click",
      before == ("click", "GMM_230") and during == before and after == before)

# the live segment from the last walk
g400_obj = fl.segment("GMM_400")
check("segment(key) is the live segment of the last walk",
      g400_obj is seq.seg("GMM_400") and fl.segment("no such shot") is None)
g400_obj.record_in = fakeflame.Time(g400_obj.record_in.frame + 5)
check("segment(key) is None once the timeline was edited since the walk",
      fl.segment("GMM_400") is None)
g400_obj.record_in = fakeflame.Time(g400_obj.record_in.frame - 5)

win.set_mode("wide")
win.resize(1500, 1100)
pump()
win.grab().save(os.path.join(out, "lens_wide.png"))


# --- Depends against the standalone Segment Lens, pixel for pixel ----------------------

def compare(mode, width):
    class Panel(object):
        shown = None

        def snapshot(self):
            return graph_state
    alone = ui_seglens.SegmentLensWindow(lambda: Panel())
    alone.set_mode(mode)
    alone.resize(width, 1200)
    alone.show()
    alone.refresh(graph_state)
    pump()
    win.set_mode(mode)
    frame = win.frames["streams.depends"]
    win.resize(width, 1600)
    pump()
    mine = frame.content
    theirs = alone._scroll.widget()
    # the same width for both canvases: move the standalone window by the gap
    for _ in range(3):
        gap = mine.width() - theirs.width()
        if not gap:
            break
        alone.resize(alone.width() + gap, alone.height())
        alone.refresh(graph_state)
        pump()
        theirs = alone._scroll.widget()
    a, b = mine.grab().toImage(), theirs.grab().toImage()
    a.save(os.path.join(out, "depends_{0}_hosted.png".format(mode)))
    b.save(os.path.join(out, "depends_{0}_standalone.png".format(mode)))
    # the standalone canvas is stretched to its viewport, the rest of it
    # empty: compare what the hosted one draws, then that the rest is empty
    drawn = b.copy(0, 0, a.width(), a.height())
    empty = all((b.pixel(x, y) >> 24) == 0 for y in range(a.height(), b.height(), 3)
                for x in range(0, b.width(), 3))
    check("Depends {0}: canvas {1}x{2} pixel-identical to the standalone's ({3}x{4}, "
          "empty below)".format(mode, a.width(), a.height(), b.width(), b.height()),
          a.width() == b.width() and a == drawn and empty)
    alone.close()


if graph_state is not None:
    win.frames["streams.depends"].set_fold("expanded")
    compare("narrow", 400)
    compare("wide", 1500)

print("rendered to", out, "-", "all checks passed" if not failures else
      "{0} FAILED".format(len(failures)))
sys.exit(1 if failures else 0)
