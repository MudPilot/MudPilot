"""Someone else scripting your loop (Dan, 2026-11-01: a player moved into the Glades loop).

Sharing a room with them is fine — your area spell takes most of a room's exp — what costs you is trailing them:
walking into lairs they cleared a moment ago. So MudPilot notes where other players are seen (in the room, walking
in, leaving), and when a lair you reach should be full but is empty, and one of them was in it a moment ago, that's
them clearing just ahead of you. Twice inside a few minutes, while you lead a loop: stop and rest until they come
round to you (or a few minutes pass), then carry on ahead of them — you clear the lairs, they get what's left.

Trail them (Dan, 2026-11-07, off unless ticked): someone scripting on top of us in PVE cuts our exp badly. Once one
of them is caught clearing ahead of us, the leader leaves the loop and goes where they go — in the room with them,
your attack goes in first and the kills are yours — but only while they stay in the loop's rooms. Never out of
the area: when they leave it, or we lose them, the loop just carries on, and the trail picks up again the next time
we're in a room with them (for the hour after they were caught). The idea is that their exp drops so far they go
and script somewhere else.
"""
from __future__ import annotations

import re
import time

SEEN_FOR = 180          # how long a sighting in a room counts
JUST_THERE = 120        # an empty lair they were in this recently: they cleared it
HITS_FOR = 300          # two of those in this long → it's costing us
CATCH_UP = 60           # cleared it less than this ago: they're just ahead — catch up instead of waiting a lap
TRAIL_WAIT = 15         # trailing, in the room with them and nothing to fight: this long to see where they go
TRAIL_LATE = 30         # they left this long ago and we're still here (a fight): too late to follow
MARKED_FOR = 3600       # caught scripting on top of us: trail them again if they show up within this long
DIR_OF = {"north": "N", "south": "S", "east": "E", "west": "W", "northeast": "NE", "northwest": "NW",
          "southeast": "SE", "southwest": "SW", "up": "U", "down": "D", "upwards": "U", "downwards": "D"}

LEFT_RE = re.compile(r"^([A-Z][a-z]+) just left (?:to the )?(\w+)")
WALKS_IN_RE = re.compile(r"^([A-Z][a-z]+) (?:walks|runs|sneaks|wanders|arrives|enters|stumbles|limps|crawls|steps)\b.*"
                         r"\binto the room\b")


