"""Gear upgrade watch: spots armour better than what you're wearing.

Whenever a room shows items, or you pick something up, each piece of armour MME knows is
checked with the inventory calculator's rules (class, race, level, strength, alignment) and
scored for your goal (Settings → Loot: AC by default) against what you wear in that slot
(the weaker ring/wrist for those). Better by at least the minimum gain →
  * an alert, once per item per session, saying what, where, and by how much;
  * optionally pick it up (if it's lying here), and optionally wear it once it's in your pack.
Weapons are never picked up or wielded — changing weapons changes how the bot fights. Since 0.8.201 they're
alerted on, though (Settings → Loot → "…and weapons", gear_watch_weapons): average damage per round with your
level, agility, strength and encumbrance (MME's attack formula, gearcalc.weapon_round) against what you wield,
at least 10% (and 1) better. Shop lists ('list' in a shop) are checked too, and an alert also goes to your phone
when the "Gear upgrade" ntfy alert is ticked.
"""
from __future__ import annotations

import re
import time

from . import gearcalc as G

PICKUP_RE = re.compile(r"^You (?:picked up|took|get|pick up) (?:an? |the |some |\d+ )?(.+?)\.?$", re.I)
WEAPON_MIN_PCT = 10
PROMPT_RE = re.compile(r"^\s*\[[^\]]*\]:?")
SHOP_LIST_SECS = 5.0


