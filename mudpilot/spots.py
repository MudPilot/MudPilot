"""Best spots: where on the map should this character (and party) hunt for the most exp/hr?

1. Everything you can walk to from here (your level, keys, avoid list) — and the steps to get there.
2. Every lair in reach scored for you: what a full spawn is worth, and how much it could hurt you
   (your real fights there if seen, else MME's attack simulator vs your HP/AC/DR/spells; a bigger
   party soaks more, a healer stretches it further). Lairs that could kill you are dropped.
3. Nearby lairs are grouped into hunting areas, and the loop builder makes the best loop in each.
4. Calibrated with your own results: loops you've really run show how far off the estimates are
   (e.g. it said 1.2M/hr, you made 1.7M/hr), and every area's estimate is scaled the same way.
"""
from __future__ import annotations

import statistics
import sys
import time
from collections import Counter
from contextlib import contextmanager

from .analyzer import risk_label
from .loopbuild import bfs, shop_items

CLUSTER_STEPS = 12
BUILD_TOP = 60
KEEP_SECS = 30 * 60          # the last search is shown straight away when the window opens again within this
_SWITCH = sys.getswitchinterval()
_calm = 0                    # workers inside calm_thread() right now


@contextmanager
def calm_thread():
    """A long search on a worker thread without the window and the bot stuttering (Dan, 2026-11-02: "best spots
    really bogs down mudpilot"). Python runs one thread at a time: this one drops to low priority and hands the
    interpreter back every half millisecond, so the game, the walk and the window always get their turn."""
    global _calm
    _calm += 1
    sys.setswitchinterval(0.0005)
    try:
        if sys.platform == "win32":
            import ctypes
            k = ctypes.windll.kernel32
            k.SetThreadPriority(k.GetCurrentThread(), -2)        # THREAD_PRIORITY_LOWEST
    except Exception:
        pass
    try:
        yield
    finally:
        _calm -= 1
        if not _calm:                               # (Best spots and Best case can both be running)
            sys.setswitchinterval(_SWITCH)


class Breather:
    """Every ~20 ms of work, a 5 ms nap: the rest of MudPilot runs smoothly while a search grinds on."""
    def __init__(self, work=0.02, nap=0.005):
        self.work, self.nap, self.t = work, nap, time.perf_counter()

    def __call__(self):
        if time.perf_counter() - self.t > self.work:
            time.sleep(self.nap)
            self.t = time.perf_counter()


