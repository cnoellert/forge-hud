"""forge_lens without Qt: the cut, the labels, the follow rule, cross-reading,
the off-thread read. ``pytest tests`` (Qt not needed; the window has its own
offscreen check, tests/render_lens.py)."""

import os
import sys
import threading

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fakeflame  # noqa: E402
import forge_lens as fl  # noqa: E402

TAKES_SRC = os.path.join(ROOT, "..", "forge-takes", "src")
needs_linktest2 = pytest.mark.skipif(not os.path.exists(fakeflame.LINKTEST2),
                                     reason="forge-takes checkout not beside this one")


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    monkeypatch.setattr(fl, "STATE_PATH", str(tmp_path / "lens.json"))
    import builtins
    monkeypatch.delattr(builtins, "_forge_lens_state", raising=False)
    sys.modules.pop("flame", None)
    yield
    sys.modules.pop("flame", None)


def rows_of(cut):
    """The cut as forge-takes' TimelineHost walks it, track then record."""
    seq = fakeflame.Sequence(cut)
    rows = []
    for ti, track in enumerate(seq.version.tracks):
        for s in track.segments:
            rows.append({"track": ti, "record_in": s.record_in.frame,
                         "record_out": s.record_out.frame, "segment": s.name,
                         "shot": s.shot_name, "media": s.file_path,
                         "effects": bool(s.effects), "gap": s.gap})
    return rows


# --- keys and labels, pinned against forge-takes ------------------------------

@needs_linktest2
def test_shot_keys_match_forge_takes_and_the_snapshot():
    cut = fakeflame.linktest2()["cut"]
    rows = rows_of(cut)
    mine = fl.shot_keys(rows)
    assert sorted(k for k, _ in mine) == sorted(c["key"] for c in cut)
    sys.path.insert(0, TAKES_SRC)
    try:
        from forge_takes.timeline import shot_keys
    except Exception:
        pytest.skip("forge_takes not importable")
    assert mine == shot_keys(rows)


@needs_linktest2
def test_labels_match_forge_takes_segment_label():
    cut = fakeflame.linktest2()["cut"]
    model = fl.Cut.from_rows(rows_of(cut))
    sys.path.insert(0, TAKES_SRC)
    try:
        from forge_takes.ui import segment_label
    except Exception:
        pytest.skip("forge_takes.ui not importable")
    info = dict((c["key"], {"track": c["track"], "gap": c["gap"],
                            "shot": "" if c["gap"] else "x"}) for c in cut)
    for s in model.segs:
        assert s.name == segment_label(info, s.key), s.key
    names = dict((s.key, s.name) for s in model.segs)
    assert names["GMM_430 (track 2)"] == "GMM_430 · V2"
    assert names["GMM_430"] == "GMM_430 · V1"
    assert names["GMM_400"] == "GMM_400"
    assert names["gap on track 3 at 86448"] == "Gap on track 3"


# --- the subject ----------------------------------------------------------------

def follower(seq):
    flame = fakeflame.module(seq)
    sys.modules["flame"] = flame
    return fl.Follower(fl.Timeline(flame)), flame


def focus_on(seq, track):
    seq.primary_track = seq.version.tracks[track]


@needs_linktest2
def test_the_playhead_finds_the_top_picture_not_the_fx_gap():
    """LINKTEST2: track 3's Gap Timeline FX covers the whole cut. At
    GMM_230's first frames the viewer shows V2's GMM_410 over it, and with
    the focus on the gap's track that is the subject -- never "Gap on track
    3" [LIVE 2027.1, 2026-11-01]."""
    seq = fakeflame.Sequence(fakeflame.linktest2()["cut"])
    focus_on(seq, 2)
    f, _ = follower(seq)
    seq._now = fakeflame.Time(86600)                # GMM_230's 5th frame
    ctx, moved, _s, _f = f.tick("Timeline")
    assert moved and ctx.source == "playhead"
    assert ctx.primary.key == "GMM_410 (track 2)" and ctx.primary.name == "GMM_410 · V2"
    assert [s.name for s in ctx.over] == ["Gap on track 3"]
    assert ctx.visible.key == "GMM_410 (track 2)"
    assert ctx.primary.version == "v01"
    assert "forge_takes:seq_1" in ctx.tags


