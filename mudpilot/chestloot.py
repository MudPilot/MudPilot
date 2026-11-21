"""Chest loot: drop what isn't worth the trip, sell only what is (0.8.201, Dan: "lot of the stones sell in khaz but
most for 2-50 gold... not worth the trip we'll only bother selling high value items"). Settings → Loot → Bank and
shop trips → "Drop cheap loot". Off until you tick it.

What a shop pays for an item is worked out from MME's price (Items: Price + Currency) the way MudPlay does it
(ShopPriceCalculator.SellCopper): Paradigm pays half the base price, then ±1% per 5 Charm from 50; stock MajorMUD
pays (Charm/2 + 25)% of it. Anything worth less than the line (default 100 gold) is:
  * not picked up off the floor (loot), and
  * dropped straight away when a chest you open hands it to you (open <chest> → read the pack before and after;
    only what that open added counts — the MudPlay Chest Offload idea).
What's worth more is kept on a list (chest loot to sell) and goes on the Sell trip with the items you listed, once
"Sell these at the nearest shop…" is ticked — never more copies than the chests gave you.

Never dropped: anything with an item rule (Game Data → Items get / stash / keep / max), keys, containers, lights,
quest items (an exit needs it, an NPC trades for it, MME 'Not Droppable'), what an errand or a restock wants, gear you
wear, and anything whose value MME doesn't know (price 0 / not in MME)."""
from __future__ import annotations

import re
import time

KEY, LIGHT, CONTAINER = 7, 6, 8          # MME ItemType
PROTECTED_TYPES = (LIGHT, KEY, CONTAINER)
COPPER = (1, 10, 100, 10000, 1000000)    # copper, silver, gold, platinum, runic
OPEN_RE = re.compile(r"^\s*open\s+(.+?)\s*$", re.I)
SETTLE = 1.0                             # the loot spills a beat after the open, then 'i'
READ_GIVE_UP = 10.0


def _norm(s) -> str:
    s = re.sub(r"\s*\([^)]*\)\s*$", "", (s or "").strip().lower())
    return re.sub(r"\s+", " ", s)


def item_named(world, name):
    """MME's item row for a name — the one you can pick up when two share it ('oak chest' is a chest you carry and
    a room fixture)."""
    items = getattr(world, "items", None) or {}
    c = getattr(world, "_carry_names", None)
    if c is None or c[0] is not items:
        names = {}
        for it in items.values():
            k = (it.get("name") or "").lower()
            if k and (k not in names or (not names[k].get("gettable", 1) and it.get("gettable", 1))):
                names[k] = it
        c = world._carry_names = (items, names)
    n = _norm(name)
    return c[1].get(n) or c[1].get(n.rstrip("s"))


def sell_copper(base: int, charm: int, paradigm: bool) -> int:
    """What a shop pays for an item worth `base` copper (MudPlay's ShopPriceCalculator.SellCopper)."""
    c = float(base)
    if charm > 0:
        if paradigm:
            c /= 2.0
            c += (int((charm - 50) / 5) * c) / 100.0
        else:
            c = int((int(charm / 2) + 25) * c / 100.0)
    elif paradigm:
        c /= 2.0                             # Charm not read yet: Paradigm's flat half
    return max(int(round(c)), 0)


