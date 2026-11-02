# forge_lens.py
# ---------------------------------------------------------------------------
# FORGE LENS -- the one Lens: a shared window that each distro registers
# *areas* into (forge-hud#1, contract r3).
#
# The rail (forge_hud) is one dock where each distro registers a row. The
# Lens is the same idea one level up: one window, owned here, where each
# distro registers an area -- Takes (forge-takes), Versions and Depends
# (forge-streams), later the Cut and the Batch tab's lenses. The window owns
# what they share, once:
#
#   * the SUBJECT -- the sequence and its segment(s), read on forge_hud's
#     heartbeat and handed to every area as a context. The last thing the
#     artist did wins: the pin; a selection; a segment clicked in the
#     timeline, until the playhead moves; else the playhead's top picture
#     from the FOCUSED track (seq.primary_track) down, as Flame sees it. Areas
#     never read the timeline to find out where they are;
#   * the SPINE -- the cut, drawn small, at the top. One painter. Areas
#     contribute overlays and previews (marks) to it, never a cut of their
#     own. Its playhead line (and the tab on it) drags to scrub; a click on
#     a segment puts the playhead on it and pins the Lens there;
#   * the WINDOW -- forge-streams' LensWindow chrome, moved here: frameless
#     Qt.Tool, dragged by its header, sized by outline grips applied on
#     release, narrow or wide, each placed where it was last left, hidden
#     off-tab and back, off the keyboard;
#   * the CRASH RULES, enforced once -- no timer of its own (the heartbeat
#     only), no event filters but the host's own (on_release, on_double,
#     the pen watch, the header hover), nothing inside a click (later), no
#     network mount touched on Flame's thread (read), and no thread of ours
#     ever calls flame.schedule_idle_event (on_main).
#
# API (what a distro calls):
#
#   import forge_lens
#   forge_lens.register_area(
#       "takes.takes",           # stable id: "<distro>.<area>"; replaces by id
#       title="Takes",
#       tabs=("Timeline",),
#       build=build,             # (parent QWidget, ctx) -> QWidget
#       refresh=refresh,         # (widget, ctx, mode) -> None; mode narrow|wide
#       summary=summary,         # (ctx) -> {"html", "tone"}: the collapsed line
#       overlay=None,            # (ctx) -> [Mark]: always on the spine
#       extent=None,             # (ctx) -> (first, last, tracks) | None
#       effects=None,            # (ctx) -> {shot_key: [Effect]}: cross-reading
#       tools=(),                # header tools: [(label, menu_fn, tone_fn)]
#       follows=(),              # area ids whose update() refreshes this one
#       wide=False)              # may this area draw wide
#   forge_lens.open() / toggle() / close() / is_open()
#   forge_lens.opener_installed()  # True: FORGE > One Lens… and the rail's
#                                  # One Lens… open it -- drop your own entry
#   forge_lens.focus(key)        # the playhead to key, key the subject till it moves
#   forge_lens.scrub(frame)      # the playhead, as the spine's drag moves it
#   forge_lens.segment(key)      # the live PySegment from the last walk, or None
#   with forge_lens.hold(): ...  # a tool acting on the Timeline: ignore it till done
#
# refresh(widget, ctx, mode): ctx.asked says why -- "subject", "settled",
# "refresh", "update", "layout", "fold" or "build" (ASKED). An area that
# reads from disk only on some redraws on the rest.
#   forge_lens.update(area_id)   # this area's state changed (None = all)
#   forge_lens.preview(area_id, marks | None, caption=None)
#   forge_lens.same_as(area_id, key, signature) -> [(area_id, label)]
#   forge_lens.later(fn)         # Flame's idle queue -- Flame's thread only
#   forge_lens.on_main(fn)       # Flame's thread from ANY thread (a poster)
#   forge_lens.read(fn, then, key=None, late=None, wait=READ_WAIT, area=None)
#   forge_lens.on_release(widget, fn) / on_double(widget, fn)
#   forge_lens.popout(area_id, beside, content)
#   forge_lens.state(area_id, mode) -> dict, saved as it is written
#   forge_lens.host(area_id)     # the area's AreaHost (see below)
#
# The AreaHost is LensWindow's own surface, per area, so an area drawn for
# the standalone Segment Lens (forge-streams' ui_seggraph.SegmentGraph) is
# hosted unchanged: mode, _scroll (setWidget / widget / ensureWidgetVisible),
# _popout, _pop, _close_popout, _redraw_later, _do, follow_link, hover_link,
# reveal, _set_title, _panel, STATE_PREFIX and refresh(state=None). An area
# may hang its own attributes on it (views, redraw, link, hover).
#
# Heartbeat: forge_hud >= 1.10's listen(). Without it the window still draws
# and Refresh works; it just doesn't follow the timeline.
#
# Per-user state -- placements, layout, folding, hidden areas, follow --
# persists in ~/.forge_lens.json.
# ---------------------------------------------------------------------------

import builtins
import json
import os
import re
import threading
from collections import namedtuple

__version__ = "0.4.1"

STATE_PATH = os.path.join(os.path.expanduser("~"), ".forge_lens.json")

#: How long a read waits before its area is told the disk hasn't answered:
#: forge-streams' seglens.READ_WAIT.
READ_WAIT = 5.0

#: The tabs the window belongs on when no area says otherwise.
DEFAULT_TABS = ("Timeline",)

# FORGE family colours (forge-streams ui_lens / ui_seglens, forge-takes).
EMBER = "#E87E24"
AMBER = "#E8B04A"
BLUE = "#4A9EE8"
READ = "#9aa3b5"
GOOD = "#7fbf7f"
BAD = "#e57266"
DIM = "#8a93a4"
FAINT = "#5c6270"
PANEL = "#282c34"
WELL = "#1e2028"
RULE = "#3a3f4f"
RAISED = "#2f3440"
RAISED_RULE = "#4a5062"
ROUND = 12
#: Tones: the state of a thing. Take colours fill; tones stroke (r3).
TONE = {"good": GOOD, "neutral": DIM, "info": BLUE, "warn": AMBER, "bad": BAD}
TONES = ("good", "neutral", "info", "warn", "bad")
#: Main's colour, as forge-takes draws it (Main has none stored).
MAIN_COLOUR = "#6b7080"
#: A segment on the spine no area has coloured.
UNCOLOURED = RAISED_RULE
FOLDS = ("collapsed", "minimal", "expanded")
NARROW_WIDTH = 340


# --- the contract's small types ---------------------------------------------

#: A segment as every area sees it. key: posting._keyed / timeline.shot_keys;
#: name: the label (a repeated name with its track, ``GMM_430 · V2``);
#: track: 0-based; record_in/record_out: frames, both included; version: its
#: version_uid (a getter) or None; kind: "picture" | "fx_gap".
Seg = namedtuple("Seg", "key name track record_in record_out version kind")
#: A mark on the spine: colour a take colour (rgbF tuple or "#hex") or None;
#: style "fill" | "outline" | "dashed" | "dim_rest" | "band"; at (track, in,
#: out) a ghost where a shot the cut no longer has used to be. A "band" is a
#: thin bar in *colour* over the shot's span, ABOVE the tracks, in row *at*
#: (an int, 0 nearest the tracks): forge-takes' groups, one row per take.
Mark = namedtuple("Mark", "key colour style at", defaults=(None, "outline", None))
#: One verb's result on one shot: label as the area says it, signature the
#: shot's resulting stack -- tuple((type, bypassed, fxprint), ...).
Effect = namedtuple("Effect", "label signature")


class Ctx(object):
    """The context every area is handed. Plain attributes, never live Flame
    objects: tab, sequence, sequence_uid, tags, segments, primary, source,
    pinned, settled, playing, frame, over, visible, shots (+ cut, in cut
    order), and asked -- why this refresh, set just before each area's
    refresh / summary / effects (else None): one of ASKED."""

    __slots__ = ("tab", "sequence", "sequence_uid", "tags", "segments", "primary",
                 "source", "pinned", "settled", "playing", "frame", "over",
                 "visible", "shots", "cut", "asked")

    def __init__(self, **kw):
        for name in self.__slots__:
            setattr(self, name, kw.get(name))
        for name in ("tags", "segments", "over", "cut"):
            if getattr(self, name) is None:
                setattr(self, name, ())
        if self.shots is None:
            self.shots = {}

    def subject(self):
        """What moving means: the keys, the primary and its version."""
        p = self.primary
        return (self.sequence_uid, tuple(s.key for s in self.segments),
                p.key if p else None, p.version if p else None)

    def __repr__(self):
        p = self.primary
        return "Ctx({0} {1} {2}{3})".format(self.sequence, self.source,
                                            p.name if p else None,
                                            " settled" if self.settled else "")


#: Why an area is refreshed (ctx.asked): the subject moved (or the sequence);
#: it settled; Refresh; update() of it or of an area it follows; the window
#: went narrow/wide; its fold changed; it was just built (registered, or
#: re-registered live). An area that reads only on some of these redraws on
#: the rest -- and treats a value it doesn't know as a reason to read.
ASKED = ("subject", "settled", "refresh", "update", "layout", "fold", "build")


# --- process-global anchor (survives reloads) -------------------------------

def _anchor():
    """The registry, the window and the poster, parked on ``builtins`` --
    for the reason forge_hud parks its own there: PySide can garbage-collect
    the QApplication's Python wrapper, attributes and all."""
    held = getattr(builtins, "_forge_lens_state", None)
    if held is None:
        held = {"areas": {}, "order": [], "window": None, "poster": None,
                "previews": {}, "effects": {}, "reads": {}, "away": False,
                "gen": 0}
        builtins._forge_lens_state = held
    return held


# --- per-user state file ----------------------------------------------------

def _load_state():
    try:
        with builtins.open(STATE_PATH) as fh:      # open() is the Lens's verb
            found = json.load(fh)
        return found if isinstance(found, dict) else {}
    except Exception:
        return {}


def _save_state(**changes):
    try:
        st = _load_state()
        st.update(changes)
        with builtins.open(STATE_PATH, "w") as fh:
            json.dump(st, fh)
    except Exception:
        pass                      # a Lens must never break an action


class _Saved(dict):
    """An area's own state for one layout: saved as it is written."""

    def __init__(self, area_id, mode, data):
        dict.__init__(self, data)
        self._where = (area_id, mode)

    def _write(self):
        areas = _load_state().get("areas") or {}
        area_id, mode = self._where
        areas.setdefault(area_id, {})[mode] = dict(self)
        _save_state(areas=areas)

    def __setitem__(self, k, v):
        dict.__setitem__(self, k, v)
        self._write()

    def __delitem__(self, k):
        dict.__delitem__(self, k)
        self._write()

    def update(self, *a, **kw):
        dict.update(self, *a, **kw)
        self._write()


def state(area_id, mode):
    """*area_id*'s own state for layout *mode* -- its folding, its views --
    a dict saved to ~/.forge_lens.json as it is written."""
    saved = ((_load_state().get("areas") or {}).get(area_id) or {}).get(mode) or {}
    return _Saved(area_id, mode, saved if isinstance(saved, dict) else {})


# --- the pen log ------------------------------------------------------------

def _pen(what, event=None):
    """A line in forge_hud's pen log (1.8.1+), when it has one."""
    try:
        import forge_hud          # noqa: PLC0415
        note = getattr(forge_hud, "pen_note", None)
        if note is not None:
            note("lens", what, event)
    except Exception:
        pass


# --- Flame's thread ---------------------------------------------------------
# flame.schedule_idle_event called from a thread of ours deadlocked Flame
# [LIVE 2027.1, 2026-10-26, the Segment Lens on WTR_060]: our thread held
# Python's lock and waited in PyEditdeskUtils::scheduleIdleEvent for the idle
# queue's; Flame's thread held the idle queue's (IdleEventQueue::run) and
# waited in CoPythonObj::~CoPythonObj for Python's. So no thread of ours
# calls it: a worker posts a queued Qt signal to an object on Flame's thread
# -- Qt posts it holding no lock the receiver needs -- and THERE the idle
# event is scheduled. forge-streams' mainthread.on_main, moved here.

def _idle_here(fn):
    """*fn* when Flame is next idle -- asked on Flame's thread; at once with
    no scheduler (outside Flame)."""
    try:
        import flame              # noqa: PLC0415
        flame.schedule_idle_event(fn)
    except Exception:
        fn()


_POSTER_LOCK = threading.Lock()


def _poster():
    try:
        from PySide6 import QtCore    # noqa: PLC0415
    except Exception:
        return None
    app = QtCore.QCoreApplication.instance()
    if app is None:
        return None
    st = _anchor()
    with _POSTER_LOCK:
        if st.get("poster") is None:
            class Poster(QtCore.QObject):
                call = QtCore.Signal(object)

                @QtCore.Slot(object)
                def run(self, fn):
                    _idle_here(fn)

            poster = Poster()
            poster.moveToThread(app.thread())   # its slot runs on Flame's thread
            poster.call.connect(poster.run, QtCore.Qt.QueuedConnection)
            st["poster"] = poster
        return st["poster"]