@needs_linktest2
def test_the_playhead_reads_the_focused_track_not_the_top_one():
    """Chris, 2026-11-01: "the playhead can be over something, a second
    layer, and be reading that when the focus is actually on the track
    beneath." The focus is seq.primary_track."""
    seq = fakeflame.Sequence(fakeflame.linktest2()["cut"])
    focus_on(seq, 0)
    f, _ = follower(seq)
    walks = []
    real = f.tl.walk
    f.tl.walk = lambda s: walks.append(1) or real(s)
    seq._now = fakeflame.Time(86600)
    ctx, moved, _s, _f = f.tick("Timeline")
    assert ctx.source == "playhead" and ctx.primary.key == "GMM_230"
    assert ctx.visible.key == "GMM_230"                    # the player, from V1 down
    assert [s.key for s in ctx.over] == ["gap on track 3 at 86448", "GMM_410 (track 2)"]
    # the focus up a track: the subject moves, with no walk of the cut
    focus_on(seq, 1)
    ctx, moved, _s, _f = f.tick("Timeline")
    assert moved and ctx.primary.key == "GMM_410 (track 2)" and len(walks) == 1
    assert f.focus_track == 1
    assert ctx.visible.key == "GMM_410 (track 2)"
    # a focused track empty at the frame looks DOWN, never up [Chris, live]
    seq._now = fakeflame.Time(86450)                        # GMM_400, V1 only
    ctx, moved, _s, _f = f.tick("Timeline")
    assert ctx.primary.key == "GMM_400"
    focus_on(seq, 2)                                         # the FX gap's track
    seq._now = fakeflame.Time(86600)
    ctx, _m, _s, _f = f.tick("Timeline")
    assert ctx.primary.key == "GMM_410 (track 2)"            # a picture beneath it


def test_an_empty_focus_looks_down_not_up():
    """TST_publish, 86894 [LIVE 2027.1, 2026-11-01]: the P on track 1 (L02),
    empty there; L01 on track 0 beneath, L03 on track 2 above. The subject
    is L01. With nothing at or below, nothing -- Flame shows black."""
    cut = fl.Cut([fl.Seg("TST_040_L01", "TST_040_L01", 0, 86860, 86920, None, "picture"),
                  fl.Seg("TST_040_L03", "TST_040_L03", 2, 86880, 86900, None, "picture"),
                  fl.Seg("TST_050_L03", "TST_050_L03", 2, 86921, 86940, None, "picture")])
    assert cut.under_playhead(86894, 1).key == "TST_040_L01"
    assert cut.under_playhead(86894, 2).key == "TST_040_L03"
    assert cut.under_playhead(86930, 1) is None
    assert cut.under_playhead(86930, None).key == "TST_050_L03"


@needs_linktest2
def test_a_focus_the_walk_doesnt_know_walks_once_not_every_beat():
    seq = fakeflame.Sequence(fakeflame.linktest2()["cut"])
    f, _ = follower(seq)
    walks = []
    real = f.tl.walk
    f.tl.walk = lambda s: walks.append(1) or real(s)
    seq._now = fakeflame.Time(86600)
    f.tick("Timeline")
    seq.primary_track = fakeflame.Track([])                 # another version's
    for _ in range(4):
        ctx, _m, _s, _f = f.tick("Timeline")
    assert len(walks) == 2 and ctx.primary.key == "GMM_410 (track 2)"


@needs_linktest2
def test_a_click_leads_until_the_playhead_moves():
    """A plain click selects nothing in Flame; the clicked segment is the
    subject until the playhead moves on, then the playhead leads again."""
    seq = fakeflame.Sequence(fakeflame.linktest2()["cut"])
    focus_on(seq, 1)
    f, flame = follower(seq)
    seq._now = fakeflame.Time(86600)
    f.tick("Timeline")
    flame.timeline.current_segment = seq.seg("GMM_230")     # beneath the playhead's
    ctx, moved, _s, _f = f.tick("Timeline")
    assert moved and ctx.source == "click" and ctx.primary.key == "GMM_230"
    ctx, moved, _s, _f = f.tick("Timeline")
    assert not moved and ctx.source == "click"
    seq._now = fakeflame.Time(86601)
    ctx, moved, _s, _f = f.tick("Timeline")
    assert moved and ctx.source == "playhead" and ctx.primary.key == "GMM_410 (track 2)"
    # a click that moved the positioner in the same beat: the click wins
    flame.timeline.current_segment = seq.seg("GMM_400")
    seq._now = fakeflame.Time(86450)
    ctx, moved, _s, _f = f.tick("Timeline")
    assert ctx.source == "click" and ctx.primary.key == "GMM_400"
    # twins by name: the segment itself decides, not (name, record in)
    flame.timeline.current_segment = seq.seg("GMM_430")
    ctx, _m, _s, _f = f.tick("Timeline")
    assert ctx.primary.key == "GMM_430"
    flame.timeline.current_segment = seq.seg("GMM_430 (track 2)")
    ctx, _m, _s, _f = f.tick("Timeline")
    assert ctx.primary.key == "GMM_430 (track 2)"


