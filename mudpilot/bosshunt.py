"""Boss hunt: when a boss you've ticked "Hunt" for is due back, step off the loop, go kill it, come back.

Like pMUD's auto-kill diversion. Once per spawn: the respawn clock comes due → if MudPilot is out
looping (not resting, not fighting) and the boss's room is within reach (Bosses tab: max steps),
it remembers the loop, walks to the boss, fights it (stop-before-boss is skipped for it), then picks
the loop up again. Not there when it arrives (someone beat you to it) → waits a little, then goes
back. Nothing is retried until the boss is killed again and its clock comes round once more.

A boss that can turn up in any of several lairs (the crimson mist: one of twelve monsters for sixteen lairs round
the Ancient Ruin) gets a sweep instead: the shortest tour through all of them, last-seen first, fighting it wherever
it shows, and only giving up after the whole round (Dan, 2026-11-02).
"""
from __future__ import annotations

import re
import time

WAIT_THERE = 25         # seconds at the spawn room before giving up on it
GIVE_UP = 600           # whole trip
SWEEP_LOOK = 3          # a sweep: seconds in each lair to see what's there before the next
SWEEP_LEG_SECS = 60     # …and this much more time for the whole trip per lair
WALK_SECS = 3           # …and this much per step of the walk there


class BossHunt:
    def __init__(self, session):
        self.s = session
        self.active = None          # {"num", "name", "room", "dead_since", "back": (path, loop), "t", "arrived"}
        self._lair_cache = {}

    # ------------------------------------------------------------ which boss, where
    def _room_for(self, mon, rec):
        kills = [k for k in rec.get("kills") or [] if k.get("room")]
        if kills:
            return tuple(kills[-1]["room"])
        if rec.get("seen_room"):
            return tuple(rec["seen_room"])
        sp = mon.get("spawn_rooms") or []
        return tuple(sp[0]) if sp else None

    def lairs(self, mon) -> list:
        """Every lair room this monster can spawn in (MME's lair lists)."""
        num = mon["num"]
        if num not in self._lair_cache:
            out = []
            for k, r in self.s.world.rooms.items():
                if not r.lair:
                    continue
                nums = {x.strip() for x in r.lair.split(":")[-1].split(",")}
                if str(num) in nums:
                    out.append(k)
            self._lair_cache[num] = out
        return self._lair_cache[num]

    def _tour(self, here, rooms, first=None) -> list:
        """The lairs in a short walking order (nearest next), starting with where it was last seen."""
        from .loopbuild import bfs
        w = self.s.world
        left = [r for r in rooms if r != first]
        out = [first] if first else []
        cur = first or here
        while left:
            dist = bfs(w, cur, 80) if cur else {}
            nxt = min(left, key=lambda r: dist.get(r, 10 ** 6))
            out.append(nxt)
            left.remove(nxt)
            cur = nxt
        return out

    def due(self):
        """[(mon, rec, room)] bosses ticked for hunting whose respawn time has come (not tried this spawn)."""
        b = self.s.bosses
        now = time.time()
        out = []
        for num, rec in b.data.items():
            if not rec.get("hunt"):
                continue
            mon = self.s.world.monsters.get(int(num))
            regen = b.respawn_secs(num) if mon else 0
            if not mon or not regen:
                continue
            chk = rec.get("check_at")
            if chk and now >= chk and rec.get("check_tried") != chk:
                pass                                   # a booked check (never caught it yet): look again
            elif not rec.get("dead_since") or now < rec["dead_since"] + regen or                     rec.get("hunt_tried") == rec["dead_since"]:
                continue
            room = self._room_for(mon, rec) or next(iter(self.lairs(mon)), None)
            if room:
                out.append((mon, rec, room))
        return out

    # ------------------------------------------------------------ running
    def tick(self):
        s, b, st, cfg = self.s, self.s.bot, self.s.state, self.s.settings
        if not s.telnet.connected or not s._entered:
            return
        self._loot_tick()
        if self.active:
            return self._follow_up()
        hr = getattr(s, "_hunt_resume", None)
        if hr and time.time() - hr["t"] > 20 and st.room and not st.in_combat and not getattr(s, "_regroup", None)                 and not s.comeback.holding():
            # a restart that was asked to hunt (resume.json 'hunt'): once back in and the party's together
            s._hunt_resume = None
            mon = s.world.monsters.get(int(hr["num"]))
            if mon:
                s.log("Boss hunt: " + self.hunt_now(mon, back=(hr["back"], True) if hr.get("back") else None))
            return
        if getattr(b.x, "_following", None) and not getattr(b.x, "_own_party", False):
            # (0.8.201, party hunt: a follower is never "walking", so with the leader's @hunt on it farmed bosses on
            #  its own and walked off from the leader — the leader hunts, the party follows, like lair camp)
            return
        on_loop = cfg.boss_hunt_on and b.walking and b.path
        farming = cfg.boss_farm_on and not b.walking and not b.detour and not getattr(b, "paused", False) \
            and not str(b.status).startswith(("Stopped by you", "Hung up", "Stopped: character died"))
        if not (on_loop or farming):
            return
        if st.in_combat or st.resting or (st.view and st.view.monsters) or b.detour:
            return
        if st.max_hp and st.hp_pct() < max(cfg.rest_until_hp - 5, 50):
            return                                     # not while hurt: the next rest comes first
        due = self.due()
        if not due:
            return
        here = st.room
        # nearest due boss first
        ranked = []
        for mon, rec, room in due:
            lairs = self.lairs(mon)
            sweep = self._tour(here, lairs, first=room if room in lairs else None) if len(lairs) > 1 else []
            if sweep:
                room = sweep[0]
            route = self._route(here, room) if here else None
            ranked.append((len(route) if route is not None else 10 ** 6, mon, rec, room, route, sweep))
        ranked.sort(key=lambda x: x[0])
        for _n, mon, rec, room, route, sweep in ranked:
            rec["hunt_tried"] = rec.get("dead_since")
            if rec.get("check_at"):
                rec["check_tried"] = rec["check_at"]
            s.bosses.save()
            if route is None:
                s.log(f"Boss hunt: {mon['name']} is due, but there's no route to {room[0]}/{room[1]} from here")
                self._book_check(mon, rec)
                continue
            if len(route) > int(cfg.boss_hunt_max_steps or 80) and not rec.get("hunt_far"):
                s.log(f"Boss hunt: {mon['name']} is due, but it's {len(route)} steps away "
                      f"(limit {cfg.boss_hunt_max_steps}) — not going")
                self._book_check(mon, rec)
                continue
            origin = None if on_loop else (getattr(self, "_chain_from", None) or here)
            self._chain_from = None
            back = (b.path, b.loop) if on_loop else None
            if on_loop and not b.loop and b.after_goto is not None:
                # on the Go to back to a loop's start (the last hunt's way home): come back to the loop, not
                # that Go to (Evolution, 2026-11-06: the golem hunt took 'Go to 17/183' as home, arrived, stood)
                back = (b.after_goto, True)
            self._start(mon, rec, room, route, sweep, back, origin, "should be up")
            return

    def _start(self, mon, rec, room, route, sweep, back, origin, why) -> bool:
        s, b = self.s, self.s.bot
        self.active = {"num": mon["num"], "name": mon["name"], "room": room, "dead_since": rec.get("dead_since") or 0,
                       "back": back, "from": origin, "t": time.time(), "arrived": 0,
                       "killed": 0, "sweep": list(sweep[1:]), "lairs": len(sweep),
                       "trip": WALK_SECS * len(route)}     # (a far one — Hunt now from 263 steps — gets the walk too)
        b._boss_ok = room                              # stop-before-boss doesn't stop us at its door
        s.log(f"Boss hunt: {mon['name']} {why} — "
              + (f"leaving {back[0].title} to kill it" if back else "going to kill it")
              + f" ({len(route)} steps to {room[0]}/{room[1]})"
              + (f" — it can be in any of {len(sweep)} lairs: checking them all, nearest next" if sweep else ""))
        s.notify.send("track", f"Boss hunt: going for {mon['name']}")
        if not b.goto(room):
            s.log("Boss hunt: couldn't start the walk" + (" — staying on the loop" if back else ""))
            self.active = None
            return False
        return True

    def named(self, q):
        """The monster a name means, for hunting: of the same-named ones the one with a respawn time, then the most
        exp (MME has two 'crimson mist's — the 300k one with a 7-hour regen, and an 11k one with none)."""
        q = (q or "").strip().lower()
        w = self.s.world
        mons = [m for m in w.monsters.values() if m.get("in_game") and self.s.bosses.killable(m)]
        hits = [m for m in mons if m["name"].lower() == q] or [m for m in mons if q in m["name"].lower()]
        if not hits:
            return None
        return max(hits, key=lambda m: (bool(m.get("regen_h")), m.get("exp") or 0))

    def hunt_now(self, mon, back=None) -> str:
        """Go for it now, clock or no clock (Dan, 2026-11-03: the crimson mist, never killed by us — no clock to say
        it's due, and a Go to only walks to the nearest of its 16 lairs). Every lair it can be in, nearest
        next; back to the loop or the room you were in after. What happened, to say."""
        s, b, st = self.s, self.s.bot, self.s.state
        if self.active:
            return f"already hunting {self.active['name']}"
        here = st.room
        if not here:
            return "not sure where I am — can't plan the hunt"
        rec = s.bosses.data.get(str(mon["num"]))
        if rec is None:
            s.bosses.track(mon)
            rec = s.bosses.data.get(str(mon["num"])) or {}
        rec["hunt"] = True                             # (not caught: looked for again every respawn — _book_check)
        rec["hunt_far"] = True                         # you asked for it by name: no step limit on those looks
        s.bosses.save()
        lairs = self.lairs(mon)
        first = self._room_for(mon, rec)
        if len(lairs) > 1:
            sweep = self._tour(here, lairs, first=first if first in lairs else None)
            room = sweep[0]
        else:
            room = first or next(iter(lairs), None)
            sweep = []
        if not room:
            return f"MME doesn't say where {mon['name']} lives"
        route = self._route(here, room)
        if route is None:
            return f"no route to {mon['name']} ({room[0]}/{room[1]})"
        if back is None:
            if b.walking and b.path and b.loop:
                back = (b.path, b.loop)
            elif b.last_path is not None and b.last_loop:
                # not looping right now (stopped, on a Go to): back to the last loop after, not just this room
                # (Dan, 2026-11-03: 'finish the hunt then loop')
                back = (b.last_path, True)
        if not self._start(mon, rec, room, route, sweep, back, None if back else here, "— hunting it now"):
            return f"couldn't start the walk to {mon['name']}"
        return (f"hunting {mon['name']}: " + (f"{len(sweep)} lairs, nearest next" if sweep else
                                              f"{room[0]}/{room[1]}") + f", {len(route)} steps to the first")

    def _follow_up(self):
        s, b, st = self.s, self.s.bot, self.s.state
        a = self.active
        now = time.time()
        rec = s.bosses.data.get(str(a["num"]), {})
        if rec.get("dead_since", 0) > a["dead_since"]:
            if st.in_combat:
                return                                 # its friends first
            if not a["killed"]:
                a["killed"] = now
                cmds = [c.strip() for c in (s.settings.boss_loot_cmd or "").split(";") if c.strip()]
                if cmds:
                    s.log(f"Boss hunt: {a['name']} killed — grabbing the loot ({'; '.join(cmds)})")
                    for c in cmds:
                        s.send(c, from_bot=True)
                s.send("", from_bot=True)              # look: what it left on the floor
                return
            if now - a["killed"] < 2:
                return
            if not a.get("looted"):
                a["looted"] = True
                if self.grab_drops(a["num"]):
                    a["killed"] = now - 2              # a moment for the gets to land
                    return
            if now - a["killed"] < 4:
                return                                 # let the pick-ups land
            return self._done(f"{a['name']} killed")
        if now - a["t"] > GIVE_UP + SWEEP_LEG_SECS * a.get("lairs", 0) + a.get("trip", 0):
            return self._done("took too long")
        if st.in_combat or st.resting:
            return
        if st.room == a["room"] and not b.walking:
            if not a["arrived"]:
                a["arrived"] = now
            present = any(m["num"] == a["num"] for m in s.bosses.bosses_in_view())
            if not present and a.get("sweep") and now - a["arrived"] > SWEEP_LOOK:
                nxt = a["sweep"].pop(0)                # not in this lair: the next one
                a.update(room=nxt, arrived=0, leg_t=now)
                b._boss_ok = nxt
                done_n = a["lairs"] - len(a["sweep"])
                s.log(f"Boss hunt: no {a['name']} here — lair {done_n} of {a['lairs']}: {nxt[0]}/{nxt[1]}")
                if not b.goto(nxt):
                    return self._done(f"no way on to {nxt[0]}/{nxt[1]}")
                return
            if not present and now - a["arrived"] > (SWEEP_LOOK if a.get("lairs") else WAIT_THERE):
                return self._done(f"{a['name']} wasn't in any of its {a['lairs']} lairs (someone got it first?)"
                                  if a.get("lairs") else f"{a['name']} wasn't there (someone got it first?)")
        elif b.walking:
            a["leg_t"] = now                           # 'stopped' = stood still 20 s, not 20 s since the hunt began
        elif not a["arrived"] and (b.errands.active or b.errands.asking or s.trips.trip):
            a["leg_t"] = now                           # fetching what the way needs (a raft at the Pier, the bank), or
            return                                     # asking the party who has one: the walk goes on after — not
            #                                            'stopped' (Evolution, 2026-11-03; the @have ask, 2026-11-06)
        elif not a["arrived"] and now - a.get("leg_t", a["t"]) > 5:
            if str(b.status).startswith(("Stopped by you", "Hung up")):
                self.active = None                     # you took over: don't drag it back to the loop
                b._boss_ok = None
                s.log("Boss hunt: cancelled (you stopped it)")
                return
            if now - a.get("leg_t", a["t"]) > 20:
                return self._done("the walk there stopped")

    def _route(self, here, room):
        """The way there as a Go to finds it: through doors you pick or bash, or with keys it fetches on the way
        (Dan, 2026-11-03: '@hunt guardian golem' — 'no route', behind the green metal door Evolution picks)."""
        b, cfg = self.s.bot, self.s.settings
        r = b.plan_route(here, room)
        if r is None and (cfg.auto_get_items or cfg.bash_key_doors):
            r = b.keyed_route(here, room)
        return r

    def after_kill(self, num):
        """A boss killed here, on a loop or by hand (a hunt does its own): look, then pick up its drops."""
        a = self.active
        if a and int(a["num"]) == int(num):
            return
        self._loot = {"num": int(num), "t": time.time(), "looked": 0}

    def _loot_tick(self):
        lt = getattr(self, "_loot", None)
        if not lt:
            return
        s, now = self.s, time.time()
        if now - lt["t"] > 30:
            self._loot = None                          # walked on / fighting on: too late
            return
        if s.state.in_combat:
            return                                     # its friends first
        if not lt["looked"]:
            lt["looked"] = now
            s.send("", from_bot=True)                  # look: what it left on the floor
        elif now - lt["looked"] >= 2:
            self._loot = None
            self.grab_drops(lt["num"])

    def grab_drops(self, num) -> list:
        """Pick up what the boss drops — the items on its drop list (MME's, and what we've seen it drop) that are
        on the floor — and not chests, they're heavy (Dan, 2026-11-03: 'as opposed to having everybody get-all').
        The names sent 'get'."""
        s = self.s
        mon = s.world.monsters.get(int(num))
        v = s.state.view
        if not mon or not v or not v.items:
            return []
        try:
            names = {n.lower() for n, _p in s.combatlog.mme_drops(mon)}
            names |= {n.lower() for n in (s.combatlog.seen_drops(mon["name"])[1] or {})}
        except Exception:
            names = set()
        got = []
        for _q, name in v.items:
            nm = name.lower().strip()
            if not nm or "chest" in nm or nm in got:
                continue
            if any(nm == d or nm.rstrip("s") == d or nm == d + "s" for d in names):
                s.send(f"get {name}", from_bot=True)
                got.append(nm)
        if got:
            s.log(f"Boss hunt: picking up what {mon['name']} dropped — {', '.join(got)}")
        return got

    def _book_check(self, mon, rec):
        """Not caught (not there, too far, no way): look again one respawn later, and again after that, till it's
        caught at home and its own clock takes over (Dan, 2026-11-03: the crimson mist, 7 h — 'keep checking every
        7 hours, it'll catch it home eventually')."""
        regen = self.s.bosses.respawn_secs(mon["num"])
        if not regen:
            return
        rec["check_at"] = time.time() + regen
        self.s.bosses.save()
        mins = regen / 60
        self.s.log(f"Boss hunt: looking for {mon['name']} again in "
                   + (f"{mins / 60:.0f} h" if mins >= 90 else f"{mins:.0f} min"))

    def _done(self, why):
        s, b = self.s, self.s.bot
        a, self.active = self.active, None
        b._boss_ok = None
        rec = s.bosses.data.get(str(a["num"]))
        if rec is not None and not a.get("killed") and rec.get("hunt"):
            mon = s.world.monsters.get(int(a["num"]))
            if mon:
                self._book_check(mon, rec)
        if s.state.dead or getattr(b, "_death_at", 0) > a["t"]:
            return                                     # died on the way: nothing restarts by itself
        if not a.get("back"):
            nxt = self.due()
            if nxt:
                self._chain_from = a.get("from")
                s.log(f"Boss hunt: {why} — next: {nxt[0][0]['name']}")
                return                                 # the next tick takes the next due boss
            fr = a.get("from")
            if fr and s.state.room != fr:
                s.log(f"Boss hunt: {why} — back to where I was ({fr[0]}/{fr[1]})")
                b.goto_bg(fr)
            else:
                s.log(f"Boss hunt: {why}")
            return
        mp, loop = a["back"]
        s.log(f"Boss hunt: {why} — back to {mp.title}")
        if b.walking:
            b.stop("Boss hunt over")
        here = s.state.room
        if here and mp.resolved and mp.steps and mp.steps[0].room and not any(x.room == here for x in mp.steps):
            # far off it: a Go to its start, then the loop — the way back can be through doors you pick (Evolution,
            # 2026-11-03: back from the guardian golem's room, 154 steps, the loop's own way back had no route
            # through the locked doors — 'lost and no route back to the path', sitting there)
            if b.goto(mp.steps[0].room, then=mp):
                return
        b.start_path(mp, loop=loop, checked=True)

    def next_due(self):
        """(boss name, seconds until it's due) for the soonest ticked boss."""
        b = self.s.bosses
        best = None
        for num, rec in b.data.items():
            mon = self.s.world.monsters.get(int(num))
            regen = b.respawn_secs(num) if mon else 0
            if not rec.get("hunt") or not mon or not regen:
                continue
            if rec.get("check_at"):
                left = rec["check_at"] - time.time()
            elif rec.get("dead_since"):
                left = rec["dead_since"] + regen - time.time()
            else:
                continue
            if best is None or left < best[1]:
                best = (mon["name"], left)
        return best

    def reset(self, why=""):
        self.active = None
