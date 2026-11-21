"""Combat summary, monster drops and item history (pMUD's Combat Summary, Monster Stats and Item History windows).

Per monster: your hits / misses / crits / backstabs, damage per hit and per round, each spell's damage and
how often it lands; what it did to you (hits, misses, damage) — and the last 10 rounds (done, taken, HP).
Drops: what showed up in the room right after a kill, counted per monster, next to MME's drop %.
Item history: everything picked up, dropped, sold, given or stashed, with the time and room.

All of it is for this session except the drop counts, which are kept per board (drops.json)."""
from __future__ import annotations

import json
import os
import re
import time
from collections import Counter, deque

from . import config

_ART = r"(?:the |an? |some )?"
# "You slash the orc for 12 damage!" · "You critically slash…" · "You surprise the orc and stab it for 300 damage!"
MY_HIT_RE = re.compile(r"^You (critically |surprise )?(?!gain\b|lose\b)([a-z][a-z'-]*(?: at)?) " + _ART +
                       r"(.+?)(?: (?:with|and) [^!]*?)? for (\d+) damage!", re.I)
# "Your flaming magma blast strikes large giant scorpion for 64 damage!"
MY_SPELL_RE = re.compile(r"^Your (.+?) (?:strikes|hits|burns|blasts|engulfs|freezes|shocks|sears|smites|"
                         r"envelops|lashes|crushes|pierces|batters|withers|rends|scorches|"
                         r"[a-z]+s) " + _ART + r"(.+?) for (\d+) damage!", re.I)
# "You swing at the orc!" / "You lunge at the kobold, but miss!" (a swing with no damage = a miss)
MY_MISS_RE = re.compile(r"^You (?:swing|lunge|slash|stab|thrust|punch|kick|lash|strike|hack|chop|whip|fire|"
                        r"shoot|throw|bash|smash|cut|claw|bite|jab|chop|club|pummel|hit)s? at " + _ART +
                        r"(.+?)(?:,? but miss(?:es)?)?[!.]$", re.I)
# "The orc smashes you for 120 damage!" · "The guardsman lunges at you with his halberd for 12 damage!"
MON_SPELL_RE = re.compile(r"^(?:The |An? )(.+?) casts? (.+?) (?:on|at|upon) you for (\d+) damage!", re.I)
MON_HIT_RE = re.compile(r"^(?:The |An? )((?:(?!\bcasts?\b).)+?) (?!casts\b)(?:[a-z]+ly )?[a-z'-]+ (?:at )?you(?: with [^!]*?)?"
                        r" for (\d+) damage!", re.I)
# "The large giant scorpion lunges at you!" · "The orc swings at you with a club!"
MON_MISS_RE = re.compile(r"^(?:The |An? )(.+?) (?:[a-z]+ly )?(?:swings|lunges|lashes|strikes|snaps|claws|bites|"
                         r"stabs|slashes|thrusts|punches|kicks|whips|hacks|chops|smashes|swipes|charges|"
                         r"shoots|fires|throws|jabs|pummels|stings|gores|butts|rakes|tears)"
                         r" at you(?: with [^!.]*)?(?:,? but (?:it )?miss(?:es)?)?[!.]$", re.I)
GOT_RE = re.compile(r"^You (?:took|picked up|get|receive[sd]?) (?:(\d+) )?(.+?)\.?$", re.I)
LOST_RE = re.compile(r"^You (dropped|drop|gave|give|sold|sell|hid|deposited|deposit|put) (?:(\d+) )?(?!in the shadows)"
                     r"(.+?)(?: (?:to|in|into) (.+?))?(?: for .+)?\.?$", re.I)
COIN_WORDS = ("copper", "silver", "gold crown", "platinum", "runic")
ROUND_GAP = 2.5


def _base(name):
    return re.sub(r"^(?:the|an?|some)\s+", "", (name or "").strip().lower())


