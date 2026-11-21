"""Put your gear back on after recovering your corpse.

PVE, 2026-10-29: died, came back, walked over its corpse and 'recover corpse' put everything in the pack —
headdress (poison immunity), robes, gloves, rings, the vortex staff — and nothing was worn again: it walked on and
fought unarmoured, and the poison the headdress negates landed. MudPilot remembers what you had on (cfg.last_worn,
saved, so it survives a restart) and puts back on whatever of it is in your pack but not worn:
  • after "You have recovered the corpse of …";
  • on the first inventory after logging in, when you're wearing a lot less than you were (3+ pieces short) —
    small differences are regen-gear swaps and are left alone."""
from __future__ import annotations

import re
import time
from collections import Counter

from .gamestate import worn_list

RECOVERED_RE = re.compile(r"^You have recovered the corpse of ", re.I)
PICKING_RE = re.compile(r"^You begin to pick through the corpse of ", re.I)
TOOK_RE = re.compile(r"^You took (?:an? |the |some )?(.+?)\.?$", re.I)
SMALL_COINS = re.compile(r"\b(copper farthings?|silver nobles?)\b", re.I)   # left on the floor; the rest is yours
GRAB_MAX = 30


def _carried(carrying: str) -> set:
    out = set()
    for part in re.split(r",\s*", carrying or ""):
        p = re.sub(r"\s*\([^)]*\)\s*$", "", part.strip().rstrip(".")).strip().lower()
        p = re.sub(r"^\d+\s+", "", p)
        if p:
            out.add(p)
    return out


def _pack_counts(carrying: str) -> Counter:
    """How many of each item are in the pack (not worn): "2 platinum ring, platinum ring (Finger)" → 2."""
    out = Counter()
    for part in re.split(r",\s*", carrying or ""):
        p = part.strip().rstrip(".")
        if not p or re.search(r"\([A-Z][A-Za-z -]{1,18}\)\s*$", p):
            continue
        m = re.match(r"^(\d+)\s+(.+)$", p)
        q, nm = (int(m.group(1)), m.group(2)) if m else (1, re.sub(r"^(?:an?|the|some)\s+", "", p, flags=re.I))
        out[nm.strip().lower()] += q
    return out


