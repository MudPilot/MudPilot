"""Events: do something on a timer, when text appears, or when a boss is due.

Event (a dict in settings.events):
    name, enabled
    when:  "timer"   every = minutes
           "text"    match = text to look for (case-insensitive; /regex/ for a regex)
           "boss"    boss  = boss name — fires when its respawn timer says it should be up
    do:    "hunt"    boss  = boss name — go to its spawn room(s), kill it, go back to what you were doing
           "send"    commands = one per line ("wait 3" pauses 3 s)
           "goto"    room = "map/room" — walk there, then resume
           "path"    path = path or loop name — start it
    min_hp       only start when HP % is at least this (rests first)
    not_fighting only start when not in combat (default on)
    cooldown     minutes before a text/boss event can fire again (default 5)
"""
from __future__ import annotations

import re
import time

KINDS_WHEN = {"timer": "Every N minutes", "text": "When text appears", "boss": "When a boss is due"}
KINDS_DO = {"hunt": "Hunt a boss, then resume", "send": "Send commands", "goto": "Go to a room, then resume",
            "path": "Start a path / loop"}


def describe(ev) -> tuple[str, str]:
    w, d = ev.get("when"), ev.get("do")
    if w == "timer":
        m = float(ev.get("every") or 0)
        when = f"every {m:g} min" if m < 60 else f"every {m / 60:g} h"
    elif w == "text":
        when = f"text: {ev.get('match', '')}"
    else:
        when = f"{ev.get('boss') or 'boss'} is due"
    if d == "hunt":
        do = f"hunt {ev.get('boss', '')}"
    elif d == "send":
        do = "send: " + " / ".join((ev.get("commands") or "").splitlines())[:40]
    elif d == "goto":
        do = f"go to {ev.get('room', '')}"
    else:
        do = f"start {ev.get('path', '')}"
    return when, do


class Hunt:
    """Walk to a boss, kill it, walk back and resume the loop/path."""
    TIMEOUT = 25 * 60

    def __init__(self, mgr, ev, mon):
        self.m, self.ev, self.mon = mgr, ev, mon
        s = mgr.s
        bot = s.bot
        self.saved = (bot.path, bot.loop, bot.idx) if bot.walking and bot.path and \
            not bot.path.title.startswith("Go to ") else (bot.last_path, bot.last_loop, None) if bot.last_path else None
        self.home = s.state.room
        rooms = [tuple(r) for r in mon.get("spawn_rooms") or []]
        here = s.state.room
        if here and len(rooms) > 1:
            dist = {}
            for r in rooms:
                rt = s.world.route(here, r, level=s.state.level or None, avoid=s.bot.avoid_set())
                if rt is not None:
                    dist[r] = len(rt)
            rooms = sorted(dist, key=dist.get) + [r for r in rooms if r not in dist]
        self.rooms = rooms
        self.state = "start"
        self.t0 = time.time()
        self.t_state = time.time()
        self.found = False
        self.result = ""

    def _set(self, st):
        self.state, self.t_state = st, time.time()

    def boss_here(self):
        v = self.m.s.state.view
        nm = self.mon["name"].lower()
        return bool(v) and any((rec and rec["name"].lower() == nm) or nm in sh.lower() for sh, rec in v.monsters)

    def tick(self) -> bool:
        """Returns False when the hunt is over."""
        s, now = self.m.s, time.time()
        bot, st = s.bot, s.state
        if now - self.t0 > self.TIMEOUT:
            self.result = "gave up (took too long)"
            return self._go_home()
        if self.state == "start":
            if not self.rooms:
                self.result = "no spawn room in MME data"
                return False
            bot.stop(f"Event: hunting {self.mon['name']}")
            bot.hunt_target = self.mon
            return self._next_room()
        if self.state == "going":
            if self.boss_here():
                self._set("fighting")
                return True
            if not bot.walking and st.room == self.target:
                self._set("looking")
                s.send("")
            elif not bot.walking and now - self.t_state > 8 and not st.in_combat:
                if st.room and st.room != self.target and not bot.goto(self.target):
                    return self._next_room()
            return True
        if self.state == "looking":
            if self.boss_here():
                self._set("fighting")
            elif now - self.t_state > 4:
                return self._next_room()
            return True
        if self.state == "fighting":
            if self.boss_here() or st.in_combat:
                self.found = True
                self.t_state = now
                return True
            if now - self.t_state > 3:
                self.result = f"{self.mon['name']} is down"
                return self._go_home()
            return True
        if self.state == "returning":
            if not bot.walking or (bot.path and not bot.path.title.startswith("Go to ")):
                return False
            if now - self.t_state > 15 * 60:
                return False
            return True
        return False

    def _next_room(self):
        s = self.m.s
        while self.rooms:
            self.target = self.rooms.pop(0)
            if s.state.room == self.target:
                self._set("looking")
                s.send("")
                return True
            if s.bot.goto(self.target):
                self._set("going")
                return True
        if not self.found:
            self.result = f"{self.mon['name']} isn't up"
            self.m.s.bosses.rec(self.mon)
        return self._go_home()

    def _go_home(self):
        s = self.m.s
        s.bot.hunt_target = None
        if not self.saved:
            s.bot.stop(f"Event done: {self.result}")
            return False
        mp, loop, idx = self.saved
        back = self.home
        if idx is not None and mp.steps and mp.steps[min(idx, len(mp.steps) - 1)].room:
            back = mp.steps[min(idx, len(mp.steps) - 1)].room
        s.log(f"Event: {self.result} — heading back to '{mp.title}'")
        if back and s.state.room != back and s.bot.goto(back, then=mp):
            s.bot.after_goto = mp
            self._resume_loop = loop
            self._set("returning")
            return True
        s.bot.start_path(mp, loop=loop)
        return False