class ChestLoot:
    def __init__(self, session):
        self.s = session
        self.ledger: dict = {}               # item (lower) -> how many the chests gave that are worth selling
        self._open = None                    # {"before": counts, "t", "seq", "chest", "asked"}
        self._quest = None

    # ------------------------------------------------------------ values
    def _item(self, name):
        return item_named(self.s.world, name)

    def value(self, name):
        """Copper a shop pays for one `name`; None when MME doesn't know (not in MME, or no price)."""
        it = self._item(name)
        if not it or not int(it.get("price") or 0):
            return None
        base = int(it["price"]) * COPPER[min(max(int(it.get("currency") or 0), 0), 4)]
        try:
            from .board_fixes import is_paradigm
            para = is_paradigm(self.s.world)
        except Exception:
            para = False
        return sell_copper(base, int(getattr(self.s.state, "charm", 0) or 0), para)

    def threshold(self) -> int:
        return max(int(self.s.settings.loot_drop_below_gold or 0), 0) * 100

    def _quest_items(self) -> set:
        """Item numbers an exit needs (keys, rope and grapple, idols) or an NPC hands over / trades for."""
        w = self.s.world
        if self._quest is not None and self._quest[0] is w:
            return self._quest[1]
        out = set()
        try:
            for r in w.rooms.values():
                for ex in r.exits.values():
                    need = w.exit_need(ex)
                    if need:
                        out.add(int(need[0]))
        except Exception:
            pass
        for k in (getattr(w, "npc_gives", None) or {}):
            it = w.item_names.get(str(k).lower()) if not isinstance(k, int) else w.items.get(k)
            if it:
                out.add(int(it["num"]))
        self._quest = (w, out)
        return out

    def protected(self, name) -> str:
        """Why `name` must never be dropped by this feature ('' = it may be)."""
        b, cfg, st, w = self.s.bot, self.s.settings, self.s.state, self.s.world
        n = _norm(name)
        if b.item_rule(n):
            return "it has an item rule"
        it = self._item(n)
        if not it:
            return "MME doesn't know it"
        g = (getattr(w, "gear", None) or {}).get(int(it["num"])) or {}
        if int(g.get("ItemType") or -1) in PROTECTED_TYPES:
            return "a key, light or container"
        if int(g.get("Not Droppable") or 0):
            return "not droppable"
        if int(it["num"]) in self._quest_items():
            return "a quest item"
        try:
            if n in b.errands.wanted():
                return "an errand wants it"
        except Exception:
            pass
        try:
            from .shoptrips import buy_rules
            if any(_norm(i) == n for i, _k, _u in buy_rules(cfg.auto_buy or "")):
                return "on your restock list"
        except Exception:
            pass
        from .gamestate import worn_list
        if any(_norm(x) == n for x, _s in worn_list(st.carrying or "")):
            return "you wear it"
        return ""

    def cheap(self, name) -> bool:
        """Drop-cheap is on and `name` is worth less than the line (known value, nothing protecting it)."""
        if not self.s.settings.loot_drop_cheap:
            return False
        v = self.value(name)
        if v is None or v >= self.threshold():
            return False
        return not self.protected(name)

    def worth_selling(self, name) -> bool:
        v = self.value(name)
        return v is not None and v >= self.threshold()

    # ------------------------------------------------------------ chest opens
    def _counts(self) -> dict:
        from .gamestate import parse_item_list, WORN_PART_RE
        out = {}
        for q, nm in parse_item_list(self.s.state.carrying or ""):
            if WORN_PART_RE.match(nm.strip()):
                continue
            k = _norm(nm)
            out[k] = out.get(k, 0) + q
        return out

    def _containers(self) -> list:
        w = self.s.world
        out = []
        for k in self._counts():
            it = self._item(k)
            g = (getattr(w, "gear", None) or {}).get(int(it["num"])) if it else None
            if g and int(g.get("ItemType") or -1) == CONTAINER:
                out.append(k)
        return out

    def note_send(self, cmd):
        """Every command going out: 'open <a chest you carry>' starts a before/after read."""
        if not self.s.settings.loot_drop_cheap:
            return
        m = OPEN_RE.match(cmd or "")
        if not m or not (self.s.state.carrying or "").strip():
            return
        t = m.group(1).lower()
        hit = next((c for c in self._containers() if c == t or any(x.startswith(t) for x in c.split())), None)
        if not hit:
            return                               # a door, or a chest we don't hold
        if self._open:
            self._open["chest"] += f", {hit}"    # back to back: one diff covers both
            self._open["t"] = time.time()
            return
        self._open = {"before": self._counts(), "t": time.time(), "seq": self.s.state.inv_seq, "chest": hit,
                      "asked": 0.0}

    def tick(self):
        o = self._open
        if not o:
            return
        st, now = self.s.state, time.time()
        if not o["asked"]:
            if now - o["t"] >= SETTLE:
                o["asked"] = now
                o["seq"] = st.inv_seq
                self.s.send("i", from_bot=True)
            return
        if st.inv_seq == o["seq"]:
            if now - o["asked"] > READ_GIVE_UP:
                self._open = None                # no listing came back: what it gave isn't known — leave it
            return
        self._open = None
        after = self._counts()
        gains = [(k, n - o["before"].get(k, 0)) for k, n in after.items() if n > o["before"].get(k, 0)]
        self.handle_gains(o["chest"], gains)

    def handle_gains(self, chest, gains):
        """What a chest gave: cheap → drop now; worth selling → onto the sell list; the rest is left alone."""
        cfg = self.s.settings
        dropped, kept = [], []
        for k, n in gains:
            if self.cheap(k):
                self.s.send(cfg.drop_cmd.format(qty=n, item=k), from_bot=True)
                v = self.value(k) or 0
                dropped.append(f"{n} {k} ({v // 100}g)" if n > 1 else f"{k} ({v // 100}g)")
            elif self.worth_selling(k) and not self.protected(k):
                self.ledger[k] = self.ledger.get(k, 0) + n
                kept.append(f"{n} {k}" if n > 1 else k)
        if dropped:
            self.s.log(f"Chest loot ({chest}): dropped what isn't worth a trip — " + ", ".join(dropped))
        if kept:
            self.s.log(f"Chest loot ({chest}): keeping to sell — " + ", ".join(kept))
        return dropped, kept

    # ------------------------------------------------------------ the sell trip
    def to_sell(self, have: dict) -> dict:
        """{item: how many} the sell trip may sell: the chests' valuable loot still carried (never more than they
        gave — what you already owned stays)."""
        if not self.s.settings.loot_drop_cheap:
            return {}
        for k in list(self.ledger):
            left = min(self.ledger[k], have.get(k, 0))
            if left <= 0:
                del self.ledger[k]
            else:
                self.ledger[k] = left
        return {k: n for k, n in self.ledger.items() if not self.protected(k)}