class SpotFinder:
    def __init__(self, session):
        self.s = session
        self.cancel = False
        self.last = None             # (time, room, party, result) — shown again when the window reopens
        self.breathe = lambda: None

    def kept(self):
        """The last search, if it's recent and you're still with the same party (None = search again)."""
        if not self.last:
            return None
        t, _room, party, r = self.last
        if time.time() - t > KEEP_SECS or party != self._party_key():
            return None
        return r, t

    def _party_key(self):
        return tuple(sorted(n.lower() for n in (self.s.state.party or {})))

    def calibration(self) -> tuple[float, int]:
        """(actual / estimated exp/hr over your real loops, how many loops that's based on)."""
        s = self.s
        ratios = []
        for key, sm in s.loopstats.all_summaries():
            if sm["laps"] < 3 or sm["exp_hr"] <= 0:
                continue
            mp = next((p for p in s.paths if s.bot.x.loop_key(p) == key and p.resolved), None)
            if not mp:
                continue
            try:
                est = s.analyzer.analyze(mp)["exp_hr"]
            except Exception:
                continue
            if est > 0:
                ratios.append(sm["exp_hr"] / est)
        if not ratios:
            return 1.0, 0
        return max(0.3, min(3.0, statistics.median(ratios))), len(ratios)

    def find(self, progress=lambda done, total, msg: None, max_steps=60, top=20) -> dict:
        """(see _find) — with the map keeping out of lairs that would maul you on the way: an area you can only
        reach past them (the Old Mine loop behind the wraith spiders, Dan 2026-10-28) isn't offered."""
        w = self.s.world
        try:
            self.s.route_char()
        except Exception:
            pass
        w._no_danger = getattr(w, "danger_fn", None) is not None
        self.breathe = Breather()
        lb = self.s.loopbuilder
        lb.breathe = self.breathe
        try:
            r = self._find(progress, max_steps, top)
            if not r.get("error") and not self.cancel:
                self.last = (time.time(), self.s.state.room, self._party_key(), r)
            return r
        finally:
            w._no_danger = False
            self.breathe = lambda: None
            lb.breathe = lambda: None

    def _find(self, progress=lambda done, total, msg: None, max_steps=60, top=15) -> dict:
        s, w, b, st = self.s, self.s.world, self.s.bot, self.s.state
        here = st.room
        if not here:
            return {"error": "Where are you? Press Enter in the game so MudPilot knows the room first."}
        level = st.level or s.settings.char_level or None
        held = set(b.held_items() or set())
        have = held | shop_items(w)                  # (a shop item on the way gets bought: the mine pass)
        avoid = b.avoid_set()
        progress(0, 1, "Working out where you can walk to…")
        reach = bfs(w, here, 2000, level, have, avoid)
        progress(0, 1, f"{len(reach):,} rooms in reach — scoring lairs for you…")
        lairs = {}
        for room in reach:
            self.breathe()
            r = w.rooms.get(room)
            if not r or not r.lair:
                continue
            val, mons = s.loopbuilder.lair_value(room)
            if val <= 0:
                continue
            if st.max_hp:
                need, a = s.danger.needed_pct(room)
                if need is not None and need > (100 if (a and a.get("observed")) else 150):
                    continue                              # could kill you, even at full HP
            lairs[room] = val
        progress(0, 1, f"{len(lairs):,} lairs worth hunting — grouping them into areas…")
        order = sorted(lairs, key=lambda k: -lairs[k])
        taken, clusters = set(), []
        for seed in order:
            if seed in taken or self.cancel:
                continue
            self.breathe()
            local = bfs(w, seed, CLUSTER_STEPS, level, have, avoid)
            members = [l for l in order if l in local and l not in taken]
            for m in members:
                taken.add(m)
            clusters.append({"seed": seed, "lairs": members, "value": sum(lairs[m] for m in members)})
        clusters.sort(key=lambda c: -c["value"])
        todo = clusters[:BUILD_TOP]
        factor, n_cal = self.calibration()
        out = []
        for i, c in enumerate(todo):
            if self.cancel:
                break
            progress(i, len(todo), f"Building the best loop in area {i + 1} of {len(todo)}…")
            try:
                cands = s.loopbuilder.build(c["seed"], max_steps, avoid_deadly=True, max_lairs=12)
            except Exception:
                cands = []
            if not cands:
                continue
            best = cands[0]
            if (best.get("danger") or 0) > 90:
                # one nasty lair makes the whole loop 'deadly?' (Dan: the flaming mammoths came with a horned demon
                # lair) — build it without the lairs that could kill you and offer that
                try:
                    safer = s.loopbuilder.build(c["seed"], max_steps, avoid_deadly=True, max_lairs=12, max_need=90)
                except Exception:
                    safer = []
                if safer and safer[0]["exp_hr"] > 0:
                    best = safer[0]
            names = Counter(w.room(r).name.split(",")[0].strip() for r in best["lairs"] if w.room(r))
            area = names.most_common(1)[0][0] if names else w.room(c["seed"]).name
            proven = self._proven(best)
            needs = []
            try:
                rt = w.route(here, best["start"], level=level, have=have, avoid=avoid)
                needs = sorted(w.item_name(n) for n in b._route_items(here, rt or [], held) if n in shop_items(w))
            except Exception:
                pass
            out.append({"area": area, "seed": c["seed"], "dist": reach.get(best["start"], reach.get(c["seed"], 0)),
                        "needs": needs,
                        "cand": best, "est_hr": best["exp_hr"] * factor, "raw_hr": best["exp_hr"],
                        "risk": risk_label(best["danger"] or None) + ("?" if not best.get("observed") and
                                                                      (best["danger"] or 0) > 40 else ""),
                        "need": best["danger"],
                        "mobs": best["mobs"], "proven": proven})
        # one row per area name (keep the better one)
        best_by = {}
        for o in out:
            k = o["area"].lower()
            if k not in best_by or o["est_hr"] > best_by[k]["est_hr"]:
                best_by[k] = o
        # '?' = MME's guess, not seen yet (they run high): an unproven 'risky?' sits with the moderate ones — the
        # flaming mammoths (71%, 3.5M/hr) fell off the list behind every 'moderate?' area
        rank = {"safe": 0, "moderate": 0, "—": 0, "moderate?": 0, "risky?": 0, "risky": 1, "deadly?": 2, "deadly": 3}
        ranked = sorted(best_by.values(), key=lambda o: (rank.get(o["risk"], 1), -(o["proven"] or o["est_hr"])))[:top]
        progress(1, 1, "Done")
        return {"spots": ranked, "factor": factor, "calibrated_on": n_cal, "reach": len(reach),
                "lairs": len(lairs), "party": len(st.party) or 1}

    def _proven(self, cand):
        """Your real exp/hr on a loop of yours that covers most of this area's lairs, if any."""
        s = self.s
        lset = set(cand["lairs"])
        best = None
        for key, sm in s.loopstats.all_summaries():
            if sm["laps"] < 3:
                continue
            mp = next((p for p in s.paths if s.bot.x.loop_key(p) == key), None)
            if not mp:
                continue
            rooms = {x.dest for x in mp.steps if x.dest}
            if lset and len(lset & rooms) / len(lset) >= 0.5:
                best = max(best or 0, sm["exp_hr"])
        return best