@needs_linktest2
def test_reveal_holds_until_the_playhead_lands_then_moves_on():
    """focus(key): the subject is key while the playhead travels there (on
    the idle queue) and until it moves on from there."""
    seq = fakeflame.Sequence(fakeflame.linktest2()["cut"])
    focus_on(seq, 1)
    f, _ = follower(seq)
    seq._now = fakeflame.Time(86450)
    f.tick("Timeline")
    g230 = f.cut.by_key["GMM_230"]
    f.reveal("GMM_230", g230.record_in)
    ctx, _m, _s, _f = f.tick("Timeline")                     # not there yet
    assert ctx.source == "click" and ctx.primary.key == "GMM_230"
    seq._now = fakeflame.Time(g230.record_in)                # landed
    ctx, _m, _s, _f = f.tick("Timeline")
    assert ctx.primary.key == "GMM_230"
    seq._now = fakeflame.Time(g230.record_in + 1)
    ctx, _m, _s, _f = f.tick("Timeline")
    assert ctx.source == "playhead"


@needs_linktest2
def test_selection_beats_the_playhead_and_a_click_ends_spine_follow():
    seq = fakeflame.Sequence(fakeflame.linktest2()["cut"])
    focus_on(seq, 1)
    f, flame = follower(seq)
    seq._now = fakeflame.Time(86600)
    f.tick("Timeline")
    g230 = seq.seg("GMM_230")
    g230.selected = True
    flame.timeline.current_segment = g230           # the click
    ctx, moved, _s, _f = f.tick("Timeline")
    assert moved and ctx.source == "selection" and ctx.primary.key == "GMM_230"
    # under it at the playhead: V2's GMM_410, then the gap
    assert [s.key for s in ctx.over] == ["gap on track 3 at 86448", "GMM_410 (track 2)"]
    # the spine used: the playhead leads, the selection still there
    f.follow_playhead()
    ctx, moved, _s, _f = f.tick("Timeline")
    assert ctx.source == "playhead" and ctx.primary.key == "GMM_410 (track 2)"
    # a click in the timeline ends that
    g400 = seq.seg("GMM_400")
    g400.selected = True
    g230.selected = False
    flame.timeline.current_segment = g400
    ctx, moved, _s, _f = f.tick("Timeline")
    assert ctx.source == "selection" and ctx.primary.key == "GMM_400"


@needs_linktest2
def test_the_pin_holds_and_settled_comes_after_two_quiet_beats():
    seq = fakeflame.Sequence(fakeflame.linktest2()["cut"])
    f, _ = follower(seq)
    seq._now = fakeflame.Time(86450)
    ctx, moved, settled, _f = f.tick("Timeline")
    assert moved and not ctx.settled and not settled
    ctx, moved, settled, _f = f.tick("Timeline")
    assert not moved and not ctx.settled
    ctx, moved, settled, _f = f.tick("Timeline")
    assert ctx.settled and settled                   # flips once
    ctx, moved, settled, _f = f.tick("Timeline")
    assert ctx.settled and not settled
    f.pin(True)
    seq._now = fakeflame.Time(86700)                 # play on
    ctx, moved, settled, frame_moved = f.tick("Timeline")
    assert ctx.source == "pin" and ctx.primary.key == "GMM_400" and frame_moved
    assert ctx.playing                               # 250 frames in a beat


@needs_linktest2
def test_the_same_segment_on_another_version_moves_the_subject():
    seq = fakeflame.Sequence(fakeflame.linktest2()["cut"])
    f, _ = follower(seq)
    seq._now = fakeflame.Time(86450)
    f.tick("Timeline")
    f.tick("Timeline")
    seq.seg("GMM_400").version_uid = "v02"
    ctx, moved, _s, _f = f.tick("Timeline")
    assert moved and ctx.primary.version == "v02"


