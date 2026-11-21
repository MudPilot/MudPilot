"""Record Path / Record Loop from the map: walk it for real and MudPilot writes it down.

Every room change while recording becomes a step (the exit MME has from the room you left to the one you're in);
a move that fails ("There is no exit in that direction!", a closed door) changes no room, so it's never recorded.
Door commands you send on the way (open / bash / unlock / pick) go on the step that goes through that door.
Saved through the same route → .mp code as the Path builder, so it lands with your other paths and loops."""
from __future__ import annotations

import re
import time

DOOR_RE = re.compile(r"^\s*(?:op|ope|open|ba|bas|bash|unl|unlo|unloc|unlock|pi|pic|pick|picklock)\s+\S+", re.I)


class RouteRecorder:
    def __init__(self, session):
        self.s = session
        self.mode = None             # "path" / "loop" while recording
        self.start = None
        self.route = []              # Exits and door commands, in order (what route_to_mpath takes)
        self.rooms = []              # the rooms walked, start first (for the map)
        self._last = None
        self._doors = []             # door commands since the last step
        self._skip_back = None       # (from, to): the walk back after Undo isn't a step
        self.on_change = None        # the map bar's refresh
        self.draw = False            # drawing on the map with the number pad (nothing sent to the game)

    @property
    def active(self) -> bool:
        return self.mode is not None

    def steps(self) -> int:
        return sum(1 for x in self.route if not isinstance(x, str))

    def here(self):
        st = self.s.state
        return st.room

    def start_rec(self, mode: str, at=None, draw: bool = False) -> str | None:
        """draw: the number pad walks a pen round the map from `at` — nothing is sent to the game, and it's a lot
        quicker than walking it (Dan, 2026-11-01)."""
        here = tuple(at) if at else self.here()
        if not here:
            return "Your room isn't known yet — press Enter in the game first, or click a room on the map."
        self.draw = draw
        self.mode, self.start = mode, here
        self.route, self.rooms, self._doors, self._skip_back = [], [here], [], None
        self._last = here
        self.s.log(f"Recording a {mode} from {here[0]}/{here[1]} — walk it; Stop/Save when you're done")
        self._changed()
        return None

    def cancel(self):
        if self.active:
            self.s.log("Recording cancelled")
        self.mode = None
        self.route, self.rooms = [], []
        self._changed()

    def _changed(self):
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    # ------------------------------------------------------------ what goes out / where you are
    def note_sent(self, cmd: str):
        if self.active and DOOR_RE.match(cmd or ""):
            self._doors.append(cmd.strip())

    def poll(self):
        if not self.active or getattr(self, "draw", False):
            return
        here = self.here()
        if not here or here == self._last:
            return
        frm, self._last = self._last, here
        if self._skip_back and self._skip_back == (frm, here):
            self._skip_back = None           # walking back after Undo
            return
        self._skip_back = None
        w = self.s.world
        r = w.room(frm)
        ex = next((e for e in (r.exits.values() if r else ()) if e.to == here), None)
        if ex is not None:
            legs = [ex]
        else:
            # not one exit away (a teleport, a missed room display): the shortest way MME knows, if it's short
            legs = w.route(frm, here, max_nodes=4000) if hasattr(w, "route") else None
            if not legs or len(legs) > 6:
                self.s.log(f"Recording: couldn't tell how you got from {frm[0]}/{frm[1]} to {here[0]}/{here[1]} — "
                           "not recorded; Undo or walk back")
                self._last = frm
                return
        self.route += self._doors + legs
        self._doors = []
        self.rooms += [e.to for e in legs]
        self._changed()

    def step(self, d: str) -> bool:
        """Draw mode: the pen goes one exit d (N, SE, U…) from where it is. False = no such exit there."""
        if not self.active or not getattr(self, "draw", False):
            return False
        r = self.s.world.room(self._last)
        ex = r.exits.get(d) if r else None
        if ex is None or not ex.to:
            return False
        self.route.append(ex)
        self.rooms.append(ex.to)
        self._last = ex.to
        self._changed()
        return True

    @property
    def pen(self):
        return self._last

    def undo(self) -> bool:
        """Take the last step off (walk back to where it started and carry on)."""
        if not any(not isinstance(x, str) for x in self.route):
            return False
        if getattr(self, "draw", False):
            while self.route and isinstance(self.route[-1], str):
                self.route.pop()
            self.route.pop()
            if len(self.rooms) > 1:
                self.rooms.pop()
            self._last = self.rooms[-1]
            self._changed()
            return True
        while self.route and isinstance(self.route[-1], str):
            self.route.pop()
        ex = self.route.pop()
        while self.route and isinstance(self.route[-1], str):
            self.route.pop()                  # its door commands go with it
        if len(self.rooms) > 1:
            self.rooms.pop()
        back = self.rooms[-1]
        here = self.here() or ex.to
        self._last = here
        self._skip_back = (here, back) if here == ex.to else None
        self._doors = []
        self.s.log(f"Recording: last step taken off — {self.steps()} steps (walk back to {back[0]}/{back[1]})")
        self._changed()
        return True

    # ------------------------------------------------------------ saving
    def back_at_start(self) -> bool:
        return (self._last if getattr(self, "draw", False) else self.here()) == self.start

    def build(self, name: str):
        """(MPath, "") or (None, why)."""
        from .pathbuilder import route_to_mpath
        if not self.steps():
            return None, "Nothing recorded yet — walk at least one step."
        if self.mode == "loop" and not self.back_at_start():
            return None, "Not back at the start yet."
        cur = self.rooms[-1]
        here = self.here()
        if here and here != cur and not getattr(self, "draw", False):
            return None, f"You're in {here[0]}/{here[1]}, not where the recording ends ({cur[0]}/{cur[1]})."
        return route_to_mpath(self.s.world, self.start, list(self.route), name)

    def label(self) -> str:
        if not self.active:
            return ""
        return f"● REC {self.mode} · {self.steps()} step{'s' if self.steps() != 1 else ''}"

    def finish(self):
        self.mode = None
        self.route, self.rooms = [], []
        self._changed()