def on_main(fn):
    """*fn* on Flame's thread when it is next idle, asked from ANY thread;
    at once outside Flame."""
    try:
        import flame              # noqa: F401, PLC0415
    except Exception:
        fn()
        return
    poster = _poster()
    if poster is None:
        _idle_here(fn)
        return
    poster.call.emit(fn)


def later(fn):
    """Run *fn* on Flame's idle queue, guarded, then repaint the window --
    never inside the click that asked for it (forge-takes crash #15). Call
    it from Flame's thread only; a worker uses on_main()."""
    def run():
        try:
            fn()
        except Exception as exc:
            _pen("later failed: {0!r}".format(exc))
        win = _anchor().get("window")
        if win is not None:
            try:
                win.update()
            except Exception:
                pass
    _idle_here(run)


def read(fn, then, key=None, late=None, wait=READ_WAIT, area=None):
    """*fn* on a worker thread -- file I/O only, never ``flame`` or Qt -- and
    *then(result)* back on Flame's thread as soon as it returns (on_main).
    A newer read with the same *key* drops an older one's result. *late()*
    is called once, on Flame's thread, when *fn* hasn't answered within
    *wait* seconds. If *fn* raises, *area*'s guard line says so and *then*
    isn't called."""
    st = _anchor()
    st["gen"] += 1
    gen = st["gen"]
    if key is not None:
        st["reads"][key] = gen
    done = threading.Event()

    def current():
        return key is None or _anchor()["reads"].get(key) == gen

    def work():
        try:
            result, error = fn(), None
        except Exception as exc:            # noqa: BLE001
            result, error = None, exc
        done.set()

        def back():
            if not current():
                return
            if error is not None:
                _guard_line(area, "read", error)
                return
            try:
                then(result)
            except Exception as exc:
                _guard_line(area, "read", exc)
        on_main(back)

    threading.Thread(target=work, name="forge-lens-read", daemon=True).start()
    if late is not None:
        def watch():
            if not done.wait(wait):
                on_main(lambda: current() and not done.is_set() and late())
        threading.Thread(target=watch, name="forge-lens-late", daemon=True).start()


# --- the cut, from the timeline (no Qt) ------------------------------------

def shot_keys(rows):
    """Each keyed shot of *rows* -- one dict per segment of the patched
    version, in track then record order -- by its key and its place in
    *rows*. Line for line forge-streams' posting._keyed(rows, 0) and
    forge-takes' timeline.shot_keys, which every record and take is keyed
    by: keep it so (a test pins it against both)."""
    out, seen = [], set()
    for i, s in enumerate(rows):
        if not (s.get("media") or s.get("effects")):
            continue
        key = (s.get("segment") or s.get("shot")
               or "{0} {1} at {2}".format("track" if s.get("media") else "gap on track",
                                          s.get("track", 0) + 1, s.get("record_in")))
        if key in seen:
            key = "{0} (track {1})".format(key, s.get("track", 0) + 1)
        if key not in seen:
            seen.add(key)
            out.append((key, i))
    return out


_TRACKED_KEY = re.compile(r"^(.*) \(track \d+\)$")


def segment_base(key):
    """*key*'s name without the track a repeat was keyed by."""
    m = _TRACKED_KEY.match(key)
    return m.group(1) if m else key


def label(key, track, kind, keys_by_base):
    """*key* as the artist knows it -- forge-takes' segment_label rule
    (18847b0): its name alone when it is the cut's only one by that name,
    else ``GMM_430 · V2``; never the key's ``GMM_430 (track 2)``. A gap is
    said by its track, as an unnamed segment is."""
    if kind == "fx_gap":
        return "Gap on track {0}".format(track + 1)
    if key.startswith("track ") and " at " in key:
        return "Track {0}".format(track + 1)
    base = segment_base(key)
    twins = keys_by_base.get(base, 1) > 1
    return "{0} · V{1}".format(base, track + 1) if twins else base


def _v(x):
    """A Flame PyAttribute's value, or *x*."""
    return x.get_value() if hasattr(x, "get_value") else x


def _frame(t):
    return int(_v(t).frame)


def _s(x):
    return str(_v(x) or "")


class Cut(object):
    """The patched version's keyed segments, top track last -- walked once
    per click, sequence change or Refresh, never per heartbeat."""

    def __init__(self, segs, objects=None, name="", uid="", tags=(), start=0, tracks=()):
        self.segs = list(segs)
        self.by_key = dict((s.key, s) for s in self.segs)
        self.objects = dict(objects or {})
        self.track_objs = list(tracks)      # the walked version's PyTracks, by index
        self.name, self.uid, self.tags, self.start = name, uid, tuple(tags), start
        self.tracks = (max(s.track for s in self.segs) + 1) if self.segs else 0
        self.lo = min(s.record_in for s in self.segs) if self.segs else 0
        self.hi = max(s.record_out for s in self.segs) if self.segs else 0

    @classmethod
    def from_rows(cls, rows, objects=(), **kw):
        """*rows* as forge-takes' TimelineHost walks them (``segment``,
        ``shot``, ``media``, ``effects``, ``track``, ``record_in``,
        ``record_out``, ``gap``), each with its live segment in *objects*."""
        keyed = shot_keys(rows)
        bases = {}
        for key, i in keyed:
            if not rows[i].get("gap"):
                b = segment_base(key)
                bases[b] = bases.get(b, 0) + 1
        segs, objs = [], {}
        for key, i in keyed:
            r = rows[i]
            kind = "fx_gap" if r.get("gap") else "picture"
            segs.append(Seg(key, label(key, r.get("track", 0), kind, bases), r.get("track", 0),
                            int(r["record_in"]), int(r["record_out"]), r.get("version"), kind))
            if i < len(objects):
                objs[key] = objects[i]
        return cls(segs, objs, **kw)

    def at(self, frame):
        """Every segment covering *frame*, top track first."""
        return sorted((s for s in self.segs if s.record_in <= frame <= s.record_out),
                      key=lambda s: -s.track)

    def top_picture(self, frame, below=None):
        """The top PICTURE segment at *frame*: a gap that only carries an
        effect works like an adjustment layer -- it is the answer only when
        nothing else is there [LIVE 2027.1, 2026-11-01: LINKTEST2's track 3
        Gap Timeline FX over the whole cut; forge-hud#1]. *below*: only
        tracks at or below that one, as Flame's player sees from the
        focused track down."""
        here = [s for s in self.at(frame) if below is None or s.track <= below]
        for s in here:
            if s.kind == "picture":
                return s
        return here[0] if here else None

    def on_track(self, track, frame):
        """The picture segment on *track* at *frame*, or None (a gap there)."""
        return next((s for s in self.at(frame) if s.track == track and s.kind == "picture"),
                    None)

    def under_playhead(self, frame, focus=None):
        """The subject the playhead gives, as Flame sees it: from the
        focused track DOWN -- the top picture at or below it at *frame*,
        tracks above ignored [Chris, 2026-11-01: "the playhead can be over
        something, a second layer, and be reading that when the focus is
        actually on the track beneath"; and, of an empty focused track,
        "it doesn't look down ... Contrary to how flame works itself"].
        Nothing at or below the focus is nothing, as Flame shows black
        there. No focus known: the top picture."""
        if frame is None:
            return None
        return self.top_picture(frame, below=focus)

    def over(self, seg, frame):
        """What is stacked over *seg* at *frame* (else its first frame), top
        first, effect-only gaps included."""
        f = frame if frame is not None and seg.record_in <= frame <= seg.record_out \
            else seg.record_in
        return [s for s in self.at(f) if s.track > seg.track]


class Timeline(object):
    """Every Flame read the Lens makes, in one place -- injectable (a test's
    fake ``flame``). Each method is guarded and cheap unless it says not."""

    def __init__(self, flame_module=None):
        self._flame = flame_module

    @property
    def flame(self):
        if self._flame is None:
            import flame          # noqa: PLC0415
            self._flame = flame
        return self._flame

    def sequence(self):
        try:
            return self.flame.timeline.clip
        except Exception:
            return None

    def uid(self, seq):
        try:
            return _s(seq.uid)
        except Exception:
            return ""

    def clicked(self):
        """``timeline.current_segment`` -- the last segment clicked; the
        positioner doesn't move it [LIVE 2026.2.2] -- as (name, record in):
        the cheap sign that a click happened."""
        try:
            seg = self.flame.timeline.current_segment
            return None if seg is None else (_s(seg.name), _frame(seg.record_in))
        except Exception:
            return None

    def frame(self, seq):
        try:
            return _frame(seq.current_time)
        except Exception:
            return None

    def version_of(self, obj):
        try:
            return str(_v(obj.version_uid)) or None
        except Exception:
            return None

    def _primary(self, seq):
        track = _v(seq.primary_track)
        if track is not None:
            for version in seq.versions:
                if any(t == track for t in version.tracks):
                    return version
        return list(seq.versions)[0]

    def walk(self, seq):
        """The cut (NOT cheap: every segment). On a click, a sequence change,
        a Refresh -- never per heartbeat."""
        rows, objs = [], []
        try:
            version = self._primary(seq)
            tracks = list(version.tracks)
        except Exception:
            return Cut([])
        for ti, track in enumerate(tracks):
            for seg in track.segments:
                try:
                    gap = str(seg.type).startswith("Gap")
                    try:
                        effects = bool(list(seg.effects))
                    except Exception:
                        effects = False
                    rows.append({"track": ti, "record_in": _frame(seg.record_in),
                                 "record_out": _frame(seg.record_out),
                                 "segment": _s(seg.name),
                                 "shot": "" if gap else _s(getattr(seg, "shot_name", "")),
                                 "media": "" if gap else _s(getattr(seg, "file_path", "")),
                                 "effects": effects, "gap": gap})
                    objs.append(seg)
                except Exception:
                    continue
        try:
            tags = [str(t) for t in (_v(seq.tags) or ())]
        except Exception:
            tags = []
        try:
            start = _frame(seq.start_time)
        except Exception:
            start = 0
        return Cut.from_rows(rows, objs, name=_s(seq.name), uid=self.uid(seq), tags=tags,
                             start=start, tracks=tracks)

    def focused(self, seq, cut):
        """The focused track -- ``seq.primary_track``, the patch the artist
        sets -- as (index in *cut*'s version, track). Index None: no focus,
        or a track of another version than the one walked (walk again).
        Flame's player shows this track and those beneath it. Cheap: one
        getter and a few comparisons; PyTrack == holds across
        reads [LIVE 2027.1, 2026-11-01: ~1 us on TST_publish's 5 tracks]."""
        try:
            track = _v(seq.primary_track)
        except Exception:
            return None, None
        if track is None:
            return None, None
        for i, t in enumerate(cut.track_objs):
            try:
                if t == track:
                    return i, track
            except Exception:
                continue
        return None, track

    def clicked_key(self, cut, clicked):
        """The key of the segment last clicked in the timeline: by the
        segment itself (PySegment == holds [LIVE 2027.1, 2026-11-01]), else
        by (name, record in)."""
        try:
            seg = self.flame.timeline.current_segment
        except Exception:
            seg = None
        if seg is not None:
            for key, obj in cut.objects.items():
                try:
                    if obj == seg:
                        return key
                except Exception:
                    continue
        if clicked is None:
            return None
        return next((s.key for s in cut.segs
                     if (segment_base(s.key), s.record_in) == (clicked[0], clicked[1])), None)

    def selected(self, cut):
        """The keys selected in the Timeline, in cut order. A segment's
        ``selected`` is a PyAttribute, not in dir() [LIVE 2027.1]. Visits
        every segment: only after a click."""
        out = []
        for s in cut.segs:
            obj = cut.objects.get(s.key)
            try:
                if obj is not None and _v(obj.selected):
                    out.append(s.key)
            except Exception:
                continue
        return out

    def move_to(self, seq, frame, start=0):
        """The positioner on record *frame*. PyTime(n) is the sequence's
        n-th frame counted from 1 at its start_time: PyTime(350) landed on
        86749 with a start of 86400 [LIVE 2027.1, 2026-11-01, forge-takes
        ca29de6] -- so frame - start + 1, not frame - start."""
        seq.current_time = self.flame.PyTime(int(frame) - int(start) + 1)


