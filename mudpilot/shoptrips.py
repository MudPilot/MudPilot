"""Bank and shop trips: deposit cash, sell loot, restock supplies — then back to the loop.

Like pMUD's Auto Deposit / Auto Sell / Auto Buy. Checked at the end of each lap (never mid-fight):
  * Deposit: carrying at least N copper worth → walk to the bank (yours, or the nearest one MME
    knows), deposit, come back.
  * Sell: carrying something on the sell list → the nearest shop that trades in it, sell, back.
  * Buy: fewer than "keep" of a supply (potions, scrolls, light sources…) → the nearest shop that
    sells it, buy up to "up to", back.
One trip per lap; each trip has a step limit so it never wanders across the realm.
"""
from __future__ import annotations

import re
import time

from .gamestate import parse_item_list

STEP_GAP = 1.3          # seconds between commands at the counter


def buy_rules(text: str) -> list:
    """'healing potion 3-10; torch 2-5' → [('healing potion', 3, 10), ('torch', 2, 5)]."""
    out = []
    for part in re.split(r"[;\n]", text or ""):
        m = re.match(r"^\s*(.+?)\s+(\d+)\s*-\s*(\d+)\s*$", part)
        if m:
            out.append((m.group(1).strip(), int(m.group(2)), max(int(m.group(2)), int(m.group(3)))))
    return out


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