class EventManager:
    def __init__(self, session):
        self.s = session
        self.hunt: Hunt | None = None
        self._queue: list = []          # (event, reason)
        self._cmds: list = []           # pending (send_at, command)
        self.on_change = lambda: None

    @property
    def events(self):
        return self.s.settings.events or []

    def last(self, ev) -> float:
        return float(ev.get("last_run") or 0)

    def next_due(self, ev):
        if ev.get("when") == "timer":
            every = float(ev.get("every") or 0) * 60
            if every <= 0:
                return None
            return (self.last(ev) or ev.setdefault("armed_at", time.time())) + every
        if ev.get("when") == "boss":
            mon = self.s.world.boss_named(ev.get("boss"))
            if not mon:
                return None
            _txt, left = self.s.bosses.status(mon["num"])
            return time.time() + left if left is not None else None
        return None

    def status(self, ev) -> str:
        if not ev.get("enabled", True):
            return "off"
        if self.hunt and self.hunt.ev is ev:
            return f"running ({self.hunt.state})"
        if any(q[0] is ev for q in self._queue):
            return "waiting to start"
        nd = self.next_due(ev)
        if nd is None:
            if ev.get("when") == "text":
                return "watching"
            if ev.get("when") == "boss":
                return "no timer yet (needs a kill)"
            return "—"
        left = nd - time.time()
        if left <= 0:
            return "due"
        h, m = int(left // 3600), int(left % 3600 // 60)
        return f"in {h}h {m:02d}m" if h else f"in {m}m {int(left % 60):02d}s"

    # ------------------------------------------------------------ triggers
    def feed_line(self, text: str):
        for ev in self.events:
            if not ev.get("enabled", True) or ev.get("when") != "text":
                continue
            pat = ev.get("match") or ""
            if not pat:
                continue
            try:
                hit = re.search(pat[1:-1], text, re.I) if len(pat) > 2 and pat.startswith("/") and pat.endswith("/") \
                    else pat.lower() in text.lower()
            except re.error:
                hit = False
            if hit and time.time() - self.last(ev) > float(ev.get("cooldown", 5) or 0) * 60:
                self.fire(ev, "text seen")

    def fire(self, ev, why="manual"):
        if any(q[0] is ev for q in self._queue) or (self.hunt and self.hunt.ev is ev):
            return
        ev["last_run"] = now = time.time()
        self._queue.append((ev, why))
        if why == "timer":
            # 0.8.224 (Dan, log noise): PVEREV's 'par' every 6 s wrote 12,432 "fired" lines — a timer event says so
            # the first time, then once every 30 minutes with a count
            q = self.__dict__.setdefault("_timer_said", {})
            k = id(ev)
            last, n = q.get(k, (0, 0))
            if now - last < 1800:
                q[k] = (last, n + 1)
            else:
                q[k] = (now, 0)
                self.s.log(f"Event '{ev.get('name') or describe(ev)[1]}' fired (timer)"
                           + (f" — {n + 1} times in the last {(now - last) / 60:.0f} min" if last else ""))
        else:
            self.s.log(f"Event '{ev.get('name') or describe(ev)[1]}' fired ({why})")
        self.on_change()

    def tick(self):
        now = time.time()
        while self._cmds and self._cmds[0][0] <= now:
            _t, c = self._cmds.pop(0)
            self.s.send(c, from_bot=True)
        for ev in self.events:
            if not ev.get("enabled", True) or ev.get("when") not in ("timer", "boss"):
                continue
            nd = self.next_due(ev)
            if nd is not None and nd <= now:
                if ev.get("when") == "boss" and now - self.last(ev) < float(ev.get("cooldown", 5) or 0) * 60:
                    continue
                self.fire(ev, "timer" if ev.get("when") == "timer" else "boss due")
        if self.hunt:
            if not self.hunt.tick():
                self.s.log(f"Event finished: {self.hunt.result or 'done'}")
                self.hunt = None
                self.s.bot.hunt_target = None
                self.on_change()
            return
        if not self._queue or not self.s.telnet.connected:
            return
        ev, why = self._queue[0]
        st = self.s.state
        if ev.get("not_fighting", True) and st.in_combat:
            return
        need = int(ev.get("min_hp") or 0)
        if need and st.max_hp and st.hp_pct() < need:
            self.s.bot.status = f"Event '{ev.get('name')}': resting to {need}% first"
            if not st.resting and self.s.bot.ready("event_rest", 5):
                self.s.send(self.s.settings.rest_cmd, from_bot=True)
            return
        self._queue.pop(0)
        self.run(ev)
        self.on_change()

    def run(self, ev):
        d = ev.get("do")
        s = self.s
        if d == "send":
            t = time.time()
            for line in (ev.get("commands") or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                m = re.match(r"^wait\s+(\d+(?:\.\d+)?)$", line, re.I)
                if m:
                    t += float(m.group(1))
                    continue
                self._cmds.append((t, line))
                t += 0.4
        elif d == "hunt":
            mon = s.world.boss_named(ev.get("boss"))
            if not mon:
                s.log(f"Event: no monster '{ev.get('boss')}' in this board's MME data")
                return
            self.hunt = Hunt(self, ev, mon)
            self.hunt.tick()
        elif d == "goto":
            m = re.match(r"^\s*(\d+)\s*/\s*(\d+)", ev.get("room") or "")
            if not m:
                s.log("Event: room must be map/room, e.g. 3/606")
                return
            then = s.bot.path if s.bot.walking and s.bot.path and not s.bot.path.title.startswith("Go to ") else None
            s.bot.goto((int(m.group(1)), int(m.group(2))), then=then)
        elif d == "path":
            name = (ev.get("path") or "").lower()
            mp = next((p for p in s.paths if p.title.lower() == name), None) or \
                next((p for p in s.paths if name and name in p.title.lower()), None)
            if not mp:
                s.log(f"Event: no path named '{ev.get('path')}'")
                return
            if mp.resolved and mp.steps[0].room and s.state.room and \
                    not any(x.room == s.state.room for x in mp.steps):
                s.bot.goto(mp.steps[0].room, then=mp)
            else:
                s.bot.start_path(mp)
