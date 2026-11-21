"""Camp lairs: stand by a handful of lairs you mark and step into each one as it comes back — never early.

(0.8.201, Dan: MudPlay's Auto-Lair, as its own engine. Off unless you start it; the old loop "lair pacing"
(Automation.LAIR_PACING) stays switched off — this doesn't touch it.)

How it goes, over and over:
  • pick the next lair: the closest one that will be back by the time we walk in; none will → the one that's back
    soonest, counting the walk (Settings → "throughput" instead: the one we'd be least late for);
  • walk to its wait room — the neighbour on the way in that isn't itself a marked lair — and wait there until the
    lair's respawn time. That instant is worked out once, as we get there (worked out again every tick, MudPlay's
    character never left the wait room);
  • one step in, fight, loot, and out: no fight inside 3 s = empty, move on; a fight that won't end is given 30 s;
  • after each lair, the same end-of-lap checks a loop makes (stash, train, bank / sell / buy, lights, scrolls):
    a trip goes, and comes back to camping.

Respawn time T per lair, from MME's Rooms.Delay (minutes):
  • Stock: the clock runs from the room's last kill, Delay×60 + 30 s;
  • Paradigm: from our last entry, (Delay−1)×60 + 30 s;
  • what lairclock.py has learned for the room wins over both (measured from the room going empty = the last kill).
No kill or entry seen since Start = ready now. A reconnect keeps the clocks (nightly cleanup doesn't reset lairs).
"""
from __future__ import annotations

import re
import time

from .loopbuild import bfs, DEFAULT_REFILL

GRACE = 3.0             # in the lair and no fight by then: it's empty
FIGHT_CAP = 30.0        # a fight (or monsters we won't fight) holding us in a lair longer than this: leave when we can
LOOT_SECS = 2.0         # quiet after the last kill before leaving: the loot gets picked up
BACKOFF_FIRST = 2.0     # a failed entry: try that lair again after 2 s, 4, 8 … 60
BACKOFF_MAX = 60.0
NO_ROUTE_SECS = 30.0    # "no way there" is believed this long, then asked again
WALK_CHECK = 3.0        # a walk we started that isn't walking (and isn't there) after this long has stopped
RESUME_SETTLE = 3.0     # back from a trip / reconnect: let the room, stash and prompts settle first
REPICK_SECS = 1.0       # how often the choice is looked at again
MAX_HOPS = 150
PAUSE_WORDS = ("Stopped by", "Paused: you moved", "Hung up", "Hands off", "Stopped: character died", "Disconnected")
DOOR_RE = re.compile(r"\bdoor\b|\block(?:ed)?\b|\bbash\b|\bpick\b", re.I)


def realm_of(session) -> str:
    """'paradigm' or 'stock': which rules this board plays by (the board or host saying Paradigm, else Stock)."""
    cfg = session.settings
    txt = f"{getattr(cfg, 'board', '') or ''} {getattr(cfg, 'host', '') or ''}".lower()
    return "paradigm" if ("paradigm" in txt or "paramud" in txt) else "stock"


def respawn_secs(delay, realm: str):
    """Seconds after the clock start a lair is back, from MME's Delay (minutes); None when MME has no delay."""
    d = int(delay or 0)
    if d <= 0:
        return None
    if realm == "paradigm":
        return float(max(30, (d - 1) * 60 + 30))
    return float(d * 60 + 30)


def room_key(text):
    m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", str(text or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


