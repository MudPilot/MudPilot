"""Loop analyzer: walk a loop on paper, room by room, against your current HP, AC/DR, spells and party.

For every room the loop passes: is it a lair (what spawns, how many at once, what that's worth),
how much a full spawn could hurt you (your real fights there if it has seen some, else MME's
monster attack simulator), what HP % you'd want walking in, and a risk rating — plus boss rooms,
traps, and exits that need a key, an item, a toll, an action or a level. Then a summary: exp per
lap, a rough exp/hr, the worst room, and what to do about the risky ones.
"""
from __future__ import annotations

from .danger import lair_spawn

RISK = ((40, "safe"), (70, "moderate"), (100, "risky"))


def risk_label(need):
    if need is None:
        return "—"
    for lim, name in RISK:
        if need <= lim:
            return name
    return "deadly"


class LoopAnalyzer:
    def __init__(self, session):
        self.s = session

    def analyze(self, mp) -> dict:
        s, w = self.s, self.s.world
        st = s.state
        bosses = w.bosses_by_room()
        rows, seen = [], set()
        lair_rooms = []
        steps = [x for x in mp.steps if x.room]
        if not steps:
            return {"rows": [], "error": "this path isn't placed on the map yet (no room matches)"}
        for i, step in enumerate(steps):
            room = step.dest or step.room
            r = w.room(room)
            if not r or room in seen:
                continue
            seen.add(room)
            here = w.room(step.room)
            ex = next((e for e in (here.exits.values() if here else []) if e.to == step.dest), None)
            notes = []
            if ex is not None:
                if ex.kind == "trap":
                    notes.append("trap")
                if ex.kind in ("key", "item"):
                    num = w.exit_need(ex)
                    notes.append(f"needs {w.item_name(num[0])}" if num else ex.etype)
                if ex.kind == "toll":
                    notes.append(ex.etype)
                if ex.kind == "restricted":
                    notes.append(ex.etype)
                if ex.kind == "hidden" and ex.action_cmds():
                    notes.append(f"types '{ex.action_cmds()[0]}'")
                elif ex.kind == "hidden" and "search" in ex.etype.lower():
                    notes.append("search")
            b = [m["name"] for m in bosses.get(room, []) if s.bot.hostile(m)]
            if b:
                notes.append("boss: " + ", ".join(b))
            n, mons = lair_spawn(w, room)
            row = {"i": i + 1, "room": room, "name": r.name, "lair": bool(n), "count": n,
                   "mobs": sorted({m["name"] for m in mons}), "value": 0, "need": None, "dmg": None,
                   "observed": False, "notes": notes}
            if n:
                val, good = s.loopbuilder.lair_value(room)
                row["value"] = round(val)
                need, a = s.danger.needed_pct(room) if st.max_hp else (None, None)
                row["need"] = need
                row["dmg"] = a["dmg"] if a else None
                row["observed"] = bool(a and a.get("observed"))
                if val > 0:
                    lair_rooms.append(room)
            row["risk"] = risk_label(row["need"])
            if row["lair"] and row["need"] is not None and not row["observed"] and row["risk"] != "safe":
                row["risk"] += "?"                    # MME's numbers only (they run high) until it's fought there
            if row["lair"] or notes:
                rows.append(row)
        exp_lap, lap_secs, exp_hr = s.loopbuilder.estimate(len(mp.steps), lair_rooms)
        risky = [r for r in rows if r["risk"].rstrip("?") in ("risky", "deadly")]
        worst = max((r for r in rows if r["need"] is not None), key=lambda r: r["need"], default=None)
        tips = []
        if not st.max_hp:
            tips.append("Your HP isn't known yet — connect (or type 'st') so the risk numbers mean something.")
        deadly = [r for r in rows if r["risk"] == "deadly"]           # deadly from your own fights
        deadly_mme = [r for r in rows if r["risk"] == "deadly?"]
        if deadly:
            tips.append(f"{len(deadly)} room{'s' if len(deadly) > 1 else ''} could kill you even from full HP "
                        f"(worst: {deadly[0]['name']} {deadly[0]['room'][0]}/{deadly[0]['room'][1]}) — skip this loop "
                        "or bring more party / better AC.")
        elif deadly_mme:
            tips.append(f"MME's numbers say {len(deadly_mme)} lair{'s' if len(deadly_mme) > 1 else ''} could be too much "
                        "(they run high — if you already farm this loop, ignore it; the real fights correct it).")
        elif risky:
            tips.append(f"{len(risky)} risky room{'s' if len(risky) > 1 else ''}: keep the danger check on (it rests "
                        "up before them) and think about a curse opener (Combat tab).")
        unobs = [r for r in rows if r["lair"] and r["need"] is not None and not r["observed"]]
        if unobs:
            tips.append(f"{len(unobs)} lair{'s' if len(unobs) > 1 else ''} rated from MME's numbers only (they run "
                        "high); a few laps of real fights make them exact.")
        if any("needs" in n for r in rows for n in r["notes"]):
            tips.append("Some exits need items — the needed-items check fetches or warns before you start.")
        if not tips:
            tips.append("Nothing worrying on this loop at your current HP, AC and party.")
        return {"rows": rows, "steps": len(mp.steps), "lairs": len(lair_rooms), "exp_lap": round(exp_lap),
                "lap_secs": round(lap_secs), "exp_hr": exp_hr, "worst": worst, "tips": tips,
                "party": len(st.party) or 1}
