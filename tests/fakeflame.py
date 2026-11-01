"""A stand-in for the bits of ``flame`` the Lens reads, built from a cut as
forge-takes' ``lens.snapshot`` writes one (``key``, ``record_in``,
``record_out``, ``track`` 0-based, ``gap``)."""

import json
import os
import re
import types

HERE = os.path.dirname(os.path.abspath(__file__))
#: forge-takes' LINKTEST2 snapshot, when its checkout sits beside this one.
LINKTEST2 = os.path.join(HERE, "..", "..", "forge-takes", "docs", "lens",
                         "linktest2-takes-area.json")
_TRACKED = re.compile(r"^(.*) \(track \d+\)$")


class Time(object):
    def __init__(self, frame, relative=False):
        self.frame, self.relative = int(frame), relative


class Segment(object):
    def __init__(self, row):
        key = row["key"]
        self.gap = bool(row.get("gap"))
        m = _TRACKED.match(key)
        self.name = "" if self.gap else (m.group(1) if m else key)
        self.shot_name = self.name
        self.file_path = "" if self.gap else "/media/{0}.mov".format(self.name)
        self.type = "Gap Timeline FX" if self.gap else "Video Segment"
        self.effects = ["Source Colour Mgmt"] if self.gap else []
        self.record_in, self.record_out = Time(row["record_in"]), Time(row["record_out"])
        self.selected = False
        self.version_uid = "v01"
        self.track = row["track"]


class Track(object):
    def __init__(self, segments):
        self.segments = segments


class Sequence(object):
    def __init__(self, cut, name="LINKTEST2", uid="seq_1", start=86400):
        tracks = max(r["track"] for r in cut) + 1
        self.segs = [Segment(r) for r in cut]
        by_track = [sorted([s for s in self.segs if s.track == t],
                           key=lambda s: s.record_in.frame) for t in range(tracks)]
        self.version = types.SimpleNamespace(tracks=[Track(t) for t in by_track])
        self.versions = [self.version]
        self.primary_track = self.version.tracks[0]
        self.name, self.uid, self.tags = name, uid, ["forge_takes:" + uid]
        self.start_time = Time(start)
        self._now = Time(cut[0]["record_in"])

    @property
    def current_time(self):
        return self._now

    @current_time.setter
    def current_time(self, t):
        # PyTime(n): the n-th frame counted from 1 at start_time [LIVE 2027.1,
        # 2026-11-01: PyTime(350) -> 86749 on a start of 86400]
        f = (self.start_time.frame + t.frame - 1) if t.relative else t.frame
        self._now = Time(f)

    def seg(self, key):
        m = _TRACKED.match(key)
        name = m.group(1) if m else key
        hits = sorted([s for s in self.segs if s.name == name], key=lambda s: s.track)
        return hits[-1] if m else hits[0]


def module(seq=None):
    """A ``flame`` with *seq* open in the Timeline."""
    fl = types.ModuleType("flame")
    fl.timeline = types.SimpleNamespace(clip=seq, current_segment=None)
    fl.PyTime = lambda n: Time(n, relative=True)
    fl.idle = []
    fl.schedule_idle_event = fl.idle.append
    return fl


def linktest2():
    with open(LINKTEST2) as fh:
        return json.load(fh)