class GearWatch:
    def __init__(self, session):
        self.s = session
        self._names = None
        self._for = None
        self.told: dict = {}            # item name -> time we said so
        self.pending_wear: list = []    # items to put on once they're in the pack

    def _gear_by_name(self):
        w = self.s.world
        if self._for is not w or self._names is None:
            self._names = {g["name"].lower(): g for g in (getattr(w, "gear", None) or {}).values()}
            self._for = w
        return self._names

    def char(self) -> G.Char:
        w, st, cfg = self.s.world, self.s.state, self.s.settings
        cname = (st.char_class or cfg.char_class or "").lower()
        rname = (st.race or "").lower()
        cls = next((k for k, v in w.classes.items() if v.get("Name", "").lower() == cname), 0)
        race = next((k for k, v in w.races.items() if v.get("Name", "").lower() == rname), 0)
        return G.Char(cls=cls, race=race, level=st.level or cfg.char_level or 0, align="Any",
                      strength=st.strength or 0, include_limited=True)

    def upgrade(self, name):
        """(gear, slot, gain, what it beats) if `name` is an upgrade for you, else None."""
        cfg, w = self.s.settings, self.s.world
        if not (self.s.state.carrying or "").strip():
            return None                    # haven't seen your inventory yet: every slot would look empty
        g = self._gear_by_name().get((name or "").strip().lower())
        if g and int(g.get("ItemType") or 0) == 1:
            return self.weapon_upgrade(g) if cfg.gear_watch_weapons else None
        if not g or int(g.get("Worn") or 0) <= 0:
            return None
        ok, _why = G.usable(w, g, self.char())
        if not ok:
            return None
        goal = G.GOALS.get(cfg.gear_goal) or "ac"
        slot = G.WORN_SLOT.get(int(g.get("Worn") or 0))
        worn = G.worn_items(w, self.s.state.carrying)
        here = [v for k, v in worn.items() if k.split(" ")[0] == slot]
        if any(v is g for v in here):
            return None                                       # already wearing it
        if slot in ("Finger", "Wrist") and len(here) < 2:
            cur = None                                        # a free ring / wrist slot
        else:
            cur = min(here, key=lambda v: G.score(v, goal)) if here else None
        gain = G.score(g, goal) - (G.score(cur, goal) if cur else 0)
        if gain < float(cfg.gear_min_gain or 0.1):
            return None
        return g, slot, gain, cur

    def fighter(self) -> G.Fighter:
        w, st, cfg = self.s.world, self.s.state, self.s.settings
        cname = (st.char_class or cfg.char_class or "").lower()
        c = next((c for c in w.classes.values() if c.get("Name", "").lower() == cname), {})
        return G.Fighter(level=st.level or cfg.char_level or 1, combat=max(int(c.get("CombatLVL") or 3) - 2, 0),
                         agility=st.agility or 50, strength=st.strength or 50,
                         encum_pct=int(st.enc[3]) if st.enc else 33)

    def weapon_upgrade(self, g):
        """(gear, "Weapon", gain per round, what you wield) when `g` hits harder than your weapon (0.8.201)."""
        from .gamestate import wielded
        w = self.s.world
        ch = self.char()
        ok, _why = G.usable(w, g, ch)
        if not ok:
            return None
        ok, _why = G.class_can_wield(w, g, ch.cls)
        if not ok:
            return None
        wn = (wielded(self.s.state.carrying or "") or "").strip().lower()
        cur = self._gear_by_name().get(wn) if wn else None
        if cur is g:
            return None
        f = self.fighter()
        try:
            new = G.weapon_round(g, f).round_dmg
            old = G.weapon_round(cur, f).round_dmg if cur else 0
        except Exception:
            return None
        gain = new - old
        if gain < max(1, old * WEAPON_MIN_PCT / 100):
            return None
        return g, "Weapon", float(gain), cur

    def _tell(self, name, up, where):
        now = time.time()
        if now - self.told.get(name.lower(), 0) < 3600:
            return False
        self.told[name.lower()] = now
        g, slot, gain, cur = up
        unit = "damage/round" if slot == "Weapon" else (self.s.settings.gear_goal or "AC").split(" (")[0]
        msg = (f"Upgrade {where}: {g['name']} ({slot}) — {unit} +{G.fmt(round(gain, 1))}"
               + (f" over your {cur['name']}" if cur else
                  " (nothing wielded)" if slot == "Weapon" else " (slot is empty)"))
        self.s.log(msg)
        self.s.on_alert(msg)
        try:
            self.s.notify.send("upgrade", msg)       # only when the "Gear upgrade" phone alert is ticked
        except Exception:
            pass
        return True

    def _shop_line(self, text) -> bool:
        """A shop's 'list' (0.8.201): each row it shows is checked like an item on the floor. True while the list
        is being read (the line is one of its rows)."""
        from .scrolls import LIST_HEAD_RE, parse_list
        t, now = (text or "").rstrip(), time.time()
        if LIST_HEAD_RE.match(t.strip()):
            self._shop = {"lines": [], "t": now, "done": set()}
            return True
        sh = getattr(self, "_shop", None)
        if not sh:
            return False
        if now - sh["t"] > SHOP_LIST_SECS or PROMPT_RE.match(t) or len(sh["lines"]) > 120:
            self._shop = None
            return False
        sh["lines"].append(t)
        names = {g["name"].lower(): g["name"] for g in self._gear_by_name().values()}
        for row in parse_list(sh["lines"]):
            name, _qty, price, cant, too = row
            if name.lower() in sh["done"] or cant or too:
                continue
            sh["done"].add(name.lower())
            full = names.get(name.lower()) or next(
                (n for k, n in names.items() if len(name) >= 28 and k.startswith(name.lower())), None)
            up = self.upgrade(full) if full else None
            if up:
                room = self.s.state.room
                self._tell(full, up, f"for sale{f' ({room[0]}/{room[1]})' if room else ''}, {price}")
        return True

    # ------------------------------------------------------------ hooks
    def on_room(self, state):
        cfg = self.s.settings
        if not cfg.gear_watch or not state.view or not state.view.items:
            return
        for _qty, name in state.view.items:
            up = self.upgrade(name)
            if not up:
                continue
            room = state.room
            self._tell(name, up, f"here{f' ({room[0]}/{room[1]})' if room else ''}")
            if up[1] == "Weapon":
                continue                                  # weapons: only said, never picked up or wielded
            if cfg.gear_grab_upgrades and not state.in_combat:
                self.s.send(cfg.get_item_cmd.format(item=name, qty=1) if "{" in cfg.get_item_cmd else f"get {name}",
                            from_bot=True)
                if cfg.gear_auto_wear:
                    self.pending_wear.append(name)

    def feed_line(self, text):
        cfg = self.s.settings
        if not cfg.gear_watch:
            return
        if self._shop_line(text):
            return
        m = PICKUP_RE.match(text.strip())
        if not m:
            return
        name = m.group(1).strip()
        up = self.upgrade(name)
        if not up:
            return
        self._tell(name, up, "picked up")
        if up[1] == "Weapon":
            return                                        # never wielded by itself
        if cfg.gear_auto_wear and name not in self.pending_wear:
            self.pending_wear.append(name)
        if cfg.gear_auto_wear and self.pending_wear:
            nm = self.pending_wear.pop(0)
            self.s.log(f"Wearing the upgrade: {nm}")
            self.s.send(f"wear {nm}", from_bot=True)
            self.s.send("i", from_bot=True)              # refresh what we wear
