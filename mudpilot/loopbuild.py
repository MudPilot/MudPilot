"""Loop builder: make a loop from the MME map instead of recording one by hand.

From a starting room it looks at every lair within reach (same exit rules as walking: your
level, the keys you carry, the avoid list), scores each by what a full spawn is worth
(average exp × how many at once), drops ones the danger check says could kill you at full HP,
and then chains the best ones into loops of a few sizes, cheapest added steps first. Each
candidate gets a rough exp/hr from your own pace (seconds per step and per kill this session)
and how fast its lairs refill (learned, else 90 s).

The result is an ordinary MegaMUD-format .mp loop, saved with your other paths.
"""
from __future__ import annotations

from collections import deque

from .danger import lair_spawn
from .worlddb import DIRS

DEFAULT_REFILL = 90.0


def _passable(world, ex, level, have, avoid, goal=None):
    return world.can_use(ex, level=level, have=have, avoid=avoid, goal=goal)


def shop_items(world) -> set:
    """Items a shop sells: a way they open counts as reachable (you'd buy one on the way — the mine pass for
    Khazarad's mines)."""
    c = getattr(world, "_shop_items", None)
    if c is None or c[0] is not getattr(world, "gear", None):
        c = world._shop_items = (getattr(world, "gear", None),
                                 {n for n, g in (world.gear or {}).items() if "Shop #" in (g.get("obtained") or "")})
    return c[1]


def bfs(world, start, max_depth, level=None, have=None, avoid=None) -> dict:
    """{room: steps from start} out to max_depth."""
    dist = {start: 0}
    q = deque([start])
    while q:
        cur = q.popleft()
        d = dist[cur]
        if d >= max_depth:
            continue
        r = world.rooms.get(cur)
        if not r:
            continue
        for ex in r.exits.values():
            if ex.to not in dist and _passable(world, ex, level, have, avoid):
                dist[ex.to] = d + 1
                q.append(ex.to)
    return dist