@needs_linktest2
def test_playback_inside_a_segment_moves_only_the_frame():
    seq = fakeflame.Sequence(fakeflame.linktest2()["cut"])
    f, _ = follower(seq)
    seq._now = fakeflame.Time(86450)
    f.tick("Timeline")
    seq._now = fakeflame.Time(86452)
    ctx, moved, _s, frame_moved = f.tick("Timeline")
    assert not moved and frame_moved and ctx.playing


def test_no_sequence_is_an_empty_subject():
    f, _ = follower(None)
    ctx, moved, _s, _f = f.tick("Timeline")
    assert ctx.primary is None and ctx.segments == ()


@needs_linktest2
def test_move_to_counts_from_the_sequence_start():
    seq = fakeflame.Sequence(fakeflame.linktest2()["cut"])
    f, flame = follower(seq)
    f.tl.move_to(seq, 86600, start=seq.start_time.frame)
    assert seq.current_time.frame == 86600
    # the live case: a start of 86400, PyTime(350) is 86749
    seq.current_time = flame.PyTime(350)
    assert seq.current_time.frame == 86749
    f.tl.move_to(seq, 86750, start=86400)
    assert seq.current_time.frame == 86750


# --- cross-reading ------------------------------------------------------------------

@needs_linktest2
def test_same_as_matches_a_take_and_a_version_by_content_only():
    snap = fakeflame.linktest2()
    main = tuple(tuple(e) for e in snap["segments"]["GMM_410 (track 2)"]["signature"])
    assert main == (("Timewarp", False, "35ed1e3fcb69953c"), ("Resize", False, "b991e0c441855d87"))
    st = fl._anchor()
    st["effects"]["takes.takes"] = {"GMM_410 (track 2)": [fl.Effect("switch to Main", main)]}
    st["effects"]["streams.versions"] = {"GMM_410 (track 2)": [
        fl.Effect("roll back to v04-v08 · v10", main),
        fl.Effect("roll back to v09 · v11", main + (("Colour Correct", False, "d716"),))]}
    assert fl.same_as("streams.versions", "GMM_410 (track 2)", main) == \
        [("takes.takes", "switch to Main")]
    assert fl.same_as("takes.takes", "GMM_410 (track 2)", main) == \
        [("streams.versions", "roll back to v04-v08 · v10")]
    assert fl.same_as("takes.takes", "GMM_230", main) == []


# --- off Flame's thread ---------------------------------------------------------------

def test_read_hands_back_the_newest_and_says_late():
    got, late = [], []
    gate = threading.Event()

    def slow():
        gate.wait(2)
        return "old"
    fl.read(slow, got.append, key="seg")
    fl.read(lambda: "new", got.append, key="seg")    # supersedes
    for t in threading.enumerate():
        if t.name == "forge-lens-read" and t is not threading.current_thread():
            t.join(0.5)
    gate.set()
    for t in threading.enumerate():
        if t.name.startswith("forge-lens") and t is not threading.current_thread():
            t.join(2)
    assert got == ["new"]
    stuck = threading.Event()
    fl.read(lambda: stuck.wait(2), got.append, late=lambda: late.append(1), wait=0.05)
    for t in threading.enumerate():
        if t.name == "forge-lens-late":
            t.join(2)
    stuck.set()
    assert late == [1]


def test_later_runs_on_the_idle_queue_never_inline():
    flame = fakeflame.module(None)
    sys.modules["flame"] = flame
    ran = []
    fl.later(lambda: ran.append(1))
    assert ran == [] and len(flame.idle) == 1
    flame.idle.pop()()
    assert ran == [1]


def test_state_is_saved_as_it_is_written():
    s = fl.state("streams.depends", "wide")
    s["sections"] = {"output": "collapsed"}
    assert fl.state("streams.depends", "wide")["sections"] == {"output": "collapsed"}
    assert fl.state("streams.depends", "narrow") == {}


def test_register_replaces_by_id_without_qt():
    fl.register_area("a.one", "One", build=lambda p, c: None, refresh=lambda w, c, m: None)
    fl.register_area("a.one", "Uno", build=lambda p, c: None, refresh=lambda w, c, m: None)
    assert fl._anchor()["order"] == ["a.one"]
    assert fl._anchor()["areas"]["a.one"]["title"] == "Uno"