class ShopTrips:
    def __init__(self, session):
        self.s = session
        self.trip = None          # {"kind", "room", "cmds", "back", "t", "phase", "next_at", "why"}

    # ------------------------------------------------------------ where
    def banks(self) -> list:
        # MME ShopType 7 is a bank (older imports: go by the name)
        return [tuple(r) for sh in self.s.world.shops.values()
                if sh.get("type") == 7 or "bank" in (sh.get("name") or "").lower()
                for r in sh.get("rooms") or []]

    def bank_choices(self) -> list:
        """[(friendly name, (map, room))] for the bank dropdown: the room's own name ('Bank of Arlysia'), with the
        town the shop is named for when the room doesn't say it ('Bank of Delanon (Shadowmere)')."""
        w, out = self.s.world, []
        for sh in w.shops.values():
            name = (sh.get("name") or "").strip()
            if not (sh.get("type") == 7 or "bank" in name.lower()):
                continue
            town = " ".join(re.sub(r"(?i)\b(bank|of|the)\b", " ", name).split())
            for r in sh.get("rooms") or []:
                rm = w.room(tuple(r))
                label = (getattr(rm, "name", "") or "").strip()
                if not label or label.lower() == "bank":
                    label = name or f"Bank {r[0]}/{r[1]}"
                elif town and town.lower() not in label.lower():
                    label = f"{label} ({town})"
                out.append((label, (int(r[0]), int(r[1]))))
        return sorted(dict.fromkeys(out), key=lambda x: x[0].lower())

    def shop_ok(self, sh) -> bool:
        """A guild shop only serves its class; a shop MME marks not in game is skipped."""
        if not sh or sh.get("in_game") == 0:
            return False
        cls = int(sh.get("class") or 0)
        if cls:
            mine = (self.s.world.char or {}).get("class") if getattr(self.s.world, "char", None) else None
            if mine is not None and int(mine) != cls:
                return False
        return True

    def shops_for(self, item: str) -> list:
        """Rooms of shops MME says sell this item (they buy it too)."""
        w, n = self.s.world, _norm(item)
        rooms = []
        for src in (getattr(w, "gear", None) or {}, getattr(w, "items", None) or {}):
            for g in src.values():
                if _norm((g or {}).get("name")) != n:
                    continue
                for num in re.findall(r"Shop #(\d+)", (g or {}).get("obtained", "") or ""):
                    if not self.shop_ok(w.shops.get(int(num))):
                        continue
                    for r in (w.shops.get(int(num)) or {}).get("rooms") or []:
                        rooms.append(tuple(r))
        return list(dict.fromkeys(rooms))

    COPPER = (1, 10, 100, 10000, 1000000)         # copper, silver, gold, platinum, runic

    def price(self, num, markup=0) -> int:
        """What a shop asks for item #num, in copper: MME's price plus the shop's markup, then the Charm discount
        (MudPlay's formula: base + Fix(base*Markup/100), then ×(1 − (Fix(Charm/5) − 10)/100))."""
        it = (getattr(self.s.world, "items", None) or {}).get(int(num)) or {}
        base = int(it.get("price") or 0) * self.COPPER[min(max(int(it.get("currency") or 0), 0), 4)]
        p = base + int(base * int(markup or 0) / 100)
        charm = int(getattr(self.s.state, "charm", 0) or 0)
        if charm:
            p = int(p * (1 - ((charm // 5) - 10) / 100))
        return max(p, 0)

    def stocked_at(self, num) -> list:
        """[(room, shop number, price)] of shops whose stock slots hold item #num (0.8.200, from the MudPlay
        review: the shop's own stock list beats the item's 'Obtained From' text). A slot that never restocks
        (Max or % of 0) doesn't count, nor does a guild shop for another class. Older imports without stock
        lists fall back to 'Obtained From'."""
        w, out = self.s.world, []
        any_stock = False
        for sn, sh in (getattr(w, "shops", None) or {}).items():
            stock = sh.get("stock")
            if stock is None:
                continue
            any_stock = True
            if not self.shop_ok(sh):
                continue
            for slot in stock:
                if int(slot[0]) != int(num):
                    continue
                mx, pct = (int(slot[1]), int(slot[4])) if len(slot) > 4 else (1, 1)
                if mx <= 0 or pct <= 0:
                    continue
                for r in sh.get("rooms") or []:
                    out.append((tuple(r), sn, self.price(num, sh.get("markup"))))
                break
        if not any_stock:
            name = (getattr(self.s.world, "items", None) or {}).get(int(num), {}).get("name")
            out = [(r, 0, self.price(num)) for r in self.shops_for(name or "")]
        return list(dict.fromkeys(out))

    def _nearest(self, rooms, limit):
        b, here = self.s.bot, self.s.state.room
        if not here:
            return None, None
        best = None
        for r in rooms:
            rt = b.plan_route(here, r) if r != here else []
            if rt is None or len(rt) > limit:
                continue
            if best is None or len(rt) < best[1]:
                best = (r, len(rt))
        return best if best else (None, None)

    # ------------------------------------------------------------ what's needed
    def carried(self) -> dict:
        """What's in your pack, by name. Worn gear doesn't count (0.8.201, bug hunt: a worn "platinum ring"
        counted toward 'sell' above keep 1, so the equipped one went up for sale too)."""
        from .gamestate import WORN_PART_RE
        out = {}
        for qty, name in parse_item_list(self.s.state.carrying or ""):
            if WORN_PART_RE.match(name.strip()):
                continue
            name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
            out[_norm(name)] = out.get(_norm(name), 0) + qty
        return out

    FAIL_COOLDOWN = 1800      # a buy / sell / deposit that changed nothing: not again for 30 minutes

    def failed_lately(self, kind, item) -> bool:
        t = (getattr(self, "_failed", None) or {}).get((kind, _norm(item)))
        return bool(t) and time.time() - t < self.FAIL_COOLDOWN

    def price_of(self, item) -> int:
        """Cheapest price of one `item` in copper (0 = unknown)."""
        n = _norm(item)
        num = next((k for k, it in ((getattr(self.s.world, "items", None) or {}).items())
                    if _norm((it or {}).get("name")) == n), None)
        if num is None:
            return 0
        try:
            return min((p for _r, _s, p in self.stocked_at(num) if p), default=0) or self.price(num)
        except Exception:
            return 0

    def _note_result(self, t):
        """0.8.201, bug hunt: out of cash, out of stock, or the shop won't take it — the trip changed nothing, and
        the next lap went straight back for the same thing, forever. Remember it for FAIL_COOLDOWN."""
        if not t.get("checked") or t.get("kind") not in ("buy", "sell", "deposit"):
            return
        st, now = self.s.state, time.time()
        failed = self._failed = {k: v for k, v in (getattr(self, "_failed", None) or {}).items()
                                 if now - v < self.FAIL_COOLDOWN}
        if t["kind"] == "deposit":
            if st.wealth is not None and st.wealth >= (t.get("wealth0") or 0) > 0:
                failed[("deposit", "")] = now
                self.s.log("Trip: the deposit didn't take — not trying again for 30 minutes")
            return
        have, before = self.carried(), t.get("have0") or {}
        for c in t.get("items") or []:
            k = _norm(c)
            if have.get(k, 0) == before.get(k, 0):
                failed[(t["kind"], k)] = now
                self.s.log(f"Trip: couldn't {t['kind']} the {c} — not trying again for 30 minutes")

    def next_trip(self):
        """(kind, room, [commands], why) or None."""
        cfg, st = self.s.settings, self.s.state
        lim = int(cfg.trip_max_steps or 60)
        if cfg.auto_deposit_on and st.wealth and st.wealth >= int(cfg.deposit_at_copper or 0) > 0 \
                and not self.failed_lately("deposit", ""):
            bank = tuple(int(x) for x in cfg.bank_room.split("/")) if re.match(r"^\d+/\d+$", cfg.bank_room or "") else None
            room, n = (bank, 0) if bank else self._nearest(self.banks(), lim)
            if room:
                cmd = (cfg.deposit_cmd or "deposit {copper}").replace("{copper}", str(st.wealth))
                return "deposit", room, [cmd], f"carrying {st.wealth:,} copper worth"
        have = self.carried()
        if cfg.auto_sell_on:
            # 0.8.201 (Dan): with Drop cheap loot on, what a shop pays next to nothing for isn't worth the walk, and
            # the valuable things chests gave (chestloot.py) go along — never more than the chests gave
            cl = getattr(self.s, "chestloot", None)
            chest = cl.to_sell(have) if cl is not None else {}
            cheap = lambda i: bool(cfg.loot_drop_cheap and cl is not None and cl.value(i) is not None
                                   and not cl.worth_selling(i))
            sell = [i for i in (cfg.auto_sell_items or []) if have.get(_norm(i))
                    and have.get(_norm(i)) > int(self.s.bot.item_rule(i).get("keep") or 0)
                    and not self.failed_lately("sell", i) and not cheap(i)]
            listed = {_norm(i) for i in sell}
            sell += [k for k in chest if k not in listed and not self.failed_lately("sell", k)]
            for item in sell:
                room, _n = self._nearest(self.shops_for(item), lim)
                if room:
                    group = [i for i in sell if room in self.shops_for(i)]
                    cmds = []
                    for i in group:
                        n = (have.get(_norm(i), 1) - int(self.s.bot.item_rule(i).get("keep") or 0)
                             if _norm(i) in listed else chest.get(_norm(i), 0))
                        cmds += [f"sell {i}"] * max(n, 0)
                    return "sell", room, cmds[:40], "selling " + ", ".join(group)
        if cfg.auto_buy_on:
            for item, keep, upto in buy_rules(cfg.auto_buy):
                if not item or have.get(_norm(item), 0) >= keep or self.failed_lately("buy", item):
                    continue
                p = self.price_of(item)
                if p and st.wealth is not None and st.wealth < p:
                    continue                          # can't afford even one: not a walk there and back every lap
                room, _n = self._nearest(self.shops_for(item), lim)
                if room:
                    n = max(1, upto - have.get(_norm(item), 0))
                    return "buy", room, [f"buy {item}"] * min(n, 20), f"only {have.get(_norm(item), 0)} {item} left"
        return None

    def withdraw_for(self, mp, loop, short, why="the toll", after=None) -> bool:
        """pMUD: short of a toll (or a boat fare) → the nearest bank, withdraw what's missing (plus a little),
        then on with the path. Once per path per 10 minutes, so an empty account can't loop.
        after: called instead of going back to the path (0.8.200: auto-train's fee — back to the trainer, not the
        loop; it doesn't need the toll setting, it's part of auto-train)."""
        cfg = self.s.settings
        if self.trip or (not cfg.toll_bank_run and after is None):
            return False
        key = getattr(mp, "title", "") if after is None else f"training:{getattr(mp, 'title', '')}"
        last = getattr(self, "_withdrew", {})
        if time.time() - last.get(key, 0) < 600:
            return False
        room, _n = self._nearest(self.banks(), int(cfg.trip_max_steps or 60) * 2)
        if not room:
            return False
        amt = int(short * 1.1) + 100
        self._withdrew = {**last, key: time.time()}
        cmd = (cfg.withdraw_cmd or "withdraw {copper}").replace("{copper}", str(amt))
        self.trip = {"kind": "withdraw", "room": room, "cmds": [cmd], "back": (mp, loop), "t": time.time(),
                     "phase": "going", "next_at": 0, "why": f"{short:,} copper short for {why}", "after": after}
        r = self.s.world.room(room)
        self.s.log(f"Trip: {short:,} copper short for {why} on {key} — to the bank at "
                   f"{r.name if r else ''} ({room[0]}/{room[1]}) first")
        if self.s.state.room == room:
            self.trip["phase"] = "doing"
            return True
        if not self.s.bot.goto(room):
            self.trip = None
            return False
        return True

    # ------------------------------------------------------------ running
    def lap_end(self, mp) -> bool:
        """End of a lap on a loop: go on a trip if one is due. True = we're off."""
        if self.trip or not (self.s.settings.auto_deposit_on or self.s.settings.auto_sell_on or self.s.settings.auto_buy_on):
            return False
        t = self.next_trip()
        if not t:
            return False
        kind, room, cmds, why = t
        return self.start_trip(mp, kind, room, cmds, why)

    def start_trip(self, mp, kind, room, cmds, why) -> bool:
        """Off to `room`, send `cmds` there, read the pack, back to the loop `mp`. Also how auto-light buys its
        lights (0.8.200). True = we're off."""
        if self.trip:
            return False
        b = self.s.bot
        self.trip = {"kind": kind, "room": room, "cmds": list(cmds), "back": (mp, True), "t": time.time(),
                     "phase": "going", "next_at": 0, "why": why,
                     # what to compare after the closing 'i' (a trip that changed nothing goes on a cooldown)
                     "items": list(dict.fromkeys(c.split(" ", 1)[1] for c in cmds
                                                 if c.startswith(("buy ", "sell ")) and " " in c)),
                     "have0": self.carried(), "wealth0": self.s.state.wealth}
        r = self.s.world.room(room)
        self.s.log(f"Trip: {kind} at {r.name if r else ''} ({room[0]}/{room[1]}) — {why}; back to {mp.title} after")
        if self.s.state.room == room:
            self.trip["phase"] = "doing"
            b.walking = False
            return True
        if not b.goto(room):
            self.s.log("Trip: no route — carrying on with the loop")
            self.trip = None
            return False
        return True

    def tick(self):
        t = self.trip
        if not t:
            return
        s, b, st = self.s, self.s.bot, self.s.state
        now = time.time()
        if not s.telnet.connected or st.dead:
            self.trip = None
            return
        if st.in_combat or st.resting:
            return
        if t["phase"] == "going":
            if st.room == t["room"] and not b.walking:
                t["phase"], t["next_at"] = "doing", now + 1.0
            elif not b.walking and now - t["t"] > 5:
                if str(b.status).startswith(("Stopped by you", "Hung up")):
                    s.log("Trip: cancelled (you stopped it)")
                    self.trip = None
                elif now - t["t"] > 30:
                    self._back("the walk there stopped")
            elif now - t["t"] > 900:
                self._back("took too long")
            return
        if t["phase"] == "doing" and now >= t["next_at"]:
            if t["cmds"]:
                s.send(t["cmds"].pop(0), from_bot=True)
                t["next_at"] = now + STEP_GAP
            elif not t.get("checked"):
                t["checked"] = True                   # see what you're carrying now (cash for the toll)
                s.send("i", from_bot=True)
                t["next_at"] = now + 2.5
            else:
                self._back(f"{t['kind']} done")

    def _back(self, why):
        t, self.trip = self.trip, None
        try:
            self._note_result(t)
        except Exception:
            pass
        mp, loop = t["back"]
        if t.get("after"):
            self.s.log(f"Trip: {why}")
            t["after"]()                               # (auto-train: back to the trainer)
            return
        self.s.log(f"Trip: {why} — back to {mp.title}")
        if t.get("goto"):
            self.s.bot.goto_bg(t["goto"], then=t.get("then"))   # cash for an item: plan it again — the item check buys it
            return
        self.s.bot.start_path(mp, loop=loop, checked=not t.get("recheck"))

    def reset(self, why=""):
        self.trip = None