class LoopBuilder:
    def __init__(self, session):
        self.s = session
        self.breathe = lambda: None      # Best spots sets a pause-now-and-then while it runs (spots.Breather)

    def _pace(self):
        """(seconds per step, seconds per kill) from this session, with sane defaults."""
        ss, st = self.s.stats, self.s.state
        walk = ss.time_in.get("walking", 0)
        fight = ss.time_in.get("fighting", 0)
        sps = walk / st.steps_walked if st.steps_walked >= 30 else 1.6
        spk = fight / st.kills if st.kills >= 10 else 9.0
        return max(0.5, min(sps, 6.0)), max(3.0, min(spk, 60.0))

    TIMED_H = 0.2         # a monster with a regen time this long or more is a boss on a timer, not lap exp

    @classmethod
    def timed(cls, m) -> bool:
        return float(m.get("regen_h") or 0) >= cls.TIMED_H

    def lair_counts(self, room):
        """{monster number: expected number in a full spawn} for a lair's regular monsters (no timed
        bosses), plus the monster records. A lair picks from its list, so each is n / len(list)."""
        n, mons = lair_spawn(self.s.world, room)
        mons = [m for m in mons if (m.get("exp") or 0) > 0 and self.s.bot.hostile(m)]
        if not n or not mons:
            return {}, mons
        each = n / len(mons)
        out = {}
        for m in mons:
            if not self.timed(m):
                out[m["num"]] = out.get(m["num"], 0) + each
        return out, mons

    def lap_exp(self, rooms) -> float:
        """Exp of one lap's full spawns over these lairs. A monster MME marks 'GameLimit 1' (one in the
        whole realm — the Scarecrow) counts once a lap however many lairs could hold it; bosses on a
        regen timer count nothing here (see boss_hr)."""
        w = self.s.world
        cnt = {}
        for r in rooms:
            c, _m = self.lair_counts(r)
            for num, k in c.items():
                cnt[num] = cnt.get(num, 0) + k
        tot = 0.0
        for num, k in cnt.items():
            m = w.monsters.get(num) or {}
            lim = int(m.get("limit") or 0)
            tot += (min(k, lim) if lim else k) * float(m.get("exp") or 0)
        return tot

    def boss_hr(self, rooms) -> tuple[float, list]:
        """Timed bosses in these lairs: exp/hr if you got every spawn (exp ÷ regen hours), and who."""
        seen, tot, who = set(), 0.0, []
        for r in rooms:
            _n, mons = lair_spawn(self.s.world, r)
            for m in mons:
                if self.timed(m) and m["num"] not in seen and (m.get("exp") or 0) > 0 and self.s.bot.hostile(m):
                    seen.add(m["num"])
                    tot += float(m["exp"]) / float(m["regen_h"])
                    who.append(m)
        return tot, who

    def lair_value(self, room):
        """What one full spawn of this lair is worth on a lap (timed bosses left out, a realm-unique
        monster counted at most its limit)."""
        c, mons = self.lair_counts(room)
        if not mons:
            return 0.0, None
        w = self.s.world
        val = 0.0
        for num, k in c.items():
            m = w.monsters.get(num) or {}
            lim = int(m.get("limit") or 0)
            val += (min(k, lim) if lim else k) * float(m.get("exp") or 0)
        return val, mons

    def build(self, center, max_steps=60, avoid_deadly=True, max_lairs=24, max_need=None) -> list:
        w, b, st = self.s.world, self.s.bot, self.s.state
        level = st.level or self.s.settings.char_level or None
        have = set(b.held_items() or set()) | shop_items(w)
        avoid = b.avoid_set()
        reach = bfs(w, center, max(4, max_steps // 2), level, have, avoid)
        lairs = []
        for room, d in reach.items():
            self.breathe()
            r = w.rooms.get(room)
            if not r or not r.lair or room in avoid:
                continue
            val, mons = self.lair_value(room)
            if val <= 0:
                continue
            danger = None
            if st.max_hp:
                need, a = self.s.danger.needed_pct(room)
                danger = need
                limit = 100 if (a and a.get("observed")) else 150     # MME-only numbers run high
                if max_need is not None:
                    limit = min(limit, max_need)      # a safer loop: leave out the lairs that could kill you
                if avoid_deadly and need is not None and need > limit:
                    continue
            lairs.append({"room": room, "value": val, "dist": d, "danger": danger,
                          "mobs": sorted({m["name"] for m in mons})})
        lairs.sort(key=lambda x: -x["value"] / (1 + x["dist"] / 8))
        lairs = lairs[:max_lairs]
        if not lairs:
            return []
        nodes = [center] + [x["room"] for x in lairs]
        dists = {}
        for n in nodes:
            self.breathe()
            dists[n] = bfs(w, n, max_steps, level, have, avoid)

        def d(a, c):
            return dists[a].get(c, 10 ** 6)
        out, seen = [], set()
        for budget in sorted({max(8, int(max_steps * f)) for f in (0.4, 0.6, 0.8, 1.0)}):
            tour = [center, center]
            length = 0
            left = list(range(len(lairs)))
            while True:
                self.breathe()
                best = None
                for i in left:
                    x = lairs[i]["room"]
                    for pos in range(1, len(tour)):
                        a, c = tour[pos - 1], tour[pos]
                        add = d(a, x) + d(x, c) - (d(a, c) if a != c else 0)
                        if length + add > budget or add >= 10 ** 5:
                            continue
                        score = lairs[i]["value"] / max(add, 1)
                        if best is None or score > best[0]:
                            best = (score, i, pos, add)
                if not best:
                    break
                _sc, i, pos, add = best
                tour.insert(pos, lairs[i]["room"])
                length += add
                left.remove(i)
            if len(tour) <= 2:
                continue
            key = frozenset(tour)
            if key in seen:
                continue
            seen.add(key)
            self.breathe()
            cand = self._assemble(tour, level, have, avoid, avoid_deadly)
            if cand:
                out.append(cand)
        out.sort(key=lambda c: -c["exp_hr"])
        return out

    def mme_refill(self, room) -> float:
        """Seconds for a lair to fill again, from MME's Delay (minutes) until we've timed it ourselves
        (pMUD: max(30, Delay×60 − 30))."""
        r = self.s.world.room(room)
        d = int(getattr(r, "delay", 0) or 0) if r else 0
        return max(30.0, d * 60 - 30.0) if d else DEFAULT_REFILL

    def estimate(self, steps, lair_rooms):
        """(exp per lap, seconds per lap, exp/hr) — rough, from MME values and your pace this session.
        Each lair assumed full when it's refilled in time (learned refill times, else 90 s)."""
        w = self.s.world
        exp_lap = self.lap_exp(lair_rooms)
        kills_lap = sum(lair_spawn(w, r)[0] for r in lair_rooms)
        sps, spk = self._pace()
        lap = steps * sps + kills_lap * spk * 0.7
        refills = [self.s.lairclock.estimate(r) or self.mme_refill(r) for r in lair_rooms]
        refill = sorted(refills)[len(refills) // 2] if refills else DEFAULT_REFILL
        fill = min(1.0, lap / refill) if refill else 1.0          # lapping faster than they refill = some empty
        exp_lap_eff = exp_lap * 0.75 * fill
        lap_eff = steps * sps + kills_lap * fill * spk * 0.75
        bonus, _who = self.boss_hr(lair_rooms)
        return exp_lap_eff, lap_eff, exp_lap_eff / max(lap_eff, 1) * 3600 + bonus * 0.5

    def _assemble(self, tour, level, have, avoid, avoid_deadly=False):
        w = self.s.world
        route = []
        for a, c in zip(tour, tour[1:]):
            seg = w.route(a, c, level=level, have=have, avoid=avoid)
            if seg is None:
                return None
            route += seg
        if not route:
            return None
        rooms, cur = [], tour[0]
        for ex in route:
            rooms.append(ex.to)
            cur = ex.to
        if cur != tour[0]:
            return None
        lair_rooms = []
        for r in rooms:
            if r not in lair_rooms and (self.lair_value(r)[0] > 0 or self.boss_hr([r])[0] > 0):
                lair_rooms.append(r)
        exp_lap_eff, lap_eff, exp_hr = self.estimate(len(route), lair_rooms)
        needs, all_obs = [], True
        for r in lair_rooms:
            need, a = self.s.danger.needed_pct(r)
            if need is not None:
                all_obs = all_obs and bool(a and a.get("observed"))
                if avoid_deadly and need > (100 if (a and a.get("observed")) else 150):
                    return None                  # the way round walks through a lair that could kill you
                needs.append(need)
        worst = max(needs or [0])
        mobs = sorted({m for r in lair_rooms for m in (self.lair_value(r)[1] and
                                                       [x["name"] for x in self.lair_value(r)[1]] or [])})
        start = w.room(tour[0])
        _b, bosses = self.boss_hr(lair_rooms)
        return {"bosses": [f"{m['name']} ({m['regen_h']:g}h)" for m in bosses], "start": tour[0], "route": route, "steps": len(route), "lairs": lair_rooms,
                "exp_lap": round(exp_lap_eff), "lap_secs": round(lap_eff),
                "exp_hr": exp_hr, "danger": worst, "observed": all_obs, "mobs": mobs,
                "title": f"Built: {start.name if start else ''} {len(lair_rooms)} lairs {len(route)} steps"}

    def save(self, cand, name):
        from .megamud_files import path_from_route
        import re
        mp = path_from_route(self.s.world, cand["start"], cand["route"], name=name)
        fn = re.sub(r"[^A-Za-z0-9 _-]+", "", name).strip().replace(" ", "_")[:40] or "built_loop"
        self.s.save_path(mp, fn + ".mp")
        self.s.on_paths_changed()
        return mp