class Redress:
    def __init__(self, bot):
        self.b = bot
        self.want_at = 0.0           # an inventory read after this → check
        self.seq = -1
        self.force = False           # after a corpse recovery: put back whatever's missing
        self.login_checked = False
        self.login_checked_swap = False
        self._saved_at = 0.0
        self.grab = None             # after a corpse recovery: (asked at, view_seq) — pick up the floor first
        self.taking = None           # what came out of the corpse ("You took …"), while recovering
        self.from_corpse: list = []

    def note_line(self, text):
        t = text.strip()
        if PICKING_RE.match(t):
            self.taking = []
            return
        mt = TOOK_RE.match(t) if self.taking is not None else None
        if mt:
            self.taking.append(mt.group(1).strip())
            return
        if RECOVERED_RE.match(t):
            self.from_corpse, self.taking = list(self.taking or []), None
            # Dan, 2026-10-30: on PvP some of it lands outside the corpse every time — nearly everything on the
            # floor of the corpse room is yours. Look, pick it all up (not copper / silver), then dress
            self.grab = (time.time(), self.b.st.view_seq)
            self.b.send("")

    def _grab_floor(self):
        """Everything on the floor but small coins: 'get' each (several of one thing: that many times)."""
        v = self.b.st.view
        got = []
        for qty, name in (v.items if v else []):
            nm = (name or "").strip()
            low = nm.lower()
            if not nm or SMALL_COINS.search(low):
                continue
            coins = re.search(r"\b(crowns?|platinum|runic|coins?)\b", low)
            if coins:
                self.b.send(f"get {qty} {nm}" if qty and qty > 1 else f"get {nm}")
                got.append(nm)
                continue
            for _ in range(min(max(int(qty or 1), 1), 10)):
                if len(got) >= GRAB_MAX:
                    break
                self.b.send(f"get {nm}")
                got.append(nm)
        if got:
            self.b.log(f"Corpse recovered — picking up what fell out: {', '.join(dict.fromkeys(got))}")

    def tick(self):
        st, cfg = self.b.st, self.b.cfg
        g = self.grab
        if g and (st.view_seq > g[1] or time.time() - g[0] > 4):
            self.grab = None
            self._grab_floor()
            self.want_at, self.force = time.time(), True     # then read the pack and dress
            self.seq = st.inv_seq
            self.b.send("i")
            return True
        if st.dead or not st.carrying:
            return False
        worn = worn_list(st.carrying)
        last = list(getattr(cfg, "last_worn", None) or [])
        if not self.login_checked and st.inv_seq > 0:
            self.login_checked = True
            if last and len(worn) <= len(last) - 3:
                self.want_at, self.force, self.seq = time.time(), True, st.inv_seq - 1
        if self.want_at and st.inv_seq > self.seq:
            self.want_at = 0
            if self.force:
                self.force = False
                return self._put_back(worn, last)
        if not self.login_checked_swap and st.inv_seq > 0:
            self.login_checked_swap = True
            self._replay_swap()
        # remember what you're wearing (fully dressed: 5+ pieces), saved now and then
        # 0.8.201, bug hunt: not in the regen set (a rest swap is on, or resting) — a death or restart mid-rest then
        # "redressed" the faded shawl for good; and not a strict part of what's remembered — a partial redress (4
        # pieces wouldn't go on) overwrote the full set, and the rest never came back
        swapping = bool(getattr(self.b, "_swap", None)) or bool(getattr(st, "resting", False))
        if len(worn) >= 5 and not self.want_at and not swapping:
            names = [n for n, _s in worn]
            lc, nc = Counter(n.lower() for n in last), Counter(n.lower() for n in names)
            subset = bool(last) and nc != lc and not (nc - lc)
            if names != last and not subset and time.time() - self._saved_at > 30:
                cfg.last_worn = names
                self._saved_at = time.time()
                try:
                    cfg.save()
                except Exception:
                    pass
        return False

    def _replay_swap(self):
        """0.8.201, bug hunt: MudPilot restarted (or relogged) while the regen set was on — the 'put the fighting
        gear back' commands only lived in memory, so the faded shawl stayed on and became the 'fighting set'. They're
        saved with the settings while a swap is on (cfg.swap_owed); the first inventory after logging in sends them."""
        cfg = self.b.cfg
        owed = list(getattr(cfg, "swap_owed", None) or [])
        if not owed or getattr(self.b, "_swap", None):
            return False
        cfg.swap_owed = []
        try:
            cfg.save()
        except Exception:
            pass
        self.b.log("Fighting gear back on (a rest swap was still on when MudPilot last stopped): " +
                   ", ".join(c[3:] for c in owed if c.startswith("eq ")))
        for c in owed[:20]:
            self.b.send(c)
        self.b.send("i")
        return True

    def _put_back(self, worn, last):
        have = _carried(self.b.st.carrying)
        on = {n.lower() for n, _s in worn}
        # 0.8.201, bug hunt: by count — two "platinum ring"s remembered, one worn and one in the pack: the second
        # goes back on too ('not in on' left it in the pack)
        owed = Counter(n.lower() for n in last) - Counter(n.lower() for n, _s in worn)
        packed = _pack_counts(self.b.st.carrying)
        missing = []
        for n in last:
            k = n.lower()
            if owed[k] > 0 and packed[k] > 0:
                owed[k] -= 1
                packed[k] -= 1
                missing.append(n)
        if not last:
            # Revolution, 2026-10-30: nothing remembered yet (he hadn't checked his inventory dressed since the
            # update) — corpse gear sat in the pack for hours. Wear the armour that came out of the corpse
            missing = self._corpse_armour(have, on)
        self.from_corpse = []
        if not missing:
            return False
        self.b.log(f"Putting your gear back on: {', '.join(missing)}")
        for n in missing[:20]:
            self.b.send(f"eq {n}")
        self.b.send("i")
        return True

    def _corpse_armour(self, have, on):
        """Armour (not weapons) taken out of your corpse that you can wear and aren't wearing."""
        gw = getattr(getattr(self.b, "s", None), "gearwatch", None)
        if gw is None:
            return []
        from . import gearcalc as G
        names, out = gw._gear_by_name(), []
        for n in dict.fromkeys(self.from_corpse):
            g = names.get(n.lower())
            if not g or n.lower() not in have or n.lower() in on:
                continue
            if int(g.get("ItemType") or 0) == 1 or int(g.get("Worn") or 0) <= 0:
                continue                                  # weapons stay as they are
            try:
                if not G.usable(self.b.s.world, g, gw.char())[0]:
                    continue
            except Exception:
                pass
            out.append(n)
        return out