class Follower(object):
    """The subject, on the heartbeat. The last thing the artist did wins
    [Chris, 2026-11-01]:

    - the pin, over everything;
    - a selection, while there is one;
    - a segment clicked in the timeline (source "click"), until the
      playhead next moves -- a plain click selects nothing in Flame;
    - else the playhead: the top picture at its frame from the focused
      track down, as Flame's player sees it (``Cut.under_playhead``).

    Using the spine, or focus(), follows the playhead until the next click
    in the timeline. tick() returns (ctx, moved, settled_now, frame_moved)."""

    #: Beats a reveal waits for the playhead to land before it holds anyway.
    LAND_BEATS = 3

    def __init__(self, timeline=None):
        self.tl = timeline or Timeline()
        self.cut = Cut([])
        self.uid = None
        self._clicked = None
        self.selection = []
        self.spine = False            # following the playhead by the spine's say
        self.pinned = None            # keys held, or None
        self._last = None             # the subject last tick
        self._same = 0
        self._frame = None
        self._walk_asked = True
        self._stale = None            # a focused track the walk didn't find
        self.click = None             # the key clicked, held until the playhead moves
        self._click_frame = None      # ...from this frame
        self._click_seen = False      # the playhead has been there
        self._click_wait = 0
        self.focus_track = None       # the focused track's index in the cut
        self.ctx = Ctx()

    def rewalk(self):
        self._walk_asked = True

    def pin(self, on):
        self.pinned = [s.key for s in self.ctx.segments] if on and self.ctx.segments else None

    def pin_keys(self, keys):
        self.pinned = list(keys) or None

    def follow_playhead(self):
        self.spine = True
        self.click = None

    def rebaseline(self):
        """After a hold(): Flame's click, frame and selection as they are
        now, none of it the artist's -- no click, no playhead move, a held
        click kept. The cut is walked again (a switch may have changed it).
        The subject itself is decided on the next tick."""
        seq = self.tl.sequence()
        if seq is None:
            return
        self._clicked = self.tl.clicked()
        self.uid = self.tl.uid(seq)
        self.cut = self.tl.walk(seq)
        self.selection = self.tl.selected(self.cut)
        self._walk_asked = False
        frame = self.tl.frame(seq)
        self._frame = frame
        if self.click is not None:
            self._click_frame, self._click_seen = frame, True

    def reveal(self, key, frame):
        """*key* is the subject, the playhead on its way to *frame*; it holds
        until the playhead moves on from there (focus())."""
        self.spine = True             # over a selection, as a spine use is
        self.click, self._click_frame = key, frame
        self._click_seen, self._click_wait = False, 0

    def tick(self, tab=None):
        seq = self.tl.sequence()
        if seq is None:
            ctx = Ctx(tab=tab)
            moved = self.ctx.subject() != ctx.subject() or self.ctx.sequence is not None
            self.ctx, self.uid = ctx, None
            return ctx, moved, False, False
        uid = self.tl.uid(seq)
        clicked = self.tl.clicked()
        first = uid != self.uid
        click = clicked != self._clicked and not first
        focus, track = self.tl.focused(seq, self.cut)
        stale = focus is None and track is not None and not (
            self._stale is not None and self._stale == track)
        if first or click or self._walk_asked or stale:
            self.cut = self.tl.walk(seq)
            self.selection = self.tl.selected(self.cut)
            self._walk_asked = False
            focus, track = self.tl.focused(seq, self.cut)
            self._stale = track if focus is None else None
            if click:
                self.spine = False    # a click in the timeline ends spine-follow
            if first:
                self.pinned, self.spine, self.click = None, False, None
        self.uid, self._clicked = uid, clicked
        self.focus_track = focus
        cut = self.cut
        frame = self.tl.frame(seq)
        if click:
            # the click wins, even where it moved the positioner this beat
            self.click = self.tl.clicked_key(cut, clicked)
            self._click_frame, self._click_seen = frame, True
        elif self.click is not None:
            if frame == self._click_frame:
                self._click_seen = True
            elif self._click_seen:
                self.click = None     # the playhead moved on: it leads again
            else:
                self._click_wait += 1
                if self._click_wait >= self.LAND_BEATS:   # it never landed
                    self._click_frame, self._click_seen = frame, True
        if self.click is not None and self.click not in cut.by_key:
            self.click = None
        if self.pinned:
            segs, source = [cut.by_key[k] for k in self.pinned if k in cut.by_key], "pin"
        elif self.selection and not self.spine:
            segs, source = [cut.by_key[k] for k in self.selection if k in cut.by_key], \
                "selection"
        elif self.click is not None:
            segs, source = [cut.by_key[self.click]], "click"
        else:
            here = cut.under_playhead(frame, focus)
            segs, source = ([here] if here else []), "playhead"
        primary = None
        if segs:
            # the one last clicked leads a selection, where it is one of them
            if source == "selection" and clicked is not None:
                primary = next((s for s in segs if (segment_base(s.key), s.record_in)
                                == (clicked[0], clicked[1])), None)
            primary = primary or segs[0]
            obj = cut.objects.get(primary.key)
            primary = primary._replace(version=self.tl.version_of(obj) if obj is not None
                                       else None)
            segs = [primary if s.key == primary.key else s for s in segs]
        playing = (frame is not None and self._frame is not None
                   and abs(frame - self._frame) > 1)
        frame_moved = frame != self._frame
        self._frame = frame
        ctx = Ctx(tab=tab, sequence=cut.name, sequence_uid=uid, tags=cut.tags,
                  segments=tuple(segs), primary=primary, source=source,
                  pinned=bool(self.pinned), playing=playing, frame=frame,
                  over=tuple(cut.over(primary, frame)) if primary else (),
                  visible=cut.under_playhead(frame, focus),
                  shots=cut.by_key, cut=tuple(cut.segs))
        subject = ctx.subject()
        moved = subject != self._last or first
        if moved or playing:
            # settled: the same subject AND a still playhead -- a drag or play
            # inside one segment must not settle it, or the flip comes while
            # the areas that wait for a still playhead won't read, and none
            # comes when it stops [LIVE 2027.1, 2026-11-01: Depends stuck on
            # "Reading..." after a positioner drag across TST_040]
            self._same = 0
        else:
            self._same += 1
        self._last = subject
        was = self.ctx.settled
        ctx.settled = self._same >= 2
        self.ctx = ctx
        return ctx, moved, bool(ctx.settled and not was), frame_moved


# --- the registry -----------------------------------------------------------

def register_area(area_id, title, build, refresh, tabs=DEFAULT_TABS, summary=None,
                  overlay=None, extent=None, effects=None, tools=(), follows=(),
                  wide=False):
    """Add or replace an area. Safe at import time (no Qt is touched); a
    second call with the same id swaps the callbacks and rebuilds that
    area's widget in a live window -- its old class may belong to a purged
    module."""
    st = _anchor()
    if area_id not in st["order"]:
        st["order"].append(area_id)
    st["areas"][area_id] = {
        "title": title, "build": build, "refresh": refresh,
        "tabs": tuple(tabs) if tabs else (), "summary": summary, "overlay": overlay,
        "extent": extent, "effects": effects, "tools": tuple(tools or ()),
        "follows": tuple(follows or ()), "wide": bool(wide)}
    win = st.get("window")
    if win is not None:
        try:
            win.rebuild_area(area_id)
        except Exception:
            pass


def unregister_area(area_id):
    st = _anchor()
    st["areas"].pop(area_id, None)
    if area_id in st["order"]:
        st["order"].remove(area_id)
    st["previews"].pop(area_id, None)
    st["effects"].pop(area_id, None)
    win = st.get("window")
    if win is not None:
        try:
            win.drop_area(area_id)
        except Exception:
            pass


def _tabs():
    st = _anchor()
    tabs = set()
    for aid in st["order"]:
        tabs.update(st["areas"].get(aid, {}).get("tabs") or ())
    return tabs or set(DEFAULT_TABS)


def _guard_line(area_id, what, exc):
    """One line in *area_id*'s frame saying what failed; logged. Never
    stops the window or another area."""
    _pen("{0}: {1} failed: {2!r}".format(area_id, what, exc))
    win = _anchor().get("window")
    if win is not None and area_id is not None:
        try:
            win.guard(area_id, what, exc)
        except Exception:
            pass


# --- the public verbs -------------------------------------------------------

def host(area_id):
    """*area_id*'s AreaHost in the open window, or None."""
    win = _anchor().get("window")
    return win.hosts.get(area_id) if win is not None else None


def update(area_id=None):
    """*area_id*'s state changed: refresh it, and the areas that follow it
    (None: every area). Flame's thread."""
    win = _anchor().get("window")
    if win is None:
        return
    try:
        win.update_areas(area_id, asked="update")
    except Exception as exc:
        _pen("update failed: {0!r}".format(exc))


def focus(key):
    """Move the subject to the segment *key*: the positioner to its first
    frame (on Flame's idle queue), *key* the subject until the playhead moves
    on from there -- then the playhead leads, on the focused track."""
    win = _anchor().get("window")
    if win is not None:
        win.focus(key)


def segment(key):
    """The live PySegment for *key*, from the cut the Lens last walked --
    Flame's thread. None when there is no window, no such key, or the
    segment no longer is what the walk saw (its name or record in changed:
    the timeline was edited since, without a click) -- walk it yourself
    then, or update()."""
    win = _anchor().get("window")
    if win is None:
        return None
    cut = win.follower.cut
    seg, obj = cut.by_key.get(key), cut.objects.get(key)
    if seg is None or obj is None:
        return None
    try:
        if _frame(obj.record_in) != seg.record_in:
            return None
        if seg.kind == "picture" and not key.startswith("track "):
            names = (_s(obj.name), _s(getattr(obj, "shot_name", "")))
            if segment_base(key) not in names:
                return None
    except Exception:
        return None                   # a segment the edit deleted
    return obj


def scrub(frame, done=True):
    """The playhead to record *frame*, as the spine's own drag moves it: on
    Flame's idle queue, the latest frame only, the subject following the
    playhead (an area's own playhead line, e.g. takes' wide lanes). With no
    window open, the positioner moves anyway, on the idle queue."""
    win = _anchor().get("window")
    if win is not None:
        win.scrub(int(frame), done=done)
        return
    tl = Timeline()

    def go():
        seq = tl.sequence()
        if seq is not None:
            try:
                start = _frame(seq.start_time)
            except Exception:
                start = 0
            tl.move_to(seq, frame, start)
    later(go)


def preview(area_id, marks, caption=None):
    """While something in *area_id* is hovered: *marks* on the spine and
    *caption* -- (head, [up to 3 lines]) -- under it. None clears both."""
    st = _anchor()
    if marks is None:
        st["previews"].pop(area_id, None)
    else:
        st["previews"][area_id] = (list(marks), caption)
    win = st.get("window")
    if win is not None:
        try:
            win.show_preview()
        except Exception:
            pass


def same_as(area_id, key, signature):
    """The other areas' effects on shot *key* that leave it as *signature*
    does: [(area_id, label)]. A lookup of what the areas published when the
    subject last moved, never a callback."""
    if signature is None:
        return []
    out = []
    for other, by_key in _anchor()["effects"].items():
        if other == area_id:
            continue
        for eff in by_key.get(key, ()):
            if eff.signature == signature:
                out.append((other, eff.label))
    return out


def popout(area_id, beside, content):
    """*content* (a QWidget) popped out under *beside*, the window's one
    popout: closed when the subject moves or the area changes mode."""
    win = _anchor().get("window")
    if win is not None:
        win.popout_widget(area_id, beside, content)


def is_open():
    win = _anchor().get("window")
    try:
        return win is not None and win.isVisible()
    except Exception:
        return False


def open(timeline=None):            # noqa: A001 - the module's verb
    """Show the Lens, built if it isn't; never takes the keyboard."""
    st = _anchor()
    st["away"] = False
    win = st.get("window")
    if win is None:
        if _Window is None:
            return None             # headless
        win = _Window(Follower(timeline))
        st["window"] = win
        win.build_areas()
    _listen()
    win.beat(None, force=True)
    win.show()
    win.raise_()
    return win


def close():
    st = _anchor()
    st["away"] = False
    win = st.get("window")
    if win is not None:
        win.hide()
    _unlisten()


def toggle():
    if is_open():
        close()
        return None
    return open()


# --- a tool acting on the Timeline -------------------------------------------

#: Beats a hold may last before the Lens lets go by itself (~60 s at 600 ms):
#: a hold(True) whose hold(False) never came must not freeze the Lens.
HOLD_BEATS = 100


class _Holding(object):
    def __enter__(self):
        hold(True)
        return self

    def __exit__(self, *_exc):
        hold(False)
        return False


def hold(on=None):
    """A tool is acting on the Timeline: ignore it until it is done
    (forge-takes, forge-hud#1 6568455441). A take switch saves effect
    setups, and Flame moves the playhead, the selection and
    current_segment while it does -- with its event loop running, so the
    heartbeat ticked mid-switch and took those for the artist [LIVE 2027.1,
    2026-11-01: TST_060 selected, the playhead on TST_070, two switches,
    the Lens fell to TST_070].

    ``with forge_lens.hold(): ...``, or hold(True) / hold(False); re-entrant.
    While held the subject, the playhead line and the areas stay as they
    were (update() still redraws an area). On the last release the Lens
    takes Flame's click, frame and selection as they are now, as no action
    of the artist's, and beats once on the idle queue. Flame's thread."""
    if on is None:
        return _Holding()
    st = _anchor()
    was = st.get("held", 0)
    n = was + 1 if on else max(was - 1, 0)
    st["held"] = n
    if on and was == 0:
        st["held_beats"] = 0
    if not on and was > 0 and n == 0:
        _let_go()
    return None


def _let_go():
    win = _anchor().get("window")
    if win is None:
        return
    try:
        win.follower.rebaseline()
    except Exception as exc:
        _pen("hold release failed: {0!r}".format(exc))

    def beat():
        w = _anchor().get("window")
        if w is not None and w.isVisible():
            w.beat(w.follower.ctx.tab)
    later(beat)


def held():
    """Whether a tool holds the Lens (hold())."""
    return _anchor().get("held", 0) > 0