class Scripters:
    def __init__(self, session):
        self.s = session
        self.seen: dict = {}            # name -> {room: last time seen there}
        self.hits: dict = {}            # name -> [times a lair they'd just been in was empty for us]
        self.hold = None                # {"name", "t", "until"} while waiting for them to come round
        self.chase = None               # {"name", "t", "until"} while catching up with them (no pacing stops)
        self._waited: dict = {}         # name -> when we last waited for them
        self.trail = None               # {"name", "t", "seen", "dir", "from", "left_at"} while trailing them
        self.marked: dict = {}          # name -> when they were caught clearing ahead of us (trail them again)

    # ------------------------------------------------------------ who's where
    def _others(self, names):
        st, cfg = self.s.state, self.s.settings
        me = (cfg.my_name or "").lower()
        party = {n.lower() for n in (st.party or {})}
        x = getattr(self.s.bot, "x", None)
        out = []
        for w in names or []:
            nm = w.split()[0].strip(".,") if w.split() else ""
            if not nm or nm.lower() == me or nm.lower() in party or not nm[:1].isupper():
                continue
            # a friend is never 'another scripter' — party now or lately, a MudPilot partner, friends / remote list
            # (0.8.135, Miserable: "Letting Revolution come round" — the party list was empty for a moment after a
            # restart)
            if x is not None and hasattr(x, "is_friend") and x.is_friend(nm):
                continue
            out.append(nm)
        return out

    def _note(self, name, room, now):
        if room:
            self.seen.setdefault(name, {})[room] = now
        if self.hold and self.hold["name"].lower() == name.lower() and room == self.s.state.room:
            self.hold["here"] = now
        if self.chase and self.chase["name"].lower() == name.lower() and room == self.s.state.room:
            self.s.log(f"Caught up with {name} — sharing their rooms")
            self.chase = None
        tr = self.trail
        if tr and tr["name"].lower() == name.lower() and room == self.s.state.room:
            tr["seen"] = now
        elif not tr and room == self.s.state.room and now - self.marked.get(name, 0) < MARKED_FOR:
            self._start_trail(name, now, f"{name} is back in our area")

    def on_room(self, state):
        if state.view and state.room:
            now = time.time()
            for nm in self._others(state.view.players):
                self._note(nm, state.room, now)

    def feed_line(self, text):
        t = (text or "").strip()
        m = LEFT_RE.match(t) or WALKS_IN_RE.match(t)
        if m and self._others([m.group(1)]):
            self._note(m.group(1), self.s.state.room, time.time())
        ml = LEFT_RE.match(t)
        tr = self.trail
        if ml and tr and tr["name"].lower() == ml.group(1).lower() and DIR_OF.get(ml.group(2).lower()):
            tr.update({"dir": DIR_OF[ml.group(2).lower()], "left_at": time.time(), "from": self.s.state.room})

    # ------------------------------------------------------------ is it costing us?
    def lair_empty(self, room, now=None):
        """We just walked into a lair and it's empty."""
        now = now or time.time()
        cfg, b = self.s.settings, self.s.bot
        trail = bool(getattr(cfg, "scripter_trail", False))
        if not (getattr(cfg, "scripter_wait", True) or trail) or self.hold or self.chase or self.trail:
            return
        for name, rooms in self.seen.items():
            t = rooms.get(room)
            if not t or now - t > JUST_THERE:
                continue
            hs = [h for h in self.hits.get(name, []) if now - h < HITS_FOR] + [now]
            self.hits[name] = hs
            ago = int(now - t)
            self.s.log(f"Lair {room[0]}/{room[1]} empty — {name} was in it {ago} s ago")
            if len(hs) >= 2 and b.walking and b.loop and b.x.leading() is not False:
                self._waited[name] = now
                self.hits[name] = []
                if trail:
                    self.marked[name] = now
                    if self._start_trail(name, now, f"{name} is clearing the lairs just ahead of us ({ago} s)"):
                        return
                if not getattr(cfg, "scripter_wait", True):
                    return
                # catch them up and share their rooms (your area spell takes most of each one) — never stop and let
                # them get ahead: on a small loop we're back on them in a lap or two, and paced like that they make
                # a quarter of their exp and move on (Dan, 2026-11-01: Evolution rested 3.5 min for Plusone, who
                # never came round — a 5.8-minute lap at 163k/hr)
                secs = int(getattr(cfg, "scripter_wait_max", 240) or 240)
                self.chase = {"name": name, "t": now, "until": now + secs}
                self.s.log(f"{name} is clearing the lairs just ahead of us ({ago} s) — no pacing stops till we catch "
                           "up and share their rooms")
            return

    # ------------------------------------------------------------ trailing them (inside our area only)
    def area(self) -> set:
        """The loop's rooms: as far as a trail ever goes."""
        p = self.s.bot.path
        return {r for st_ in (p.steps if p else []) for r in (st_.room, st_.dest) if r}

    def _can_trail(self) -> bool:
        b = self.s.bot
        return bool(getattr(self.s.settings, "scripter_trail", False) and b.walking and b.loop and b.path
                    and b.x.leading() is not False and not b.path.title.startswith("Go to "))

    def _start_trail(self, name, now, why) -> bool:
        if not self._can_trail() or self.s.state.room not in self.area():
            return False
        self.trail = {"name": name, "t": now, "seen": now, "dir": None, "from": None, "left_at": 0, "with": None}
        self.chase = self.hold = None
        self.s.bot.detour = None
        self.s.log(f"{why} — trailing {name} round our area to take the kills (never outside the loop's rooms)")
        return True

    def _end_trail(self, why):
        self.s.log(why)
        self.trail = None

    def trailing(self, mobs) -> bool:
        """Walk tick: True = the loop waits a moment for them. They left the room we're in, into one of the loop's
        rooms: after them (once the fight here's over — never leave a fight). In the room with them: a few seconds
        to see which way they go. Anything else — lost them, they left the area — the loop just carries on, and we
        pick them up again next time we're in a room together (Dan, 2026-11-07: it stood at 17/1631 'lost sight';
        'I don't care if it loses him twice a lap, it should keep looping and catch up with him')."""
        tr = self.trail
        if not tr:
            return False
        if not self._can_trail():
            self.trail = None
            return False
        b, st, w = self.s.bot, self.s.state, self.s.world
        now = time.time()
        name = tr["name"]
        here = st.room
        if tr["dir"] and here and tr["from"] == here:
            d = tr["dir"]
            r = w.room(here)
            ex = r.exits.get(d) if r else None
            if ex is None or ex.to not in self.area():
                tr["dir"] = None
                self.s.log(f"{name} left our area ({d}{f' to {ex.to[0]}/{ex.to[1]}' if ex is not None else ''}) — "
                           "not following them out; looping on")
                return False
            if st.in_combat or mobs:
                if now - tr["left_at"] < TRAIL_LATE:
                    b.status = f"Trailing {name} — this fight first, then after them ({d})"
                    return True
                tr["dir"] = None                          # too long: they're well gone — loop on
                return False
            tr["dir"], tr["seen"], tr["with"] = None, now, None
            b.status = f"Trailing {name} → {ex.to[0]}/{ex.to[1]}"
            b._send_exit(ex)
            return True
        if st.view and name.lower() in {n.lower() for n in self._others(st.view.players)}:
            tr["seen"] = now
            tr["with"] = tr.get("with") or now
            if now - tr["with"] < TRAIL_WAIT:
                b.status = f"Trailing {name} — with them, seeing which way they go"
                b._last_progress = now
                return True
            return False                                  # they're staying put: loop on (we'll meet again)
        tr["with"] = None
        return False

    def catching_up(self) -> bool:
        """Catching up with someone just ahead: lair pacing doesn't stop us."""
        c = self.chase
        if c and time.time() > c["until"]:
            self.chase = c = None
        return bool(c)

    def holding(self, mobs) -> bool:
        """Walk tick: waiting for them to catch up. Rest meanwhile; go once they're in our room or time's up."""
        h = self.hold
        if not h:
            return False
        b, st = self.s.bot, self.s.state
        now = time.time()
        if not b.walking or not b.loop:
            self.hold = None
            return False
        if h.get("here") or (st.view and h["name"].lower() in {n.lower() for n in self._others(st.view.players)}):
            self.s.log(f"{h['name']} came round to us — going on ahead of them")
            self.hold = None
            return False
        if now > h["until"]:
            self.s.log(f"{h['name']} didn't come round in {int(now - h['t']) // 60} min — carrying on")
            self.hold = None
            return False
        if mobs or st.in_combat:
            return False                              # something to fight here: the fight comes first
        b.status = f"Letting {h['name']} come round ({int(h['until'] - now)} s left) — then on ahead of them"
        if not st.resting:
            b.idle_regen(mobs, why=f"letting {h['name']} come round (they were clearing just ahead of us)")
        return True