class CombatLog:
    def __init__(self, session):
        self.s = session
        self.mobs: dict = {}            # monster name -> stats dict
        self.spells: dict = {}          # spell name -> {"casts", "dmg", "min", "max"}
        self.rounds = deque(maxlen=10)  # last rounds: {t, mon, done, taken, hp0, hp1}
        self._round = None
        self.items = deque(maxlen=500)  # item history: (t, what, qty, item, room, note)
        self._pending_drop = None
        self.drops: dict = {}           # monster name -> {"kills": n, "items": {item: [count, last_t]}}
        self._drops_loaded_for = None
        self.reset_t = time.time()

    # ------------------------------------------------------------------ storage (drops only)
    @property
    def file(self):
        return os.path.join(config.board_dir(self.s.settings.board), "drops.json")

    def _load(self):
        if self._drops_loaded_for == self.s.settings.board:
            return
        self._drops_loaded_for = self.s.settings.board
        try:
            with open(self.file, encoding="utf-8") as f:
                self.drops = json.load(f)
        except (OSError, ValueError):
            self.drops = {}

    def _save(self):
        if os.environ.get("MUDPILOT_NO_RECORD") and not os.environ.get("MUDPILOT_DROPS_SAVE"):
            return                                    # tests never write the board's files
        try:
            os.makedirs(os.path.dirname(self.file), exist_ok=True)
            tmp = self.file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.drops, f, indent=0)
            os.replace(tmp, self.file)
        except OSError:
            pass

    def reset(self):
        self.mobs.clear()
        self.spells.clear()
        self.rounds.clear()
        self._round = None
        self.reset_t = time.time()

    # ------------------------------------------------------------------ lines
    def _mob(self, name):
        key = _base(name)
        rec = self.s.world.identify_monster(key) if getattr(self.s.world, "loaded", True) else None
        if rec:
            key = rec["name"].lower()
        return self.mobs.setdefault(key, {"hits": 0, "misses": 0, "crits": 0, "bs": 0, "dmg": 0, "min": None,
                                          "max": 0, "spell_hits": 0, "spell_dmg": 0, "taken_hits": 0,
                                          "taken_miss": 0, "taken": 0, "taken_max": 0, "kills": 0, "rounds": 0,
                                          "round_dmg": 0})

    def _tick_round(self, mon, done=0, taken=0):
        now = time.time()
        st = self.s.state
        r = self._round
        if r is None or now - r["last"] > ROUND_GAP:
            if r is not None:
                self._close_round()
            r = self._round = {"t": now, "last": now, "mon": mon, "done": 0, "taken": 0, "hp0": st.hp, "hp1": st.hp}
        r["last"] = now
        r["done"] += done
        r["taken"] += taken
        r["hp1"] = st.hp
        if mon and not r.get("mon"):
            r["mon"] = mon

    def _close_round(self):
        r = self._round
        self._round = None
        if not r:
            return
        self.rounds.append(r)
        if r.get("mon") and r["done"]:
            m = self._mob(r["mon"])
            m["rounds"] += 1
            m["round_dmg"] += r["done"]

    def feed_line(self, text: str):
        t = (text or "").strip()
        if not t or t.startswith("["):
            return
        st = self.s.state
        m = MY_SPELL_RE.match(t)
        if m:
            sp, mon, dmg = m.group(1).lower(), m.group(2), int(m.group(3))
            d = self.spells.setdefault(sp, {"hits": 0, "dmg": 0, "min": None, "max": 0, "casts": 0})
            d["hits"] += 1
            d["dmg"] += dmg
            d["min"] = dmg if d["min"] is None else min(d["min"], dmg)
            d["max"] = max(d["max"], dmg)
            mm = self._mob(mon)
            mm["spell_hits"] += 1
            mm["spell_dmg"] += dmg
            self._tick_round(_base(mon), done=dmg)
            return
        m = MY_HIT_RE.match(t)
        if m and not t.lower().startswith(("you gain", "you lose", "you cast")):
            mon, dmg = m.group(3), int(m.group(4))
            mm = self._mob(mon)
            mm["hits"] += 1
            mm["dmg"] += dmg
            mm["min"] = dmg if mm["min"] is None else min(mm["min"], dmg)
            mm["max"] = max(mm["max"], dmg)
            kind = (m.group(1) or "").strip().lower()
            if kind == "critically":
                mm["crits"] += 1
            elif kind == "surprise":
                mm["bs"] += 1
            self._tick_round(_base(mon), done=dmg)
            return
        m = MY_MISS_RE.match(t)
        if m and "damage" not in t.lower():
            self._mob(m.group(1))["misses"] += 1
            self._tick_round(_base(m.group(1)))
            return
        ms = MON_SPELL_RE.match(t)
        m = MON_HIT_RE.match(t) if not ms else None
        if ms or m:
            mm = self._mob((ms or m).group(1))
            dmg = int(ms.group(3) if ms else m.group(2))
            mm["taken_hits"] += 1
            mm["taken"] += dmg
            mm["taken_max"] = max(mm["taken_max"], dmg)
            self._tick_round(None, taken=dmg)
            return
        m = MON_MISS_RE.match(t)
        if m and "damage" not in t.lower():
            self._mob(m.group(1))["taken_miss"] += 1
            self._tick_round(None)
            return
        if "*combat off*" in t.lower():
            self._close_round()
        self._items_line(t)

    def note_cast(self, spell_name):
        d = self.spells.setdefault((spell_name or "").lower(), {"hits": 0, "dmg": 0, "min": None, "max": 0, "casts": 0})
        d["casts"] += 1

    # ------------------------------------------------------------------ kills / drops
    def on_exp(self, n):
        if n <= 0:
            return
        st = self.s.state
        name = getattr(st, "last_kill_name", None) or (self._round or {}).get("mon")
        if not name and st.view and st.view.monsters:
            sh, rec = st.view.monsters[0]
            name = rec["name"] if rec else sh
        if not name:
            return
        name = _base(name)
        rec = self.s.world.identify_monster(name)
        if rec:
            name = rec["name"].lower()
        self._mob(name)["kills"] += 1
        self._load()
        d = self.drops.setdefault(name, {"kills": 0, "items": {}})
        d["kills"] += 1
        before = Counter()
        for q, it in (st.view.items if st.view else []):
            before[it.lower()] += q
        self._pending_drop = {"mon": name, "t": time.time(), "room": st.room, "before": before}

    def on_room(self, state):
        pd = self._pending_drop
        if not pd:
            return
        if time.time() - pd["t"] > 10 or (pd["room"] and state.room and state.room != pd["room"]):
            self._pending_drop = None
            return
        now_items = Counter()
        for q, it in (state.view.items if state.view else []):
            now_items[it.lower()] += q
        new = now_items - pd["before"]
        if not new:
            return
        d = self.drops.setdefault(pd["mon"], {"kills": 0, "items": {}})
        for it, q in new.items():
            e = d["items"].setdefault(it, [0, 0])
            e[0] += q
            e[1] = time.time()
        pd["before"] = now_items
        self._save()

    def mme_drops(self, rec) -> list:
        """MME's drop list for a monster: [(item name, pct)] (from each item's 'Obtained From')."""
        w = self.s.world
        idx = getattr(w, "_drop_index", None)
        if idx is None:
            idx = {}
            for num, g in (getattr(w, "gear", None) or {}).items():
                for mm in re.finditer(r"Monster #(\d+)(?:\(([\d.]+)%\))?", g.get("obtained") or ""):
                    idx.setdefault(int(mm.group(1)), []).append((w.item_name(num), float(mm.group(2) or 0)))
            w._drop_index = idx
        return sorted(idx.get(int(rec["num"]), []), key=lambda x: -x[1]) if rec else []

    def seen_drops(self, name) -> tuple[int, dict]:
        self._load()
        d = self.drops.get((name or "").lower()) or {}
        return d.get("kills", 0), d.get("items", {})

    # ------------------------------------------------------------------ item history
    def _items_line(self, t):
        st = self.s.state
        room = st.room
        m = GOT_RE.match(t)
        if m and not t.lower().startswith(("you get the feeling", "you get a sense")):
            it = m.group(2)
            self.items.append((time.time(), "got", int(m.group(1) or 1), it, room, ""))
            return
        m = LOST_RE.match(t)
        if m:
            verb = m.group(1).lower()
            if verb == "put" and not m.group(4):
                return                                # 'You put on the ring' — wearing, not putting it away
            what = {"dropped": "dropped", "drop": "dropped", "gave": "gave", "give": "gave", "sold": "sold",
                    "sell": "sold", "hid": "stashed", "hide": "stashed", "put": "put", "deposited": "deposited",
                    "deposit": "deposited"}[verb]
            it = m.group(3)
            self.items.append((time.time(), what, int(m.group(2) or 1), it, room, m.group(4) or ""))

    def stashed(self) -> dict:
        """Coins left on the floor or hidden this session (stash runs), by kind, and their copper value."""
        from .gamestate import COIN_VALUE
        out = {}
        for _t, what, q, it, _room, _note in self.items:
            if what not in ("dropped", "stashed"):
                continue
            low = it.lower()
            for kind in COIN_VALUE:
                if kind.split()[0] in low:
                    out[kind] = out.get(kind, 0) + q
        return out