# --- the family's opener ------------------------------------------------------

def opener_installed():
    """True: the Lens is offered by the family -- FORGE > One Lens… on
    Flame's main menu (below) and One Lens… at the foot of every rail menu
    (forge_hud >= 1.11). A distro's own entry steps aside when this says so
    (read it through getattr: an older forge_lens hasn't it)."""
    return True


def _on_lens_tab(_selection=None):
    """The entry is live on a tab the Lens shows on. Fails open."""
    try:
        import flame              # noqa: PLC0415
        return str(flame.get_current_tab()) in _tabs()
    except Exception:
        return True


def _open_from_menu(_selection=None):
    later(open)                   # never inside the menu's click


def get_main_menu_custom_ui_actions():
    """Flame's hook: FORGE > One Lens… -- there whether the rail is or not.
    Flame aggregates groups across hook files (forge-flame-kb D14), so FORGE
    is shared with the distros' own submenus."""
    return [{"name": "FORGE", "hierarchy": [], "actions": [
        {"name": "One Lens…", "order": 1, "execute": _open_from_menu,
         "isEnabled": _on_lens_tab}]}]


def _beat(tab):
    """forge_hud's heartbeat: follow the tab, then the subject."""
    st = _anchor()
    win = st.get("window")
    if win is None:
        return
    here = tab is None or tab in _tabs()
    try:
        if not here:
            if win.isVisible():
                st["away"] = True
                win.hide()
            return
        if st.get("away"):
            st["away"] = False
            win.show()
        if held():
            st["held_beats"] = st.get("held_beats", 0) + 1
            if st["held_beats"] < HOLD_BEATS:
                return                # a tool is acting: Flame's moves aren't the artist's
            _pen("hold never released: let go after {0} beats".format(HOLD_BEATS))
            st["held"] = 0
            _let_go()
            return
        if win.isVisible():
            win.beat(tab)
    except Exception as exc:
        _pen("beat failed: {0!r}".format(exc))


def _listen():
    try:
        import forge_hud          # noqa: PLC0415
        listen = getattr(forge_hud, "listen", None)
        if listen is not None:
            listen("forge_lens", _beat)
            return True
    except Exception:
        pass
    return False


def _unlisten():
    try:
        import forge_hud          # noqa: PLC0415
        if hasattr(forge_hud, "unlisten"):
            forge_hud.unlisten("forge_lens")
    except Exception:
        pass


# --- Qt ---------------------------------------------------------------------

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except Exception:                   # headless: the logic above still works
    QtCore = QtGui = QtWidgets = None


def _colour(c, fallback=UNCOLOURED):
    if c is None:
        return QtGui.QColor(fallback)
    if isinstance(c, (tuple, list)):
        return QtGui.QColor.fromRgbF(*[float(v) for v in c[:3]])
    return QtGui.QColor(str(c))


def plain(line):
    """A ``links`` line (forge-streams) as words alone."""
    if isinstance(line, str):
        return line
    return "".join(p if isinstance(p, str) else p["text"] for p in line)


def targets(line):
    return [] if isinstance(line, str) else [p["to"] for p in line if not isinstance(p, str)]


def _escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _linked(line):
    """A ``links`` line as rich text: a noun blue, a verb ember, both
    underlined (forge-streams ui_lens._linked)."""
    out, n = [], 0
    for part in line:
        if isinstance(part, str):
            out.append(_escape(part))
            continue
        colour = EMBER if "do" in part["to"] else BLUE
        out.append('<a href="{0}" style="color: {1}; text-decoration: underline;">{2}</a>'
                   .format(n, colour, _escape(part["text"])))
        n += 1
    return "".join(out)


# The family sheet (forge-takes ui.py, byte-identical to forge-wireless's)
# and the Lens's own (forge-streams ui_lens._SS), so a card drawn for the
# standalone Lens is drawn here the same, pixel for pixel.
FORGE_SS = (
    "QDialog { background: #282c34; }"
    "QLabel { color: #ccc; font-size: 12px; }"
    "QLineEdit { background: #1e2028; color: #ccc; "
    "  border: 1px solid #555; border-radius: 3px; "
    "  padding: 4px 8px; font-size: 12px; }"
    "QLineEdit:focus { border: 1px solid #E87E24; }"
    "QComboBox { background: #1e2028; color: #ccc; border: 1px solid #555; "
    "  border-radius: 3px; padding: 3px 8px; font-size: 12px; }"
    "QComboBox QAbstractItemView { background: #1e2028; color: #ccc; "
    "  selection-background-color: #2d4f7a; }"
    "QListWidget { background: #1e2028; color: #ccc; border: none; "
    "  font-size: 12px; }"
    "QListWidget::item { padding: 5px 6px; }"
    "QListWidget::item:selected { background: #2d4f7a; color: #fff; }"
    "QTreeWidget { background: #1e2028; color: #ccc; border: none; "
    "  font-size: 12px; }"
    "QTreeWidget::item { padding: 4px 6px; }"
    "QTreeWidget::item:selected { background: #2d4f7a; color: #fff; }"
    "QTableWidget { background: #1e2028; color: #ccc; border: none; "
    "  font-size: 11px; gridline-color: #2e3240; }"
    "QTableWidget::item { padding: 2px 6px; }"
    "QTableWidget::item:selected { background: #2d4f7a; color: #fff; }"
    "QHeaderView::section { background: #23262f; color: #888; "
    "  border: none; border-right: 1px solid #3a3f4f; "
    "  border-bottom: 1px solid #3a3f4f; "
    "  padding: 5px 6px; font-size: 10px; font-weight: bold; }"
    "QPlainTextEdit { background: #1e2028; color: #aaa; border: none; "
    "  font-size: 11px; font-family: Menlo, monospace; }"
)
BTN_QUIET = (
    "QPushButton { background: #3a3f4f; color: #ddd; "
    "  border: none; border-radius: 3px; padding: 6px 18px; font-size: 12px; }"
    "QPushButton:hover { background: #4a5062; }"
    "QPushButton:disabled { background: #2e3240; color: #666; }"
)
BAR_BTN = BTN_QUIET + " QPushButton { padding: 6px 9px; }"
LENS_SS = FORGE_SS + (
    "QWidget#lens, QWidget#lenswin { background: %(panel)s; }"
    "QFrame#card { background: %(panel)s; border: 1px solid %(rule)s; border-radius: 3px; }"
    "QFrame#card[kind=\"plate\"] { background: %(well)s; border-radius: %(round)spx; }"
    "QFrame#card[kind=\"plate_stream\"] { background: %(well)s; }"
    "QFrame#card[kind=\"shot_stream\"] { background: %(raised)s; border-color: %(raised_rule)s; }"
    "QFrame#card[kind=\"shot\"] { border-color: %(raised_rule)s; border-radius: %(round)spx; }"
    "QFrame#card:hover { border-color: #566078; }"
    "QFrame#card[lit=\"true\"], QFrame#centre[lit=\"true\"] { border: 2px solid %(amber)s; }"
    "QFrame#card[picked=\"true\"], QFrame#centre[picked=\"true\"] { border: 2px solid #e6e9ef; }"
    "QFrame#centre { background: %(panel)s; border: 2px solid %(ember)s; border-radius: 4px; }"
    "QLabel#name { color: #e6e9ef; font-weight: bold; font-size: 12px; }"
    "QLabel#big { color: #eef0f4; font-weight: bold; font-size: 17px; }"
    "QLabel#dim { color: #8a93a4; font-size: 11px; }"
    "QLabel#faint { color: #5c6270; font-size: 10px; letter-spacing: 1px; }"
    "QLabel#kind { color: #8a93a4; font-size: 10px; letter-spacing: 1px; }"
    "QLabel#mono { color: #b9c3d6; font-family: Menlo, monospace; font-size: 11px; }"
    "QLabel#amber { color: %(amber)s; font-size: 11px; }"
    "QLabel#good { color: %(good)s; font-size: 11px; }"
    "QLabel#held { color: %(blue)s; font-size: 11px; }"
    "QToolButton#link { color: %(blue)s; border: none; font-size: 11px; padding: 0; }"
    "QToolButton#link:hover { text-decoration: underline; }"
) % {"panel": PANEL, "rule": RULE, "ember": EMBER, "amber": AMBER, "good": GOOD, "blue": BLUE,
     "well": WELL, "raised": RAISED, "raised_rule": RAISED_RULE, "round": ROUND}
# the host's own frames, over the family sheet
HOST_SS = (
    "QFrame#area { background: transparent; border: none; border-top: 1px solid %(rule)s; }"
    # a hosted canvas shows the window's ground, as it does as the standalone
    # Lens's scroll widget (whose own rule doesn't reach this deep)
    "QFrame#area QWidget#lens { background: transparent; }"
    "QLabel#areatitle { color: #c9d0dc; font-size: 10px; font-weight: bold; "
    "  letter-spacing: 1px; }"
    "QLabel#guard { color: %(bad)s; font-size: 11px; }"
    "QLabel#caption { color: #a3a9b5; font-size: 11px; }"
    "QLabel#caphead { color: #c9d0dc; font-size: 11px; font-weight: bold; }"
    "QToolButton#chip { color: #c9d0dc; background: %(well)s; border: 1px solid %(rule)s; "
    "  border-radius: 8px; padding: 1px 8px; font-size: 10px; }"
    "QToolButton#chip[hidden_area=\"true\"] { color: %(faint)s; }"
    "QToolButton#chip:hover { border-color: #566078; }"
    "QToolButton#quiet { color: %(faint)s; border: none; font-size: 12px; padding: 0 2px; }"
    "QToolButton#quiet:hover { color: #c9d0dc; }"
) % {"rule": RULE, "bad": BAD, "well": WELL, "faint": FAINT}


def _drop(widget):
    """A widget taken out of a layout: hidden now, deleted when the loop
    next turns -- until then a dropped one still paints, at its last place
    or, never laid out, over the window's corner."""
    widget.hide()
    widget.deleteLater()



def _as_mark(m):
    """*m* as a Mark, or None when it can't be one -- a bad mark from an
    area is dropped, never raised into the beat."""
    if isinstance(m, Mark):
        return m
    try:
        return Mark(*m)
    except Exception:
        return None


def _onto_its_screen(widget):
    """Tell *widget*'s window the screen it is really on. Moved by our own
    header drag onto a second monitor, the Lens kept its first screen in
    Flame on macOS, and its menus opened clamped to that one [LIVE 2027.1,
    2026-11-01, Chris: "I moved the lens to a separate window, but the menu
    drew on the other main flame window"]. Plain Qt follows the move
    (offscreen, two screens); this makes sure. A screen of the same virtual
    desktop only repoints the window: nothing is recreated."""
    try:
        handle = widget.windowHandle()
        if handle is None:
            return
        here = QtGui.QGuiApplication.screenAt(widget.frameGeometry().center())
        if here is not None and (handle.screen() is None
                                 or handle.screen().name() != here.name()):
            handle.setScreen(here)
    except Exception:
        pass


def _menu_under(button, menu):
    """*menu* dropped from *button*, on the button's own screen -- the screen
    under the point, not whatever screen the menu's window was made on."""
    pos = button.mapToGlobal(QtCore.QPoint(0, button.height()))
    try:
        here = QtGui.QGuiApplication.screenAt(button.mapToGlobal(button.rect().center()))
        if here is not None:
            menu.setScreen(here)
    except Exception:
        pass
    menu.popup(pos)


def _label(text, name="dim", wrap=False):
    lbl = QtWidgets.QLabel(text)
    lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def _elide(text, room, mono=False):
    font = QtGui.QFont("Menlo") if mono else QtGui.QFont()
    font.setPixelSize(11 if mono else 12)
    font.setBold(not mono)
    return QtGui.QFontMetrics(font).elidedText(text, QtCore.Qt.ElideMiddle, max(60, room))


if QtWidgets is None:
    _Window = None