class LairCamp:
    def __init__(self, session):
        self.s = session
        self.on = False
        self.state = "off"           # choose / approach / wait / enter / engage / paused
        self.status = "Not camping"
        self.target = None           # the lair we're working on
        self.wait_room = None
        self.entry_at = 0.0          # latched once in the wait room (MudPlay's pitfall: recomputed every tick)
        self.anchors: dict = {}      # room -> {"kill": t, "entry": t}
        self.backoff: dict = {}      # room -> (until, secs)
        self.no_route: dict = {}     # room -> until
        self.dropped: dict = {}      # room -> why (behind a door we can't open): out for this run
        self._disp = None            # the walk we asked for: {"dest", "purpose", "at", "ok"}
        self._engage = None
        self._conn = None
        self._room_prev = None
        self._next_look = 0.0
        self._resume_at = 0.0
        self._started_at = 0.0
        self._dist = (None, 0.0, {})
        self._said: dict = {}
        from .megamud_files import MPath
        # what the end-of-lap trips (stash, train, bank…) are told to come back to: Automation.start_path sees the
        # flag and hands back to camping instead of walking a path (0.8.201)
        self.mp = MPath(name="Camp lairs", author="MudPilot", start_hash="camp", end_hash="camp", resolved=True)
        self.mp.lair_camp = True
        try:
            session.state.on_exp.append(self._on_exp)
        except Exception:
            pass

    # ------------------------------------------------------------ the marked lairs
    def rooms(self) -> list:
        out = []
        for t in getattr(self.s.settings, "lair_camp_rooms", None) or []:
            k = room_key(t)
            if k and k not in out:
                out.append(k)
        return out

    def add(self, room) -> str:
        room = tuple(room)
        r = self.s.world.room(room)
        if not r:
            return f"{room[0]}/{room[1]} isn't on this board's map"
        if room in self.rooms():
            return f"{room[0]}/{room[1]} {r.name} is already in Camp lairs"
        lst = list(getattr(self.s.settings, "lair_camp_rooms", None) or []) + [f"{room[0]}/{room[1]}"]
        self.s.settings.lair_camp_rooms = lst
        self._save()
        note = "" if r.lair else " (MME doesn't list it as a lair — it'll be timed as one anyway)"
        return f"added {room[0]}/{room[1]} {r.name} to Camp lairs{note}"

    def remove(self, room) -> str:
        room = tuple(room)
        lst = [t for t in (getattr(self.s.settings, "lair_camp_rooms", None) or []) if room_key(t) != room]
        self.s.settings.lair_camp_rooms = lst
        self._save()
        self.anchors.pop(room, None)
        if self.target == room and self.on:
            self.state, self.target = "choose", None
        return f"took {room[0]}/{room[1]} out of Camp lairs"

    def _save(self):
        try:
            self.s.settings.save()
        except Exception:
            pass

    # ------------------------------------------------------------ respawn clocks
    def respawn(self, room):
        """(T seconds, where it came from: 'learned' / 'mme' / 'default')."""
        try:
            est = self.s.lairclock.estimate(room)
        except Exception:
            est = None
        if est:
            return float(est), "learned"
        r = self.s.world.room(room)
        t = respawn_secs(getattr(r, "delay", 0) if r else 0, realm_of(self.s))
        if t:
            return t, "mme"
        return float(DEFAULT_REFILL), "default"

    def ready_at(self, room) -> float:
        """When the lair is back (0 = ready now: nothing seen since Start)."""
        a = self.anchors.get(tuple(room)) or {}
        t, how = self.respawn(room)
        if how == "learned" or realm_of(self.s) == "stock":
            # Stock times the room from its last kill (an entry is the fallback: walked in, nothing to kill); the
            # learned figure is measured from the room going empty, which is the last kill too. Timing Stock from
            # entry brought lairs back early after long fights (MudPlay)
            start = a.get("kill") or a.get("entry")
        else:
            start = a.get("entry") or a.get("kill")
        return (start + t) if start else 0.0

    def _on_exp(self, n):
        if not self.on or not n or n <= 0:
            return
        room = self.s.state.room
        if room and room in self.rooms():
            self.anchors.setdefault(room, {})["kill"] = time.time()
            if self._engage is not None and self.target == room:
                self._engage["last_kill"] = time.time()

    # ------------------------------------------------------------ choosing
    def _secs_per_step(self) -> float:
        try:
            return float(self.s.loopbuilder._pace()[0]) or 1.6
        except Exception:
            return 1.6

    def distances(self, here) -> dict:
        """Steps from here to everywhere near, the way the walker may go (kept 5 s per room: cheap, but not free)."""
        cached_for, at, dist = self._dist
        now = time.time()
        if cached_for == here and now - at < 5:
            return dist
        b, w = self.s.bot, self.s.world
        try:
            dist = bfs(w, here, MAX_HOPS, level=b.route_level(), have=b.held_items() or set(), avoid=b.avoid_set())
        except Exception:
            dist = bfs(w, here, MAX_HOPS)
        self._dist = (here, now, dist)
        return dist

    def wait_room_for(self, lair, dist):
        """The neighbour on the shortest way in that isn't itself a marked lair (or avoided): where we wait."""
        w = self.s.world
        r = w.room(lair)
        if not r:
            return None
        marked = set(self.rooms())
        try:
            avoid = self.s.bot.avoid_set()
        except Exception:
            avoid = frozenset()
        best = None
        for ex in r.exits.values():
            n = ex.to
            if not n or n in marked or n not in dist or n in (avoid or ()):
                continue
            nr = w.rooms.get(n)
            if not nr or not any(e.to == lair for e in nr.exits.values()):
                continue                         # a one-way exit out: no stepping back in from there
            if best is None or dist[n] < dist[best]:
                best = n
        return best

    def candidates(self, now=None) -> list:
        """[{room, wait, hops, arrival, ready, slack}] for every lair we could go to now."""
        now = now or time.time()
        here = self.s.state.room
        if not here:
            return []
        dist = self.distances(here)
        sps = self._secs_per_step()
        out = []
        for room in self.rooms():
            if room in self.dropped:
                continue
            bo = self.backoff.get(room)
            if bo and now < bo[0]:
                continue
            nr = self.no_route.get(room)
            if nr and now < nr:
                continue
            if room not in dist:
                self.no_route[room] = now + NO_ROUTE_SECS
                self._say(("noroute", room), f"Camping: no way to {self._name(room)} from here — asking again in "
                                             f"{NO_ROUTE_SECS:.0f} s")
                continue
            wait = self.wait_room_for(room, dist)
            hops = dist[wait] if wait else max(0, dist[room] - 1)
            if wait is None and here not in self.rooms():
                wait = here                      # nowhere better beside it: wait where we stand
            arrival = now + hops * sps + sps     # the walk to the wait room, then the one step in
            ready = self.ready_at(room)
            # (ready since Start / long ago counts as ready now: lateness is measured from now, not from 1970)
            out.append({"room": room, "wait": wait, "hops": hops, "dist": dist[room], "arrival": arrival,
                        "ready": ready, "slack": arrival - max(ready, now)})
        return out

    def pick(self, now=None):
        """The next lair, by the rule in Settings (closest ready lair, else soonest back; or least late)."""
        c = self.candidates(now)
        if not c:
            return None
        if getattr(self.s.settings, "lair_camp_throughput", False):
            return min(c, key=lambda x: (max(0.0, x["slack"]), max(0.0, -x["slack"]), x["dist"]))
        ready = [x for x in c if x["slack"] >= 0]
        if ready:
            return min(ready, key=lambda x: (x["dist"], x["ready"]))
        return min(c, key=lambda x: (max(x["arrival"], x["ready"]), x["dist"]))

    # ------------------------------------------------------------ start / stop
    def start(self, by="you") -> str:
        s, b = self.s, self.s.bot
        if self.on:
            return "already camping lairs"
        rooms = self.rooms()
        if not rooms:
            return "no lairs marked — add some first (Paths → Camp lairs, or Game Data → Rooms → Add to Camp lairs)"
        if getattr(s.settings, "hands_off", False):
            return "Hands off is on — switch it off first"
        lead = None
        try:
            lead = b.x.leader()
        except Exception:
            pass
        if lead or getattr(b.x, "_following", None):
            # a follower never sets off on its own: the leader camps and the party follows it (0.8.201, Dan)
            return f"following {lead or b.x._following} — the leader camps, not a follower"
        if b.dead_blocked("camping lairs"):
            return "died — nothing walks until you start it yourself"
        if b.walking:
            b.stop("Camping lairs takes over")
        for r in rooms:
            self.anchors.pop(r, None)            # a run's Start: every marked lair counts as ready
        self.backoff, self.no_route, self.dropped = {}, {}, {}
        self.on, self.state, self.target, self._disp, self._engage = True, "choose", None, None, None
        self._started_at = time.time()
        self._conn = s._connected_at
        self._room_prev = s.state.room
        self._resume_at = 0.0
        self.status = "Camping lairs"
        s.log(f"Camping lairs: started by {by} — {len(rooms)} lair{'s' if len(rooms) != 1 else ''} "
              f"({realm_of(s).capitalize()} timing)")
        return f"camping {len(rooms)} lair{'s' if len(rooms) != 1 else ''}"

    def stop(self, why="Stopped") -> str:
        if not self.on:
            return "not camping lairs"
        self.on = False
        disp, self._disp = self._disp, None
        self.state, self.target, self._engage = "off", None, None
        self.status = "Not camping"
        self.s.log(f"Camping lairs: stopped — {why}")
        b = self.s.bot
        if why.startswith("Stopped by") and disp and b.walking and b.path and b.path.title.startswith("Go to ") \
                and getattr(b, "_goto_target", None) == tuple(disp["dest"]):
            b.stop(why)                          # our own walk ends with it (the hook: camping is already off)
        return "stopped camping lairs"

    def note_stop(self, why: str):
        """Automation.stop: your Stop (or a hang-up, Hands off, a death, Disconnect) ends camping."""
        if self.on and why.startswith(PAUSE_WORDS):
            self.stop(why)

    def trip_over(self):
        """A stash / train / bank trip that left from camping is done: back to camping (Automation.start_path)."""
        if not self.on:
            return
        self.s.log("Camping lairs: trip done — back to camping")
        self.state, self._disp = "choose", None
        self._resume_at = time.time() + RESUME_SETTLE

    # ------------------------------------------------------------ helpers
    def _name(self, room):
        r = self.s.world.room(room) if room else None
        return f"{room[0]}/{room[1]} {r.name}" if r else (f"{room[0]}/{room[1]}" if room else "?")

    def _say(self, key, msg, every=30):
        now = time.time()
        if now - self._said.get(key, 0) >= every:
            self._said[key] = now
            self.s.log(msg)

    def _busy(self):
        """Something else is running a trip (bank, sell, stash, train, scrolls, an errand, a boss hunt, a comeback):
        camping pauses and keeps its clocks."""
        s, b = self.s, self.s.bot
        if getattr(s.trips, "trip", None):
            return "a bank / shop trip"
        if getattr(s.training, "busy", False):
            return "training"
        if getattr(b.errands, "active", None) or getattr(b.errands, "asking", None):
            return "an errand"
        if getattr(s.scrolls, "trip", None):
            return "the scroll errand"
        if getattr(s.bosshunt, "active", None):
            return "a boss hunt"
        if getattr(getattr(s, "comeback", None), "fetch", None):
            return "fetching a party member"
        return None

    def _our_walk(self) -> bool:
        b, d = self.s.bot, self._disp
        return bool(d and b.walking and b.path and b.path.title.startswith("Go to ")
                    and getattr(b, "_goto_target", None) == tuple(d["dest"]))

    def _fighting(self) -> bool:
        st = self.s.state
        if st.in_combat:
            return True
        try:
            return bool(self.s.bot.attackable())
        except Exception:
            return bool(st.view and st.view.monsters)

    def dispatch(self, dest, purpose):
        """Ask the walker for one walk to `dest` — once (re-asking every tick superseded its own walk and spun about
        once a second without ever going in: MudPlay). Worked out off the window's thread."""
        b = self.s.bot
        d = {"dest": tuple(dest), "purpose": purpose, "at": time.time(), "ok": None}
        self._disp = d
        if self.s.state.room == tuple(dest):
            d["ok"] = True
            return

        def done(res, err, d=d):
            if self._disp is not d:
                return                           # a newer walk of ours replaced it: not a failure
            d["ok"] = bool(res) and not err
            d["at"] = time.time()
            if not d["ok"]:
                self._failed(self.target or d["dest"], getattr(b, "no_route_msg", "") or (str(err) if err else ""),
                             no_route=True)
        from . import bgplan
        try:
            bgplan.plan(self.s, lambda _a: b.goto(tuple(dest)), done, after=getattr(self.s, "tk_after", None))
        except Exception as ex:
            done(False, ex)

    def _failed(self, lair, why="", no_route=False):
        """Getting into `lair` didn't work: behind a door we can't open → out for this run; no way there → asked
        again in 30 s; anything else → that lair waits 2 s, then 4, 8 … up to 60, and another one is picked."""
        now = time.time()
        if lair is None:
            return
        lair = tuple(lair)
        status = str(getattr(self.s.bot, "status", "") or "")
        if DOOR_RE.search(why or "") or status.startswith("Stopped: the door"):
            self.dropped[lair] = why or status
            self.s.log(f"Camping lairs: {self._name(lair)} is behind a door I can't open — dropped from this run")
        elif no_route:
            self.no_route[lair] = now + NO_ROUTE_SECS
            self._say(("noroute", lair), f"Camping lairs: no way to {self._name(lair)} — asking again in "
                                         f"{NO_ROUTE_SECS:.0f} s")
        else:
            prev = self.backoff.get(lair, (0, 0))[1]
            secs = min(BACKOFF_MAX, prev * 2 if prev else BACKOFF_FIRST)
            self.backoff[lair] = (now + secs, secs)
            self.s.log(f"Camping lairs: couldn't get into {self._name(lair)} — trying it again in {secs:.0f} s")
        self.state, self.target, self._disp, self._engage = "choose", None, None, None

    def _walk_stopped(self) -> bool:
        """Our walk isn't walking any more and we're not where it was going."""
        b, d, st = self.s.bot, self._disp, self.s.state
        if not d or d["ok"] is None or getattr(b, "_planning", False):
            return False
        if st.room == d["dest"] or self._our_walk() or (b.parked() if hasattr(b, "parked") else False):
            return False
        return time.time() - d["at"] > WALK_CHECK and not b.walking

    # ------------------------------------------------------------ every poll
    def tick(self):
        if not self.on:
            return
        s, b, st, cfg = self.s, self.s.bot, self.s.state, self.s.settings
        if not s.telnet.connected or not s._entered:
            return                               # (a dropped line: picked up again once back in, clocks kept)
        now = time.time()
        if self._conn != s._connected_at:
            self._conn = s._connected_at
            if not getattr(cfg, "resume_after_reconnect", True):
                self.stop("back in after a dropped line, and 'carry on after reconnecting' is off")
                return
            # the line dropped and we're back in: carry on from the room this connection shows, clocks kept. The
            # reconnect's own Rego would walk on to whichever room our last walk was going to — camping picks again
            s._drop_resume, s._resume_at = None, 0
            self.state, self.target, self._disp, self._engage = "choose", None, None, None
            self._resume_at = now + RESUME_SETTLE
            s.log("Camping lairs: back in after a dropped line — carrying on from here, lair clocks kept")
        if st.dead or getattr(b, "dead_hold", 0) > self._started_at:
            self.stop("character died")
            return
        if getattr(cfg, "hands_off", False):
            self.stop("Hands off")
            return
        try:
            lead = b.x.leader()
        except Exception:
            lead = None
        if lead:
            self.stop(f"following {lead} now — the leader camps")
            return
        here = st.room
        if here != self._room_prev:
            self._room_prev = here
            if here and here in self.rooms():
                self.anchors.setdefault(here, {})["entry"] = now
        busy = self._busy()
        if busy:
            if self.state != "paused":
                self.state, self._disp = "paused", None
                s.log(f"Camping lairs: paused for {busy}")
            self.status = f"Camping lairs — paused for {busy}"
            return
        if self.state == "paused":
            if b.walking or b.parked():
                self.status = "Camping lairs — waiting for the trip's walk to finish"
                return
            self.state = "choose"
            self._resume_at = max(self._resume_at, now + RESUME_SETTLE)
            s.log("Camping lairs: carrying on")
        if b.walking and b.loop:
            self.stop("a loop started")
            return
        if b.walking and not self._our_walk() and self.state != "engage":
            self.status = "Camping lairs — waiting for another walk to finish"
            return                               # your Go to (or one that isn't ours): it goes first
        if now < self._resume_at or getattr(b, "_planning", False):
            return
        if self.state == "engage":
            return self._engage_tick(now)
        if self._fighting() or st.resting:
            return                               # the fight / rest comes first; we go when it's over
        if b.walk_holds():
            self.status = "Camping lairs — the walk is held: " + "; ".join(b.walk_holds().values())
            return
        if self.state == "choose":
            return self._choose(now)
        if self.state == "approach":
            return self._approach_tick(now)
        if self.state == "wait":
            return self._wait_tick(now)
        if self.state == "enter":
            return self._enter_tick(now)

    def _choose(self, now):
        st = self.s.state
        if now < self._next_look:
            return
        self._next_look = now + REPICK_SECS
        c = self.pick(now)
        if not c:
            soon = [v[0] for v in self.backoff.values() if v[0] > now] + [v for v in self.no_route.values() if v > now]
            self.status = ("Camping lairs — none reachable right now" +
                           (f", trying again in {min(soon) - now:.0f} s" if soon else ""))
            if not soon and len(self.dropped) >= len(self.rooms()):
                self.stop("every marked lair is behind a door I can't open")
            return
        self.target, self.wait_room = c["room"], c["wait"]
        self.entry_at = 0.0
        if st.room == c["room"]:
            if c["ready"] <= now:
                self._begin_engage(now)
            elif c["wait"] and c["wait"] != st.room:
                # the lair we're standing in is the best pick but isn't back yet: being early does nothing — step
                # out to its wait room and come back in on time
                self.state = "approach"
                self.dispatch(c["wait"], "approach")
            else:
                self._latch(now)
            return
        if c["slack"] >= 0 or not c["wait"] or c["wait"] == st.room:
            if c["slack"] >= 0 or c["ready"] <= now:
                self.state = "enter"
                self.dispatch(c["room"], "enter")
            else:
                self._latch(now)                 # already standing in its wait room
            return
        self.state = "approach"
        self.status = f"Camping lairs — walking to {self._name(c['wait'])} for {self._name(c['room'])}"
        self.dispatch(c["wait"], "approach")

    def _latch(self, now):
        """In the wait room: the moment to step in, worked out once."""
        self.state = "wait"
        self.entry_at = max(now, self.ready_at(self.target))
        left = self.entry_at - now
        self.s.log(f"Camping lairs: waiting in {self._name(self.s.state.room)} — {self._name(self.target)} is back in "
                   f"{left:.0f} s")

    def _approach_tick(self, now):
        st = self.s.state
        if self.wait_room and st.room == self.wait_room and not self.s.bot.walking:
            self._latch(now)
            return
        if self._walk_stopped():
            self._failed(self.target, getattr(self.s.bot, "status", ""))
            return
        if now >= self._next_look and self._disp and self._disp["ok"] and now - self._disp["at"] > WALK_CHECK:
            # on the way, another lair can become the better pick (a quicker one coming due): change course — once,
            # as our own walk replacing our own walk, never re-asked every tick
            self._next_look = now + REPICK_SECS
            c = self.pick(now)
            if c and c["room"] != self.target:
                self.s.log(f"Camping lairs: {self._name(c['room'])} is the better pick now — going there instead")
                self.target, self.wait_room = c["room"], c["wait"]
                if c["slack"] >= 0 or not c["wait"]:
                    self.state = "enter"
                    self.dispatch(c["room"], "enter")
                else:
                    self.dispatch(c["wait"], "approach")

    def _wait_tick(self, now):
        st = self.s.state
        if self.wait_room and st.room != self.wait_room and not self.s.bot.walking:
            self.state = "choose"                # pushed away (fled, summoned): pick again from here
            return
        left = self.entry_at - now
        if left > 0:
            self.status = f"Camping lairs — waiting for {self._name(self.target)} ({left:.0f} s)"
            self.s.bot.status = self.status      # (the status bar says why we're standing here, not 'Arrived')
            return
        self.state = "enter"
        self.status = f"Camping lairs — into {self._name(self.target)}"
        self.dispatch(self.target, "enter")

    def _enter_tick(self, now):
        st = self.s.state
        if st.room == self.target:
            self._begin_engage(now)
            return
        if self._walk_stopped():
            self._failed(self.target, getattr(self.s.bot, "status", ""))

    def _begin_engage(self, now):
        self.state = "engage"
        self._engage = {"t0": now, "fought": False, "last_fight": 0.0, "last_kill": 0.0, "capped": False}
        self.backoff.pop(self.target, None)
        self.anchors.setdefault(self.target, {})["entry"] = now
        self.status = f"Camping lairs — in {self._name(self.target)}"

    def _engage_tick(self, now):
        st, e = self.s.state, self._engage
        if e is None:
            self.state = "choose"
            return
        if st.room != self.target:
            if not self.s.bot.walking:
                self.state, self._engage = "choose", None     # out of it (fled, carried off): pick again
            return
        if self._fighting():
            e["fought"], e["last_fight"] = True, now
            if now - e["t0"] > FIGHT_CAP and not e["capped"]:
                e["capped"] = True
                self.s.log(f"Camping lairs: still fighting in {self._name(self.target)} after {FIGHT_CAP:.0f} s — "
                           "leaving as soon as it's safe to")
            if st.in_combat or now - e["t0"] <= FIGHT_CAP:
                return                           # never walk out in the middle of a fight
            # past the cap and nothing is fighting us: monsters we won't fight are holding us here — go
        elif not e["fought"]:
            if now - e["t0"] < GRACE:
                return
            self.s.log(f"Camping lairs: {self._name(self.target)} is empty — moving on")
        elif now - e["last_fight"] < LOOT_SECS or (st.pending and now - e["last_fight"] < LOOT_SECS * 3):
            return                               # the loot first
        if st.resting:
            return
        self._leave(now)

    def _leave(self, now):
        e, lair = self._engage or {}, self.target
        if e.get("last_kill"):
            self.anchors.setdefault(lair, {})["kill"] = e["last_kill"]
        self._engage, self.target, self._disp = None, None, None
        self.state = "choose"
        self._next_look = 0.0
        if self._lap_end():
            self.state = "paused"

    def _lap_end(self) -> bool:
        """After a lair, the checks a loop makes at the end of a lap: stash, train, bank / sell / buy, lights,
        scrolls. One that sets off pauses camping; its way back (start_path on our marker path) resumes it."""
        s, b = self.s, self.s.bot
        for fn in (b.x.stash_at_lap_end, s.training.lap_end, s.trips.lap_end, b.lights.lap_end, s.scrolls.lap_end):
            try:
                if fn(self.mp):
                    s.log("Camping lairs: off on a trip first — back to camping after")
                    return True
            except Exception as ex:
                s.log(f"Camping lairs: end-of-lap check failed ({ex})")
        return False

    # ------------------------------------------------------------ what to show
    def rows(self, now=None) -> list:
        """[(room, name, 'T s (where from)', 'ready' / 'in N s' / why it's out)] for the list and @camp list."""
        now = now or time.time()
        out = []
        for room in self.rooms():
            r = self.s.world.room(room)
            t, how = self.respawn(room)
            if room in self.dropped:
                nxt = "dropped (door)"
            elif room in self.backoff and self.backoff[room][0] > now:
                nxt = f"retry in {self.backoff[room][0] - now:.0f} s"
            elif room in self.no_route and self.no_route[room] > now:
                nxt = "no route"
            else:
                ra = self.ready_at(room)
                nxt = "ready" if ra <= now else f"in {ra - now:.0f} s"
            if self.on and room == self.target:
                nxt += " ◀"
            out.append((room, r.name if r else "?", f"{t:.0f} s ({how})", nxt))
        return out

    def list_lines(self) -> list:
        rows = self.rows()
        if not rows:
            return ["no lairs marked (Paths → Camp lairs)"]
        head = self.status if self.on else "not camping"
        return [head] + [f"{r[0][0]}/{r[0][1]} {r[1]}: {r[3]}" for r in rows[:8]]