else:
    class _PenWatch(QtCore.QObject):
        """Each press, release and double-click the window is handed, with
        the tablet events behind them and focus coming and going, to
        forge_hud's pen log -- one log for the wedge across the rail and the
        Lens (r3, open question 2). Takes nothing: always answers False."""

        _KEPT = (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease,
                 QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.TabletPress,
                 QtCore.QEvent.TabletRelease, QtCore.QEvent.FocusIn, QtCore.QEvent.FocusOut)

        def __init__(self, parent):
            QtCore.QObject.__init__(self, parent)
            self.moves = 0

        def eventFilter(self, obj, event):           # noqa: N802
            try:
                kind = event.type()
                if kind == QtCore.QEvent.MouseMove:
                    if event.buttons() != QtCore.Qt.NoButton:
                        self.moves += 1
                elif kind in self._KEPT:
                    if kind == QtCore.QEvent.MouseButtonRelease and self.moves:
                        _pen("moved {0} times while held".format(self.moves))
                    if kind in (QtCore.QEvent.MouseButtonPress,
                                QtCore.QEvent.MouseButtonRelease):
                        self.moves = 0
                    _pen("window", event)
            except Exception:
                pass
            return False

    class _Clicks(QtCore.QObject):
        """A widget's click (acted on at release, inside it, left button)
        and double-click -- forge-streams' _DoubleClick, the host's own so
        areas never install a filter of theirs (r3). The release that ends a
        double-click is no click."""

        def __init__(self, parent):
            QtCore.QObject.__init__(self, parent)
            self.click = None
            self.double = None
            self._armed = False

        def eventFilter(self, obj, event):           # noqa: N802
            kind = event.type()
            if kind == QtCore.QEvent.MouseButtonDblClick:
                self._armed = False
                if self.double is not None:
                    self.double()
                    return True
            elif kind == QtCore.QEvent.MouseButtonPress:
                self._armed = event.button() == QtCore.Qt.LeftButton
            elif kind == QtCore.QEvent.MouseButtonRelease and self._armed:
                self._armed = False
                if (self.click is not None and event.button() == QtCore.Qt.LeftButton
                        and obj.rect().contains(event.position().toPoint())):
                    self.click()
            return False

    def _clicks(widget):
        for child in widget.children():
            if isinstance(child, _Clicks):
                return child
        found = _Clicks(widget)
        widget.installEventFilter(found)
        return found

    class _Dots(QtWidgets.QWidget):
        """forge_hud's drag grip: six painted dots, brighter while the
        header is under the pointer. A signpost; clicks pass through."""

        DOT, PITCH = 2.0, 4.0

        def __init__(self):
            QtWidgets.QWidget.__init__(self)
            self.lit = False
            self.setFixedSize(int(self.PITCH * 2), int(self.PITCH * 3))
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

        def paintEvent(self, _event):                # noqa: N802
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor("#8a93a4" if self.lit else "#3a3f4f"))
            for col in range(2):
                for row in range(3):
                    p.drawEllipse(QtCore.QRectF(col * self.PITCH, row * self.PITCH + 1,
                                                self.DOT, self.DOT))

    class _HeaderHover(QtCore.QObject):
        def __init__(self, header, dots):
            QtCore.QObject.__init__(self, header)
            self._dots = dots

        def eventFilter(self, obj, event):           # noqa: N802
            kind = event.type()
            if kind in (QtCore.QEvent.Enter, QtCore.QEvent.Leave):
                self._dots.lit = kind == QtCore.QEvent.Enter
                self._dots.update()
            return False

    class _Outline(QtWidgets.QWidget):
        """Where the window will be when the pen lifts: never under the pen."""

        def __init__(self):
            QtWidgets.QWidget.__init__(self, None, QtCore.Qt.ToolTip
                                       | QtCore.Qt.FramelessWindowHint
                                       | QtCore.Qt.WindowTransparentForInput)
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
            self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)

        def paintEvent(self, _event):                # noqa: N802
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            p.setBrush(QtGui.QColor(74, 158, 232, 28))
            p.setPen(QtGui.QPen(QtGui.QColor(BLUE), 2))
            p.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1), 9, 9)

    def _resized(start, delta, left, minimum):
        rect = QtCore.QRect(start)
        rect.setBottom(max(start.top() + minimum.height() - 1, start.bottom() + delta.y()))
        if left:
            rect.setLeft(min(start.right() - minimum.width() + 1, start.left() + delta.x()))
        else:
            rect.setRight(max(start.left() + minimum.width() - 1, start.right() + delta.x()))
        return rect

    class _Grip(QtWidgets.QWidget):
        """A bottom corner the window is sized by: the drag moves an outline,
        the window takes its size once, on release. QSizeGrip resized it
        under the pen on every move, and left the Wacom driver reading every
        tip press as a right click [Chris, 2026-10-16]."""

        SIZE = 16

        def __init__(self, win, left):
            QtWidgets.QWidget.__init__(self, win)
            self._win, self.left = win, left
            self._press = self._outline = None
            self._hover = False
            self.setFixedSize(self.SIZE, self.SIZE)

        def target(self, here):
            point, start = self._press
            return _resized(start, here - point, self.left, self._win.minimumSize())

        def mousePressEvent(self, event):            # noqa: N802
            if event.button() == QtCore.Qt.LeftButton:
                self._press = (event.globalPosition().toPoint(), self._win.geometry())
                event.accept()

        def mouseMoveEvent(self, event):             # noqa: N802
            if self._press is None:
                return
            if self._outline is None:
                self._outline = _Outline()
            self._outline.setGeometry(self.target(event.globalPosition().toPoint()))
            self._outline.show()
            event.accept()

        def mouseReleaseEvent(self, event):          # noqa: N802
            if self._press is None:
                return
            rect = self.target(event.globalPosition().toPoint())
            self._press = None
            self._drop()
            if rect != self._win.geometry():
                self._win.setGeometry(rect)
                self._win.remember()
            event.accept()

        def _drop(self):
            if self._outline is not None:
                self._outline.hide()
                self._outline.deleteLater()
                self._outline = None

        def hideEvent(self, event):                  # noqa: N802
            self._press = None
            self._drop()
            QtWidgets.QWidget.hideEvent(self, event)

        def enterEvent(self, event):                 # noqa: N802
            self._hover = True
            self.update()

        def leaveEvent(self, event):                 # noqa: N802
            self._hover = False
            self.update()

        def paintEvent(self, event):                 # noqa: N802
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            p.setPen(QtGui.QPen(QtGui.QColor("#8a93a4" if self._hover else RULE), 1.5))
            s = self.SIZE - 3
            for k in (4, 8, 12):
                if self.left:
                    p.drawLine(QtCore.QPointF(3, s - k), QtCore.QPointF(3 + k, s))
                else:
                    p.drawLine(QtCore.QPointF(s - k, s), QtCore.QPointF(s, s - k))

    class _FoldMark(QtWidgets.QAbstractButton):
        """One of an area's three marks, painted -- pipeline's: a dash for
        collapsed, three lines for minimal, a box with lines for expanded."""

        def __init__(self, fold, current):
            QtWidgets.QAbstractButton.__init__(self)
            self.fold, self.current = fold, current
            self.setFixedSize(20, 16)
            self.setToolTip({"collapsed": "Collapse to one line", "minimal": "A row per card",
                             "expanded": "Every card in full"}[fold])

        def paintEvent(self, _event):                # noqa: N802
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            colour = QtGui.QColor(EMBER if self.current else FAINT)
            if self.current:
                p.fillRect(self.rect(), QtGui.QColor(WELL))
            p.setPen(QtGui.QPen(colour, 1.4))
            cx, cy = self.width() / 2, self.height() / 2
            if self.fold == "collapsed":
                p.drawLine(QtCore.QPointF(cx - 5, cy), QtCore.QPointF(cx + 5, cy))
            elif self.fold == "minimal":
                for dy in (-3.5, 0, 3.5):
                    p.drawLine(QtCore.QPointF(cx - 5, cy + dy), QtCore.QPointF(cx + 5, cy + dy))
            else:
                p.drawRect(QtCore.QRectF(cx - 6, cy - 5, 12, 10))
                for dy in (-1.5, 1.5):
                    p.drawLine(QtCore.QPointF(cx - 3, cy + dy), QtCore.QPointF(cx + 3, cy + dy))

    class _ListPopout(QtWidgets.QWidget):
        """Something about a card, popped out under it -- forge-streams'
        _ListPopout, its links followed by the area that drew it (*linker*:
        the area's host)."""

        GAP = 6

        def __init__(self, win, frame, key, title, note, paragraphs, close, linker,
                     mono=False):
            QtWidgets.QWidget.__init__(self, win, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
            self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
            self.setStyleSheet(win.styleSheet())
            self.key, self._frame, self._win = key, frame, win
            self._narrow = linker.mode == "narrow"
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(12, 9, 12, 10)
            lay.setSpacing(3)
            top = QtWidgets.QHBoxLayout()
            top.addWidget(_label(title, "name"), 1)
            if note:
                top.addWidget(_label(note, "faint"))
            lay.addLayout(top)
            for n, paragraph in enumerate(paragraphs):
                if n and not mono:
                    lay.addSpacing(6)
                for line in paragraph:
                    if mono:
                        said = _label(_elide(plain(line), 520, mono=True), "mono")
                        said.setToolTip(plain(line))
                        if targets(line):
                            to = targets(line)[0]
                            said.setTextFormat(QtCore.Qt.RichText)
                            said.setText('<a href="0" style="color: {0}; text-decoration: '
                                         'underline;">{1}</a>'.format(BLUE, _escape(said.text())))
                            said.setTextInteractionFlags(QtCore.Qt.LinksAccessibleByMouse)
                            said.setToolTip("{0} - show it in the Finder".format(plain(line))
                                            if "finder" in to else plain(line))
                            said.linkActivated.connect(lambda _h, to=to: linker.follow_link(to))
                    else:
                        said = _label(plain(line), wrap=True)
                        said.setStyleSheet("color: #c9d0dc; font-size: 12px;")
                        said.setMinimumWidth(300)
                        if targets(line):
                            said.setTextFormat(QtCore.Qt.RichText)
                            said.setText(_linked(line))
                            said.setTextInteractionFlags(QtCore.Qt.LinksAccessibleByMouse)
                            said.setAccessibleName(plain(line))
                            to = targets(line)
                            said.linkActivated.connect(
                                lambda href, to=to: linker.follow_link(to[int(href)]))
                            said.linkHovered.connect(
                                lambda href, to=to: linker.hover_link(to[int(href)] if href
                                                                      else None))
                    lay.addWidget(said)
            foot = QtWidgets.QHBoxLayout()
            foot.addStretch(1)
            hide = QtWidgets.QToolButton()
            hide.setObjectName("link")
            hide.setText("hide")
            hide.clicked.connect(lambda: later(close))
            foot.addWidget(hide)
            lay.addLayout(foot)

        def paintEvent(self, _event):                # noqa: N802
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            p.setBrush(QtGui.QColor(PANEL))
            p.setPen(QtGui.QPen(QtGui.QColor("#566078"), 1))
            p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 4, 4)

        def place(self):
            """Under its card, as a drop-down from it -- left edges together
            wide, right edges narrow; above the card when there's no room
            below."""
            frame = self._frame
            if not frame.isVisible():
                self.hide()
                return
            hint = self.sizeHint()
            width = max(frame.width(), hint.width())
            lay = self.layout()
            height = lay.totalHeightForWidth(width) if lay.hasHeightForWidth() else hint.height()
            top = frame.mapToGlobal(QtCore.QPoint(0, 0))
            x = top.x() + frame.width() - width if self._narrow else top.x()
            y = top.y() + frame.height() + self.GAP
            win = self._win
            bottom = win.mapToGlobal(QtCore.QPoint(0, win.height())).y()
            if y + height > bottom and top.y() - self.GAP - height >= \
                    win.mapToGlobal(QtCore.QPoint(0, 0)).y():
                y = top.y() - self.GAP - height
            self.setGeometry(x, y, width, height)
            _onto_its_screen(self)

    class _WidgetPopout(_ListPopout):
        """popout(): an area's own widget, in the same frame."""

        def __init__(self, win, frame, key, content, close, linker):
            _ListPopout.__init__(self, win, frame, key, "", "", [], close, linker)
            lay = self.layout()
            lay.insertWidget(1, content)

    class _AreaScroll(object):
        """The surface a hosted drawing reaches as ``host._scroll``: its one
        content widget, in its area's frame; scrolling is the window's."""

        def __init__(self, frame):
            self._frame = frame

        def setWidget(self, widget):                # noqa: N802
            self._frame.set_content(widget)

        def widget(self):
            return self._frame.content

        def ensureWidgetVisible(self, widget, x=50, y=50):   # noqa: N802
            self._frame.win.scroll.ensureWidgetVisible(widget, x, y)

        def verticalScrollBar(self):                # noqa: N802
            return self._frame.win.scroll.verticalScrollBar()

        def viewport(self):
            return self._frame.win.scroll.viewport()

    class AreaHost(object):
        """LensWindow's own surface, for one area (see the module header):
        what forge-streams' SegmentGraph reaches as ``host``. An area hangs
        its own on it -- ``redraw(state)`` for refresh(state), ``link(to)``
        and ``hover(to)`` for its links, ``views``, ``_panel``."""

        def __init__(self, win, area_id, frame):
            self._win, self.area_id, self._frame = win, area_id, frame
            self._scroll = _AreaScroll(frame)
            self.STATE_PREFIX = "lens_{0}_".format(area_id.replace(".", "_"))
            self._panel = None
            self.views = set()
            self.redraw = None
            self.link = None
            self.hover = None
            self.reveal_card = None

        @property
        def mode(self):
            area = _anchor()["areas"].get(self.area_id) or {}
            return self._win.mode if area.get("wide") else "narrow"

        @property
        def fold(self):
            return self._frame.fold

        @property
        def ctx(self):
            return self._win.follower.ctx

        @property
        def _popout(self):
            return self._win._popout

        def _pop(self, card, frame, what, note, paragraphs, title=None, mono=False):
            self._win.pop(self, card, frame, what, note, paragraphs, title=title, mono=mono)

        def _close_popout(self):
            self._win.close_popout()

        def _redraw_later(self, what, fn):
            g = self._win.geometry()
            _pen("redraw asked: {0}:{1} @ {2},{3} {4}x{5}".format(
                self.area_id, what, g.x(), g.y(), g.width(), g.height()))
            later(fn)

        def _do(self, verb, *args):
            name = getattr(verb, "__name__", "?")
            _pen("asked: {0}".format(name))

            def run():
                _pen("doing: {0}".format(name))
                verb(*args)
                _pen("done: {0}".format(name))
                update(self.area_id)
            later(run)

        def follow_link(self, to):
            _pen("link: {0}".format(to))
            if self.link is not None:
                self.link(to)

        def hover_link(self, to):
            if self.hover is not None:
                self.hover(to)

        def reveal(self, card_id):
            if self.reveal_card is not None:
                self.reveal_card(card_id)

        def _set_title(self, rest):
            self._frame.set_subtitle(rest)

        def refresh(self, state=None):
            """A hosted drawing's redraw: from *state* (what it read last)
            through its ``redraw``; else the area read afresh."""
            if state is not None and self.redraw is not None:
                try:
                    self.redraw(state)
                except Exception as exc:
                    _guard_line(self.area_id, "redraw", exc)
                return
            update(self.area_id)

    class _AreaFrame(QtWidgets.QFrame):
        """One area: its header -- marks, title, summary, tools, hide -- and
        its one content widget, or the line saying what failed."""

        def __init__(self, win, area_id):
            QtWidgets.QFrame.__init__(self)
            self.setObjectName("area")
            self.win, self.area_id = win, area_id
            self.content = None
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(0, 6, 0, 4)
            lay.setSpacing(4)
            self._head = QtWidgets.QHBoxLayout()
            self._head.setSpacing(4)
            lay.addLayout(self._head)
            self._sub = QtWidgets.QLabel("")
            self._sub.setTextFormat(QtCore.Qt.RichText)
            self._sub.setVisible(False)
            lay.addWidget(self._sub)
            self._guard = _label("", "guard", wrap=True)
            self._guard.setVisible(False)
            lay.addWidget(self._guard)
            self._body = QtWidgets.QVBoxLayout()
            self._body.setContentsMargins(0, 0, 0, 0)
            lay.addLayout(self._body)
            self._marks = []
            self._title = _label("", "areatitle")
            self._summary = QtWidgets.QLabel("")
            self._summary.setTextFormat(QtCore.Qt.RichText)
            self.head()

        @property
        def area(self):
            return _anchor()["areas"].get(self.area_id) or {}

        @property
        def fold(self):
            saved = (_load_state().get("fold") or {}).get(self.win.mode) or {}
            fold = saved.get(self.area_id)
            return fold if fold in FOLDS else "expanded"

        def set_fold(self, fold):
            folds = _load_state().get("fold") or {}
            folds.setdefault(self.win.mode, {})[self.area_id] = fold
            _save_state(fold=folds)
            self.win.close_popout()
            self.apply_fold()
            self.win.refresh_area(self.area_id, "fold")

        def cycle(self):
            i = FOLDS.index(self.fold)
            self.set_fold(FOLDS[(i + 1) % len(FOLDS)])

        def head(self):
            """The header, drawn afresh (a fold or a tool changed)."""
            while self._head.count():
                item = self._head.takeAt(0)
                w = item.widget()
                if w is not None and w not in (self._title, self._summary):
                    _drop(w)
            self._marks = []
            for fold in FOLDS:
                mark = _FoldMark(fold, fold == self.fold)
                mark.clicked.connect(lambda _c=False, f=fold: later(lambda: self.set_fold(f)))
                self._marks.append(mark)
                self._head.addWidget(mark)
            self._head.addSpacing(4)
            self._title.setText(str(self.area.get("title", self.area_id)).upper())
            self._title.setToolTip("Click to fold or unfold")
            on_release(self._title, lambda: later(self.cycle))
            self._head.addWidget(self._title)
            self._head.addSpacing(6)
            self._head.addWidget(self._summary, 1)
            for tool in self.area.get("tools") or ():
                self._head.addWidget(self._tool(tool))
            hide = QtWidgets.QToolButton()
            hide.setObjectName("quiet")
            hide.setText("×")
            hide.setToolTip("Hide this area - its chip brings it back")
            hide.clicked.connect(lambda: later(lambda: self.win.set_hidden(self.area_id, True)))
            self._head.addWidget(hide)

        def _tool(self, tool):
            text, menu_fn = tool[0], tool[1]
            btn = QtWidgets.QPushButton(text)
            btn.setStyleSheet(BAR_BTN + " QPushButton { padding: 2px 8px; font-size: 11px; }")

            def show():
                # A fresh menu every click, never one reused: on Flame 2027.1
                # (macOS, two screens of different scale) a reused QMenu
                # opened right the first time and on the primary screen the
                # next, at the right point read as the other screen's local
                # coordinates; a fresh one lands right every time [LIVE
                # 2027.1, 2026-11-01, forge-streams' NSWindow log]. Not
                # setMenu either: its drop reuses the menu.
                menu = QtWidgets.QMenu(btn)
                menu.aboutToHide.connect(menu.deleteLater)   # after its action runs
                try:
                    menu_fn(menu, self.win.follower.ctx)
                except Exception as exc:
                    _guard_line(self.area_id, "tool", exc)
                    menu.deleteLater()
                    return
                if menu.actions():
                    _menu_under(btn, menu)
                else:
                    menu.deleteLater()
            btn.setText(text + "  \u25be")
            btn.clicked.connect(lambda _c=False: show())
            btn._tone_fn = tool[2] if len(tool) > 2 else None
            return btn

        def tint_tools(self, ctx):
            for i in range(self._head.count()):
                w = self._head.itemAt(i).widget()
                fn = getattr(w, "_tone_fn", None)
                if fn is None:
                    continue
                try:
                    tone = fn(ctx)
                except Exception:
                    tone = None
                tint = TONE.get(tone) if tone in ("info", "warn", "bad") else None
                w.setStyleSheet(BAR_BTN + " QPushButton { padding: 2px 8px; font-size: 11px; }"
                                + (" QPushButton {{ color: {0}; }}".format(tint) if tint else ""))

        def apply_fold(self):
            for mark in self._marks:
                mark.current = mark.fold == self.fold
                mark.update()
            collapsed = self.fold == "collapsed"
            if self.content is not None:
                self.content.setVisible(not collapsed)
            self._sub.setVisible(not collapsed and bool(self._sub.text()))

        def set_summary(self, said):
            said = said or {}
            tone = TONE.get(said.get("tone"), DIM)
            self._summary.setText('<span style="color:{0}; font-size:11px;">{1}</span>'
                                  .format(tone, said.get("html", "")))

        def set_subtitle(self, rest):
            self._sub.setText(rest or "")
            self._sub.setVisible(bool(rest) and self.fold != "collapsed")

        def set_content(self, widget):
            if widget is self.content:
                return
            if self.content is not None:
                self._body.removeWidget(self.content)
                _drop(self.content)
            self.content = widget
            if widget is not None:
                self._body.addWidget(widget)
                widget.setVisible(self.fold != "collapsed")

        def guard(self, what, exc):
            if exc is None:
                self._guard.setVisible(False)
                return
            self._guard.setText("{0}: {1} failed ({2})".format(
                self.area.get("title", self.area_id), what, type(exc).__name__))
            self._guard.setToolTip(repr(exc))
            self._guard.setVisible(True)

    class _Spine(QtWidgets.QWidget):
        """The cut, drawn small: a row a track, the top track on top; each
        segment filled in a take colour (an area's fill mark) or neutral, an
        effect-only gap hollow, the subject outlined white, the positioner a
        white line. A preview's marks draw by style -- fill, outline,
        dashed, dim the rest -- never a tone fill (r3: take colours fill,
        tones stroke). Sized once per subject to the cut plus every area's
        extent, so a preview never grows it or slides a shot (streams
        816ae57). Two ways to move in time, as the Takes Lens has them
        (forge-takes 59b5b28) [Chris, 2026-10-31: "It should only be
        draggable when directly clicked and dragged. If I click on a segment
        the behavior should be as before."]:

        - pressed on the playhead's line (GRAB px) or its tab, a drag scrubs
          and the subject follows the playhead;
        - pressed anywhere else, a click acted on at release over the same
          segment: the playhead to its first frame, the window pinned on it.

        Nothing in Flame moves on the press, only on a drag or a release, on
        the idle queue."""

        ROW, GAP, PAD = 11, 3, 6
        #: band rows over the tracks: height, gap, and how many before "+n"
        BAND, BAND_GAP, BANDS = 4, 2, 4
        #: How near the playhead's line a press grabs it, in pixels -- room
        #: for a pen (forge-takes' GRAB).
        GRAB = 5

        def __init__(self, win):
            QtWidgets.QWidget.__init__(self)
            self.win = win
            self.setMouseTracking(True)
            self.cut = ()
            self.span = (0, 1, 1)
            self.frame = None
            self.subject = set()
            self.fills = {}
            self.marks = []
            self.bands = []           # the areas' band marks (overlay)
            self.band_rows = 0        # rows held for them
            self._extents = ()
            self._press = False       # the playhead grabbed
            self._down = None         # the segment pressed, acted on at release
            self._lit = False         # the line can be grabbed
            self.hold(())

        def hold(self, extents=None):
            if extents is None:
                extents = self._extents
            self._extents = tuple(extents)
            cut = self.cut
            first = min([s.record_in for s in cut] + [e[0] for e in extents]) if (cut or extents) \
                else 0
            last = max([s.record_out for s in cut] + [e[1] for e in extents]) if (cut or extents) \
                else 1
            tracks = max([s.track + 1 for s in cut] + [e[2] for e in extents] + [1])
            self.span = (first, max(last, first + 1), tracks)
            self.setFixedHeight(2 * self.PAD + self._top() + tracks * self.ROW
                                + (tracks - 1) * self.GAP)
            self.update()

        def _top(self):
            """The height the band rows take over the tracks."""
            n = min(self.band_rows, self.BANDS)
            return n * (self.BAND + self.BAND_GAP)

        def band_rows_for(self, marks):
            rows = [m.at for m in marks if m.style == "band" and isinstance(m.at, int)
                    and m.at >= 0]
            return (max(rows) + 1) if rows else 0

        def _x(self, frame):
            first, last, _t = self.span
            width = max(self.width() - 2 * self.PAD, 1)
            return self.PAD + (frame - first) * width / float(last + 1 - first)

        def _frame_at(self, x):
            first, last, _t = self.span
            width = max(self.width() - 2 * self.PAD, 1)
            f = first + (x - self.PAD) * (last + 1 - first) / float(width)
            return int(max(first, min(last, f)))

        def _rect(self, track, start, end):
            tracks = self.span[2]
            x0, x1 = self._x(start), self._x(end + 1)
            y = self.PAD + self._top() + (tracks - 1 - track) * (self.ROW + self.GAP)
            return QtCore.QRectF(x0, y, max(x1 - x0 - 1, 1.5), self.ROW)

        def _paint_bands(self, p, marks):
            n = min(self.band_rows, self.BANDS)
            if not n:
                return
            by_key = dict((s.key, s) for s in self.cut)
            hidden = 0
            for m in marks:
                if m.style != "band" or not isinstance(m.at, int) or m.at < 0:
                    continue
                if m.at >= n:
                    hidden = max(hidden, m.at + 1 - n)
                    continue
                s = by_key.get(m.key)
                if s is None:
                    continue
                x0, x1 = self._x(s.record_in), self._x(s.record_out + 1)
                y = self.PAD + (n - 1 - m.at) * (self.BAND + self.BAND_GAP)
                p.fillRect(QtCore.QRectF(x0, y, max(x1 - x0 - 1, 1.5), self.BAND),
                           _colour(m.colour))
            if hidden:
                # rows past BANDS: said, at the top row's right end
                f = p.font()
                f.setPixelSize(9)
                p.setFont(f)
                text = "+{0}".format(hidden)
                w = p.fontMetrics().horizontalAdvance(text) + 6
                r = QtCore.QRectF(self.width() - self.PAD - w, 0, w, self.PAD + self.BAND + 2)
                p.fillRect(r, QtGui.QColor(PANEL))
                p.setPen(QtGui.QColor("#aab2c2"))
                p.drawText(r, QtCore.Qt.AlignCenter, text)

        def paintEvent(self, _event):                # noqa: N802
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing, False)
            tracks = self.span[2]
            width = max(self.width() - 2 * self.PAD, 1)
            top = self._top()
            for t in range(tracks):
                p.fillRect(QtCore.QRectF(self.PAD, self.PAD + top + t * (self.ROW + self.GAP),
                                         width, self.ROW), QtGui.QColor("#1b1d24"))
            self._paint_bands(p, list(self.bands) + [m for m in self.marks
                                                     if m.style == "band"])
            # a shot's marks merged: its fill colour, and how it is stroked
            fill_of, styles = {}, {}
            marks = [m for m in self.marks if m.style != "band"]
            for m in marks:
                if m.at is not None:
                    continue
                styles.setdefault(m.key, set()).add(m.style)
                if m.style == "fill" and m.colour is not None:
                    fill_of[m.key] = m.colour
            dim = any(m.style == "dim_rest" for m in marks)
            white = QtGui.QColor("#f2f2f2")
            for s in self.cut:
                r = self._rect(s.track, s.record_in, s.record_out)
                marked = styles.get(s.key, set())
                c = _colour(fill_of.get(s.key, self.fills.get(s.key)))
                if dim and not marked:
                    c.setAlphaF(0.22)
                if s.kind == "fx_gap":
                    fill = QtGui.QColor(c)
                    fill.setAlphaF(c.alphaF() * 0.35)
                    p.fillRect(r, fill)
                    p.setPen(QtGui.QPen(c, 1))
                    p.setBrush(QtCore.Qt.NoBrush)
                    p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
                else:
                    p.fillRect(r, c)
                dashed = "dashed" in marked and not marked & {"outline", "dim_rest"}
                if marked & {"outline", "dashed", "dim_rest"} or \
                        (not marks and s.key in self.subject):
                    pen = QtGui.QPen(QtGui.QColor("#8a91a0") if dashed else white, 1.2)
                    if dashed:
                        pen.setStyle(QtCore.Qt.DashLine)
                    p.setPen(pen)
                    p.setBrush(QtCore.Qt.NoBrush)
                    p.drawRect(r.adjusted(0.6, 0.6, -0.6, -0.6))
            for m in marks:
                # a ghost only where at is (track, in, out): a style or an
                # at this spine doesn't know (a newer area's) is skipped
                if not (isinstance(m.at, (tuple, list)) and len(m.at) == 3):
                    continue
                r = self._rect(*m.at)
                pen = QtGui.QPen(_colour(m.colour, "#8a91a0"), 1.0)
                pen.setStyle(QtCore.Qt.DashLine)
                p.setPen(pen)
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
            first, last, _t = self.span
            if self.frame is not None and first <= self.frame <= last:
                px = self._x(self.frame) + 0.5
                lit = self._lit or self._press
                p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1.4))
                p.drawLine(QtCore.QPointF(px, 1), QtCore.QPointF(px, self.height() - 1))
                # its grip: a small tab on top, brighter while it can be
                # grabbed -- Flame owns the pointer, so brightness is the sign
                tab = QtGui.QPainterPath()
                tab.moveTo(px - 4, 0)
                tab.lineTo(px + 4, 0)
                tab.lineTo(px, self.PAD - 1)
                tab.closeSubpath()
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(QtGui.QColor("#ffffff" if lit else "#aab2c2"))
                p.drawPath(tab)
            p.end()

        def near_line(self, x):
            first, last, _t = self.span
            return (self.frame is not None and first <= self.frame <= last
                    and abs(x - self._x(self.frame) - 0.5) <= self.GRAB)

        def _light(self, on):
            if on != self._lit:
                self._lit = on
                self.update()

        def seg_at(self, pos):
            for s in sorted(self.cut, key=lambda s: -s.track):
                if self._rect(s.track, s.record_in, s.record_out).adjusted(-1, -1, 1, 1) \
                        .contains(pos):
                    return s
            return None

        def mousePressEvent(self, event):            # noqa: N802
            # armed only: nothing in Flame moves while the tip goes down
            _pen("spine press", event)
            event.accept()
            if event.button() != QtCore.Qt.LeftButton:
                return
            QtWidgets.QToolTip.hideText()
            pos = event.position()
            if self.near_line(pos.x()):
                self._press = True    # the playhead, grabbed: no jump
                self.update()
            else:
                s = self.seg_at(pos)
                self._down = s.key if s else None

        def mouseMoveEvent(self, event):             # noqa: N802
            pos = event.position()
            if self._press:
                self.win.scrub(self._frame_at(pos.x()))
                return
            near = self.near_line(pos.x())
            self._light(near)
            s = None if near else self.seg_at(pos)
            if near:
                tip = "the playhead - drag to scrub"
            elif s is not None:
                tip = "{0}\nclick: the playhead to its start, the Lens pinned on it".format(
                    s.name)
            else:
                tip = ""
            self.setToolTip(tip)

        def leaveEvent(self, _event):                # noqa: N802
            self._light(False)

        def mouseReleaseEvent(self, event):          # noqa: N802
            _pen("spine release", event)
            if event.button() != QtCore.Qt.LeftButton:
                return
            if self._press:
                self._press = False
                self.win.scrub(self._frame_at(event.position().x()), done=True)
                self.update()
                return
            key, self._down = self._down, None
            s = self.seg_at(event.position())
            if key is not None and s is not None and s.key == key:
                self.win.pick(key)    # a press that wandered off does nothing

    class _Window(QtWidgets.QWidget):
        """The one Lens. See the module header."""

        def __init__(self, follower):
            # A tool window, not always-on-top: with Flame, out of every other
            # app's way [Chris, 2026-10-15: "super intrusive"].
            QtWidgets.QWidget.__init__(self, None, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
            self.follower = follower
            self.hosts, self.frames = {}, {}
            self._popout = None
            self._pen_watch = _PenWatch(self)
            self._pen_window = None
            self._press = self._offset = None
            self._moved = self._manual = False
            self._switching = False
            self._scrub_to = None
            saved = _load_state().get("mode")
            self.mode = saved if saved in ("narrow", "wide") else "narrow"
            self.setWindowTitle("FORGE — Lens")
            self.setObjectName("lensnarrow")
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
            self.setFocusPolicy(QtCore.Qt.NoFocus)          # off the keyboard
            self.setStyleSheet(LENS_SS + HOST_SS)
            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(14, 12, 14, 12)
            outer.setSpacing(6)
            # the header: FORGE, the buttons, and the subject on its own row
            self._header = QtWidgets.QWidget()
            rows = QtWidgets.QVBoxLayout(self._header)
            rows.setContentsMargins(0, 0, 0, 0)
            rows.setSpacing(2)
            bar = QtWidgets.QHBoxLayout()
            rows.addLayout(bar)
            dots = _Dots()
            bar.addWidget(dots, 0, QtCore.Qt.AlignVCenter)
            bar.addSpacing(4)
            self._header.installEventFilter(_HeaderHover(self._header, dots))
            self._title = QtWidgets.QLabel(
                '<span style="color:{0};font-weight:bold;">FORGE</span>'
                '&nbsp;<span style="color:#8a93a4;">LENS</span>'.format(EMBER))
            self._title.setTextFormat(QtCore.Qt.RichText)
            bar.addWidget(self._title, 1)
            self._follow_btn = self._button(bar, "", self._toggle_pin)
            self._mode_btn = self._button(bar, "", lambda: self.set_mode(
                "wide" if self.mode == "narrow" else "narrow"))
            refresh = self._button(bar, "Refresh", self.refresh_all)
            refresh.setToolTip("Read the timeline and every area again")
            close_btn = self._button(bar, "×", close, now=True)
            close_btn.setToolTip("Put the Lens away")
            self._subject = QtWidgets.QLabel("")
            self._subject.setTextFormat(QtCore.Qt.RichText)
            self._subject.setContentsMargins(12, 0, 0, 0)
            rows.addWidget(self._subject)
            outer.addWidget(self._header)
            self.spine = _Spine(self)
            outer.addWidget(self.spine)
            # the caption: held at its full height, so a preview never moves
            # what is under it
            self._cap_head = _label("", "caphead")
            self._cap = _label("", "caption")
            self._cap.setTextFormat(QtCore.Qt.PlainText)
            self._cap.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
            cap = QtWidgets.QWidget()
            cl = QtWidgets.QVBoxLayout(cap)
            cl.setContentsMargins(6, 0, 6, 0)
            cl.setSpacing(0)
            cl.addWidget(self._cap_head)
            cl.addWidget(self._cap)
            self._cap.setFixedHeight(self._cap.fontMetrics().lineSpacing() * 3 + 2)
            self._cap_head.setFixedHeight(self._cap_head.fontMetrics().lineSpacing() + 2)
            outer.addWidget(cap)
            self._chips = QtWidgets.QHBoxLayout()
            self._chips.setSpacing(4)
            outer.addLayout(self._chips)
            self.scroll = QtWidgets.QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            self.scroll.setStyleSheet(
                "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
            self.scroll.viewport().setAutoFillBackground(False)
            self.scroll.verticalScrollBar().valueChanged.connect(self.place_popout)
            self._stack_w = QtWidgets.QWidget()
            self._stack = QtWidgets.QVBoxLayout(self._stack_w)
            self._stack.setContentsMargins(0, 0, 0, 0)
            self._stack.setSpacing(2)
            self._empty = _label("No areas yet: a FORGE tool adds its own when it loads.",
                                 "dim", wrap=True)
            self._stack.addWidget(self._empty)
            self._stack.addStretch(1)
            self.scroll.setWidget(self._stack_w)
            outer.addWidget(self.scroll, 1)
            self._grips = [_Grip(self, left=True), _Grip(self, left=False)]
            self._said_follow()
            self._apply_mode()

        def build_areas(self):
            """Every registered area, built -- once the window is the
            anchor's, so an area's build can reach its host()."""
            for area_id in list(_anchor()["order"]):
                self.rebuild_area(area_id)
            self.chips()

        def _button(self, bar, text, fn, now=False):
            btn = QtWidgets.QPushButton(text)
            btn.setStyleSheet(BAR_BTN)
            btn.setFocusPolicy(QtCore.Qt.NoFocus)
            btn.clicked.connect(fn if now else (lambda: later(fn)))
            bar.addWidget(btn)
            return btn

        # -- areas --------------------------------------------------------------

        def rebuild_area(self, area_id):
            """Build (or rebuild, after a re-register) *area_id*'s frame and
            widget, in registry order."""
            area = _anchor()["areas"].get(area_id)
            if area is None:
                return
            frame = self.frames.get(area_id)
            if frame is None:
                frame = _AreaFrame(self, area_id)
                self.frames[area_id] = frame
                order = [a for a in _anchor()["order"] if a in self.frames]
                # after the "no areas yet" line, in registry order
                self._stack.insertWidget(1 + order.index(area_id), frame)
            else:
                frame.head()
            host = AreaHost(self, area_id, frame)
            self.hosts[area_id] = host
            frame.guard(None, None)
            try:
                widget = area["build"](frame, self.follower.ctx)
                if widget is not None:
                    frame.set_content(widget)
            except Exception as exc:
                _guard_line(area_id, "build", exc)
            frame.apply_fold()
            frame.setVisible(area_id not in self.hidden())
            self._empty.setVisible(not self.frames)
            self.chips()
            self.refresh_area(area_id, "build")
            self.paint_spine(hold=False)          # its overlay, now -- not next beat

        def drop_area(self, area_id):
            frame = self.frames.pop(area_id, None)
            self.hosts.pop(area_id, None)
            if frame is not None:
                self._stack.removeWidget(frame)
                _drop(frame)
            self._empty.setVisible(not self.frames)
            self.chips()
            self.paint_spine(hold=False)          # its marks gone with it

        def hidden(self):
            return set(_load_state().get("hidden") or ())

        def set_hidden(self, area_id, on):
            hidden = self.hidden()
            hidden = (hidden | {area_id}) if on else (hidden - {area_id})
            _save_state(hidden=sorted(hidden))
            frame = self.frames.get(area_id)
            if frame is not None:
                frame.setVisible(not on)
            self.chips()

        def chips(self):
            """A chip per area: jump to it, or bring a hidden one back."""
            while self._chips.count():
                item = self._chips.takeAt(0)
                if item.widget() is not None:
                    _drop(item.widget())
            hidden = self.hidden()
            for area_id in _anchor()["order"]:
                if area_id not in self.frames:
                    continue
                chip = QtWidgets.QToolButton()
                chip.setObjectName("chip")
                chip.setFocusPolicy(QtCore.Qt.NoFocus)
                chip.setText(str((_anchor()["areas"].get(area_id) or {}).get("title", area_id)))
                chip.setProperty("hidden_area", area_id in hidden)
                chip.setToolTip("Bring it back" if area_id in hidden else "Go to it")
                chip.clicked.connect(lambda _c=False, a=area_id: later(lambda: self.jump(a)))
                self._chips.addWidget(chip)
            self._chips.addStretch(1)

        def jump(self, area_id):
            if area_id in self.hidden():
                self.set_hidden(area_id, False)
            frame = self.frames.get(area_id)
            if frame is not None:
                self.scroll.ensureWidgetVisible(frame, 0, 0)

        def guard(self, area_id, what, exc):
            frame = self.frames.get(area_id)
            if frame is not None:
                frame.guard(what, exc)

        def _call(self, area_id, name, *args):
            fn = (_anchor()["areas"].get(area_id) or {}).get(name)
            if fn is None:
                return None
            try:
                return fn(*args)
            except Exception as exc:
                _guard_line(area_id, name, exc)
                return None

        def refresh_area(self, area_id, asked="refresh"):
            """One area against the context: refresh, then what it says on
            the header, the spine and to the others. *asked*: why (ASKED),
            on ctx.asked for these calls only."""
            frame = self.frames.get(area_id)
            if frame is None:
                return
            ctx = self.follower.ctx
            host = self.hosts.get(area_id)
            mode = host.mode if host is not None else "narrow"
            was, ctx.asked = ctx.asked, asked      # an update() inside a refresh nests
            try:
                if frame.content is not None and frame.fold != "collapsed":
                    self._call(area_id, "refresh", frame.content, ctx, mode)
                frame.set_summary(self._call(area_id, "summary", ctx))
                frame.tint_tools(ctx)
                effects = self._call(area_id, "effects", ctx)
            finally:
                ctx.asked = was
            st = _anchor()
            if effects is not None:
                st["effects"][area_id] = dict((k, [Effect(*e) for e in v])
                                              for k, v in effects.items())
            else:
                st["effects"].pop(area_id, None)

        def update_areas(self, area_id=None, paint=True, asked="refresh"):
            if area_id is None:
                ids = [a for a in _anchor()["order"] if a in self.frames]
            else:
                ids = [area_id] + [a for a in _anchor()["order"] if a in self.frames
                                   and area_id in (_anchor()["areas"].get(a) or {})
                                   .get("follows", ())]
            for a in ids:
                self.refresh_area(a, asked)
            if paint:
                self.paint_spine(hold=False)

        def paint_spine(self, hold=True):
            """The spine's marks: every area's overlay, then any preview.
            *hold*: resize it to the subject (only when the subject moves)."""
            ctx = self.follower.ctx
            self.spine.cut = ctx.cut
            self.spine.frame = ctx.frame
            self.spine.subject = set(s.key for s in ctx.segments)
            fills = {}
            bands = []
            extents = []
            for area_id in _anchor()["order"]:
                if area_id not in self.frames:
                    continue
                for m in self._call(area_id, "overlay", ctx) or ():
                    m = _as_mark(m)
                    if m is None:
                        continue
                    if m.style == "fill" and m.colour is not None:
                        fills[m.key] = m.colour
                    elif m.style == "band":
                        bands.append(m)
                if hold:
                    e = self._call(area_id, "extent", ctx)
                    if e:
                        extents.append(tuple(e))
            self.spine.fills = fills
            self.spine.bands = bands
            # band rows come from the overlays only: a preview never grows it
            rows = self.spine.band_rows_for(bands)
            if rows != self.spine.band_rows:
                self.spine.band_rows = rows
                if not hold:
                    self.spine.hold()             # the subject's extents, kept
            if hold:
                self.spine.hold(extents)
            self.show_preview()

        def show_preview(self):
            previews = _anchor()["previews"]
            marks, caption = [], None
            for area_id, (m, cap) in previews.items():
                marks += [x for x in (_as_mark(y) for y in m) if x is not None]
                caption = cap if cap is not None else caption
            self.spine.marks = marks
            head, lines = (caption or ("", []))
            self._cap_head.setText(head or "")
            self._cap.setText("\n".join(list(lines or [])[:3]))
            self.spine.update()

        # -- the subject ----------------------------------------------------------

        def beat(self, tab, force=False, asked=None):
            ctx, moved, settled, frame_moved = self.follower.tick(tab)
            if moved or force:
                self.close_popout()
                _anchor()["previews"].clear()
                self._said_subject(ctx)
                self.update_areas(None, paint=False,
                                  asked=asked or ("subject" if moved else "refresh"))
                self.paint_spine(hold=True)
            elif settled:
                self.update_areas(None, asked="settled")
            elif frame_moved:
                self.spine.frame = ctx.frame
                self.spine.update()

        def refresh_all(self):
            self.follower.rewalk()
            self.beat(self.follower.ctx.tab, force=True, asked="refresh")

        def focus(self, key):
            """The playhead to *key*'s first frame, and *key* the subject until
            the playhead moves on -- even where the focused track would give
            another segment there."""
            seg = self.follower.cut.by_key.get(key)
            if seg is None:
                return
            self.follower.reveal(key, seg.record_in)
            self._move(seg.record_in)

        def pick(self, key):
            """A segment clicked on the spine: the playhead to its first frame,
            the window pinned on it (the Takes Lens's click, forge-takes
            59b5b28). Unpin with the Pinned button."""
            seg = self.follower.cut.by_key.get(key)
            if seg is None:
                return
            self.follower.pin_keys([key])
            self._said_follow()
            self._move(seg.record_in, force=True)   # nothing read inside the click

        def scrub(self, frame, done=False):
            """The spine pressed and dragged: the positioner follows, on the
            idle queue, once per idle however many moves asked; the subject
            follows the playhead until the next click in the timeline."""
            self.follower.follow_playhead()
            pending = self._scrub_to is not None
            self._scrub_to = frame
            if not pending:
                def run():
                    to, self._scrub_to = self._scrub_to, None
                    if to is not None:
                        self._move(to, now=True)
                later(run)

        def _move(self, frame, now=False, force=False):
            def go():
                tl, seq = self.follower.tl, self.follower.tl.sequence()
                if seq is not None:
                    tl.move_to(seq, frame, self.follower.cut.start)
                self.beat(self.follower.ctx.tab, force=force)
            go() if now else later(go)

        def _toggle_pin(self):
            self.follower.pin(not self.follower.pinned)
            self._said_follow()
            self.beat(self.follower.ctx.tab, force=True)

        def _said_follow(self):
            pinned = bool(self.follower.pinned)
            self._follow_btn.setText("Pinned" if pinned else "Following")
            self._follow_btn.setToolTip(
                "Stays on this segment - click to follow the timeline" if pinned else
                "Follows a click in the timeline, else the playhead on the focused "
                "track - click to stay on this one")

        def _said_subject(self, ctx):
            p = ctx.primary
            if p is None:
                said = '<span style="color:#8a93a4;">{0}</span>'.format(
                    "No sequence open in the Timeline" if not ctx.sequence else
                    "Nothing under the playhead")
            else:
                more = len(ctx.segments) - 1
                word = {"selection": "selected", "playhead": "at the playhead",
                        "pin": "pinned", "click": "clicked"}.get(ctx.source, "")
                said = '<b style="color:#e6e9ef;">{0}</b>{1}&nbsp;&nbsp;' \
                       '<span style="color:#8a93a4;">{2}</span>'.format(
                           _escape(p.name), " +{0}".format(more) if more > 0 else "", word)
                top = next((s for s in ctx.over if s.kind == "picture"), None)
                if top is not None:
                    said += '&nbsp;&nbsp;<span style="color:{0};">under {1}</span>'.format(
                        AMBER, _escape(top.name))
            self._subject.setText(said)
            self._said_follow()

        # -- popouts ----------------------------------------------------------------

        def close_popout(self):
            if self._popout is not None:
                self._popout.close()
                self._popout.deleteLater()
                self._popout = None
            for host in self.hosts.values():
                graph = getattr(host, "graph", None)
                if graph is not None and hasattr(graph, "unlit"):
                    try:
                        graph.unlit()
                    except Exception:
                        pass

        def pop(self, host, card, frame, what, note, paragraphs, title=None, mono=False):
            key = (card["id"], what)
            mine = (self._popout is not None and getattr(self._popout, "key", None) == key
                    and getattr(self._popout, "area_id", None) == host.area_id)
            self.close_popout()
            if mine:
                return
            self._popout = _ListPopout(self, frame, key, title or card["short"], note,
                                       paragraphs, self.close_popout, host, mono=mono)
            self._popout.area_id = host.area_id
            self._popout.place()
            self._popout.show()

        def popout_widget(self, area_id, beside, content):
            self.close_popout()
            host = self.hosts.get(area_id)
            if host is None:
                return
            self._popout = _WidgetPopout(self, beside, (area_id, id(content)), content,
                                         self.close_popout, host)
            self._popout.place()
            self._popout.show()

        def place_popout(self, *_args):
            if self._popout is not None:
                self._popout.place()

        # -- the two layouts ---------------------------------------------------------

        def set_mode(self, mode):
            if mode == self.mode:
                return
            self.remember()
            self.close_popout()
            self.mode = mode
            _save_state(mode=mode)
            self._apply_mode()
            for frame in self.frames.values():
                frame.head()
                frame.apply_fold()
            self.update_areas(None, asked="layout")

        def _apply_mode(self):
            narrow = self.mode == "narrow"
            self._mode_btn.setText("Wide" if narrow else "Narrow")
            self._mode_btn.setToolTip("Spread the Lens out" if narrow else
                                      "Fold the Lens into a column")
            self.scroll.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarAlwaysOff if narrow else QtCore.Qt.ScrollBarAsNeeded)
            self.setMinimumSize(*((280, 300) if narrow else (900, 360)))
            self._switching = True
            try:
                self.setGeometry(self._placed())
            finally:
                self._switching = False

        def _placed(self):
            saved = _load_state().get(self.mode)
            if isinstance(saved, list) and len(saved) == 4:
                rect = QtCore.QRect(*[int(v) for v in saved])
                if any(s.availableGeometry().intersects(rect)
                       for s in QtGui.QGuiApplication.screens()):
                    return rect
            screen = (QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
                      or QtGui.QGuiApplication.primaryScreen())
            area = screen.availableGeometry()
            if self.mode == "narrow":
                return QtCore.QRect(area.right() - NARROW_WIDTH + 1, area.top(), NARROW_WIDTH,
                                    area.height())
            w, h = min(1240, area.width()), min(620, area.height())
            return QtCore.QRect(area.left() + (area.width() - w) // 2,
                                area.top() + (area.height() - h) // 3, w, h)

        def remember(self):
            g = self.geometry()
            _save_state(**{self.mode: [g.x(), g.y(), g.width(), g.height()]})

        # -- the window: painted, dragged and sized by hand, as the HUD is -----------

        def showEvent(self, event):                  # noqa: N802
            QtWidgets.QWidget.showEvent(self, event)
            _onto_its_screen(self)
            handle = self.windowHandle()
            if handle is not None and handle is not self._pen_window:
                handle.installEventFilter(self._pen_watch)
                self._pen_window = handle

        def hideEvent(self, event):                  # noqa: N802
            if not self._switching:
                self.remember()
            self.close_popout()
            QtWidgets.QWidget.hideEvent(self, event)

        def paintEvent(self, event):                 # noqa: N802
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            p.setBrush(QtGui.QColor(20, 22, 28, 235))
            p.setPen(QtGui.QPen(QtGui.QColor(58, 63, 79), 1))
            p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 9, 9)

        def resizeEvent(self, event):                # noqa: N802
            QtWidgets.QWidget.resizeEvent(self, event)
            self.place_popout()
            for grip in self._grips:
                grip.move(0 if grip.left else self.width() - grip.width(),
                          self.height() - grip.height())
                grip.raise_()

        def _in_header(self, pos):
            if not self._header.geometry().contains(pos):
                return False
            return not isinstance(self.childAt(pos), QtWidgets.QAbstractButton)

        def mousePressEvent(self, event):            # noqa: N802
            pos = event.position().toPoint()
            if event.button() == QtCore.Qt.LeftButton and self._in_header(pos):
                self._press = event.globalPosition().toPoint()
                self._offset = self._press - self.frameGeometry().topLeft()
                self._moved = self._manual = False
                return
            QtWidgets.QWidget.mousePressEvent(self, event)

        def mouseMoveEvent(self, event):             # noqa: N802
            if self._press is None:
                QtWidgets.QWidget.mouseMoveEvent(self, event)
                return
            here = event.globalPosition().toPoint()
            if not self._moved and (here - self._press).manhattanLength() < 5:
                return
            if not self._moved:
                self._moved = True
                try:
                    handle = self.windowHandle()
                    if handle is not None and handle.startSystemMove():
                        self._press = None
                        return
                except Exception:
                    pass
                self._manual = True
            if self._manual:
                self.move(here - self._offset)

        def mouseReleaseEvent(self, event):          # noqa: N802
            if self._press is None:
                QtWidgets.QWidget.mouseReleaseEvent(self, event)
                return
            self._press = None
            if self._moved:
                self.remember()

        def moveEvent(self, event):                  # noqa: N802
            QtWidgets.QWidget.moveEvent(self, event)
            if self.isVisible():
                _onto_its_screen(self)               # its menus open where it is
            if self.isVisible() and not self._switching:
                self.remember()                      # a system move sends no release
            self.place_popout()


def on_release(widget, fn):
    """*fn* on a click of *widget*, acted on at release, inside it: the
    host's filter, so no area installs its own (r3)."""
    if QtWidgets is not None:
        _clicks(widget).click = fn


def on_double(widget, fn):
    """*fn* on a double-click of *widget*."""
    if QtWidgets is not None:
        _clicks(widget).double = fn


# --- reload adoption --------------------------------------------------------
# A rescan that reloads this module leaves the previous window running old
# code: close it, and open one with the new code if it was showing. The
# registry (on builtins) carries the areas across untouched; each area's
# build runs again for the new window.

def _adopt_previous():
    st = _anchor()
    old = st.get("window")
    if old is None:
        return
    try:
        was = old.isVisible() or st.get("away")
    except Exception:
        was = False
    try:
        old.close_popout()
        old.close()
        old.deleteLater()
    except Exception:
        pass
    st["window"] = None
    st["poster"] = None
    if was:
        try:
            later(open)
        except Exception:
            pass


_adopt_previous()
