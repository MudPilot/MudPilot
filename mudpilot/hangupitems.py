"""Hang-up item pickup: on boards that drop items on a penalised hang-up, pick them back up after logging in.

(0.8.201, Dan: from MudPlay's hang-up item recheck.) Stock-type boards can be set (option #38 / #60) to drop up to
N items when you hang up in a fight. The game walks every other pack slot, then every other key-ring slot; worn
gear drops too, and it all lands on the floor of the room you were in. Next login says "Last time you were on, you
disconnected while playing." — and prints it even when nothing was taken. Paradigm never drops items (only HP).

What it does (Settings → PvP → "Hang-up item pickup", off unless you tick it and set how many items drop):
  • Snapshot: whenever MudPilot saves while you're in the game, after an 'i' on this connection — how many of each
    item you have (worn, carried, keys; no coins), the room, HP, lives, and whether a fight was on.
  • Back in the game: hold the walk, read 'i', work out what's missing, make sure we came back in the same room and
    can see it (not dark, not blind, no hostile monster), then 'get' each missing item, never more than the floor
    shows and never more in all than the board drops (a stale list once took like-named items that were never ours),
    put back on what was worn, and let the walk go. Once per connection.
  • Death first: a snapshot at a dropping / near-death HP means the hang-up's HP share may have killed us unseen.
    One life fewer and a different room → it's a death: recorded, and the gear left to death recovery.
"""
from __future__ import annotations

import json
import os
import re
import time

from .gamestate import parse_item_list, coin_kind, worn_list, LIVES_RE

HOLD = "hang-up items"
INV_WAIT = 4.0          # the login's own 'i' comes within a second or so; then we ask, and give that answer as long
STAT_WAIT = 3.0
ROOM_WAIT = 3.0         # a look answers within the second; a dark room never does
FIGHT_WAIT = 60.0
GET_SETTLE = 3.0        # quiet after the last 'You took' before the gets count as done
DRESS_WAIT = 5.0
NEAR_DEATH_PCT = 25     # a snapshot under this much HP: the hang-up's HP share could have killed us
TOOK_RE = re.compile(r"^You took (?!\d+ damage)", re.I)


def norm(name: str) -> str:
    n = re.sub(r"\s*\([^)]*\)\s*$", "", (name or "").strip().rstrip("."))
    n = re.sub(r"^(?:an?|the|some)\s+", "", n.strip(), flags=re.I)
    return re.sub(r"\s+", " ", n).lower()


def counts(carrying: str, keys: str = "") -> dict:
    """{item name: how many} over worn + carried + key ring (the lit light is in the carried list); no coins."""
    out: dict = {}
    for text in (carrying or "", keys or ""):
        for qty, name in parse_item_list(text) if text.strip() else []:
            n = norm(name)
            if not n or coin_kind(n) or n in ("nothing", "no keys"):
                continue
            out[n] = out.get(n, 0) + max(1, int(qty or 1))
    return out


def missing(before: dict, now: dict) -> dict:
    return {n: c - now.get(n, 0) for n, c in (before or {}).items() if c - now.get(n, 0) > 0}


def pickup_plan(short: dict, floor: list, cap: int) -> list:
    """[(name, n)]: each missing item up to what lies on the floor, and no more than `cap` in all."""
    lying: dict = {}
    for qty, name in floor or []:
        n = norm(name)
        if n:
            lying[n] = lying.get(n, 0) + max(1, int(qty or 1))
    plan, left = [], max(0, int(cap or 0))
    for name, n in short.items():
        take = min(n, lying.get(name, 0), left)
        if take <= 0:
            continue
        lying[name] -= take
        left -= take
        plan.append((name, take))
        if left <= 0:
            break
    return plan


class HangupItems:
    def __init__(self, session):
        self.s = session
        self.snap = None
        self.job = None
        self._conn = None
        self._inv0 = 0
        self._done_conn = None
        self._written = None
        self._said_paradigm = False
        self._load()

    # ------------------------------------------------------------ settings
    def paradigm(self) -> bool:
        from .lair_camp import realm_of
        return realm_of(self.s) == "paradigm"

    def enabled(self) -> bool:
        cfg = self.s.settings
        if not getattr(cfg, "hangup_items_drop", False) or int(getattr(cfg, "hangup_items_count", 0) or 0) <= 0:
            return False
        if self.paradigm():
            if not self._said_paradigm:
                self._said_paradigm = True
                self.s.log("Hang-up item pickup: Paradigm doesn't drop items on a hang-up (only HP) — not checking")
            return False
        return True

    def cap(self) -> int:
        return max(0, int(getattr(self.s.settings, "hangup_items_count", 0) or 0))

    # ------------------------------------------------------------ the snapshot (kept on disk: a crash is a hang-up)
    def _path(self):
        from . import config
        cfg = self.s.settings
        safe = "".join(c for c in (cfg.profile or "Default") if c.isalnum() or c in " -_").strip() or "Default"
        return os.path.join(config.board_dir(cfg.board), f"hangup_items_{safe}.json")

    def _load(self):
        if os.environ.get("MUDPILOT_NO_RECORD"):
            return
        try:
            with open(self._path(), encoding="utf-8") as f:
                self.snap = json.load(f) or None
        except (OSError, ValueError):
            self.snap = None

    def _write(self):
        if os.environ.get("MUDPILOT_NO_RECORD"):
            return
        body = {k: v for k, v in (self.snap or {}).items() if k != "t"}
        if body == self._written:
            return
        self._written = body
        try:
            p = self._path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.snap, f)
            os.replace(tmp, p)
        except OSError:
            pass

    def snapshot(self, why="save"):
        """At MudPilot's save points while in the game, once 'i' has been read on this connection."""
        s, st = self.s, self.s.state
        if self.job or not self.enabled() or not s.telnet.connected or not s._entered or st.dead:
            return False
        self._note_conn()
        if st.inv_seq <= self._inv0 or not (st.carrying or "").strip():
            return False                         # no 'i' this connection: the list could be from before a death
        x = getattr(s.bot, "x", None)
        self.snap = {"items": counts(st.carrying, st.keys), "worn": [n for n, _sl in worn_list(st.carrying)],
                     "room": list(st.room) if st.room else None, "hp": st.hp, "max_hp": st.max_hp,
                     "lives": st.lives, "combat": bool(st.in_combat), "pvp": bool(getattr(x, "pvp_target", None)),
                     "board": s.settings.board, "profile": s.settings.profile, "t": time.time()}
        self._write()
        return True

    def note_drop(self):
        """The line went down: the HP / fight at that moment is what the hang-up penalty saw."""
        if self.snap and self.job is None and self.s._entered:
            st = self.s.state
            self.snap.update(hp=st.hp, max_hp=st.max_hp, combat=bool(st.in_combat) or self.snap.get("combat"),
                             t=time.time())
            if st.room:
                self.snap["room"] = list(st.room)
            self._write()

    def note_clean_exit(self):
        """Disconnect (the game's exit command first): a clean quit drops nothing, so the next login has nothing to
        check."""
        if self.snap and self.job is None:
            self.snap["clean"] = True
            self._write()

    def _note_conn(self):
        if self._conn != self.s._connected_at:
            self._conn = self.s._connected_at
            self._inv0 = self.s.state.inv_seq

    # ------------------------------------------------------------ back in
    def on_entered(self):
        """session: first prompt of a connection (the _entered block, after _back_in)."""
        s = self.s
        self._note_conn()
        if self._done_conn == s._connected_at:
            return                               # one pass per connection
        self._done_conn = s._connected_at
        snap = self.snap
        if not snap or not self.enabled():
            return
        if snap.get("board") != s.settings.board or snap.get("profile") != s.settings.profile:
            return
        if not snap.get("items") or snap.get("clean"):
            return
        self.job = {"phase": "inv", "t": time.time(), "asked": 0.0, "lives": None}
        s.bot.hold(HOLD, "checking for items the hang-up dropped")
        s.log("Hang-up item pickup: back in — reading the pack to see whether the hang-up dropped anything")

    def note_line(self, text):
        j = self.job
        if not j:
            return
        t = (text or "").strip()
        m = LIVES_RE.search(t)
        if m:
            j["lives"] = int(m.group(1))
        if TOOK_RE.match(t):
            j["took_at"] = time.time()

    def near_death(self) -> bool:
        sn = self.snap or {}
        hp, mx = sn.get("hp"), sn.get("max_hp")
        if hp is None:
            return False
        if hp <= 0:
            return True                          # dropped: any HP share is a death
        return bool(mx) and hp * 100 < mx * NEAR_DEATH_PCT

    def _finish(self, why, forget=True):
        self.job = None
        self.s.bot.release(HOLD)
        self.s.log(f"Hang-up item pickup: {why}")
        if forget:
            self.snap = None                     # used up: the next save after an 'i' makes a fresh one

    def tick(self):
        s, st, b = self.s, self.s.state, self.s.bot
        self._note_conn()
        j = self.job
        if not j:
            return
        now = time.time()
        if not s.telnet.connected:
            # the link dropped again mid-pass: keep the list and try again on the next connection
            self.job = None
            self._done_conn = None
            b.release(HOLD)
            s.log("Hang-up item pickup: the line dropped before it was done — trying again once back in")
            return
        if getattr(s.settings, "hands_off", False):
            return self._finish("Hands off is on — not picking anything up", forget=False)
        sn = self.snap or {}
        ph = j["phase"]
        if ph == "inv":
            if st.inv_seq > self._inv0:
                j["short"] = missing(sn.get("items") or {}, counts(st.carrying, st.keys))
                if not j["short"]:
                    return self._finish("nothing missing")
                s.log("Hang-up item pickup: missing since the hang-up — "
                      + ", ".join(f"{n} {k}" for k, n in j["short"].items()))
                j["phase"], j["t"] = ("death" if self.near_death() else "room"), now
            elif not j["asked"] and now - j["t"] > INV_WAIT:
                j["asked"] = now
                s.send("i", from_bot=True)       # (straight out: the walk is held for it, it's once per login)
            elif j["asked"] and now - j["asked"] > INV_WAIT:
                return self._finish("couldn't read the pack — not picking anything up")
            return
        if ph == "death":
            if not j.get("stat_at"):
                j["stat_at"] = now
                s.send("stat", from_bot=True)
                return
            if j["lives"] is None and now - j["stat_at"] < STAT_WAIT:
                return
            was, room = sn.get("lives"), tuple(sn["room"]) if sn.get("room") else None
            if j["lives"] is not None and was is not None and j["lives"] == was - 1 and st.room and st.room != room:
                return self._death(room)
            j["phase"], j["t"] = "room", now
            return
        if ph == "room":
            v = st.view
            if v is not None and (v.exits is None or v.name in ("(dark)", "(blind)")):
                return self._finish("couldn't see the room (dark, or blind) — not picking anything up")
            fresh = v is not None and v.t >= getattr(s, "_entered_at", 0) - 1
            if not st.room or not fresh:
                if not j.get("looked"):
                    j["looked"] = now
                    s.send("", from_bot=True)
                elif now - j["looked"] > ROOM_WAIT:
                    return self._finish("not sure which room this is — not picking anything up")
                return
            want = tuple(sn["room"]) if sn.get("room") else None
            if not want or st.room != want:
                return self._finish("came back in a different room — what dropped is back where it happened")
            j["phase"], j["t"] = "fight", now
            return
        if ph == "fight":
            if st.in_combat:
                if now - j["t"] > FIGHT_WAIT:
                    return self._finish("a fight kept going — not picking anything up")
                return
            v = st.view
            if v and any(rec is None or b.hostile(rec) for _sh, rec in (v.monsters or [])):
                return self._finish("a monster is here — not picking anything up")
            plan = pickup_plan(j["short"], (v.items if v else []), self.cap())
            if not plan:
                return self._finish("none of it is on the floor here")
            names = []
            for name, n in plan:
                for _ in range(n):
                    b.send(f"get {name}")        # one 'get' per copy: the Stock way (Paradigm never gets here)
                names.append(f"{n} {name}")
            s.log("Hang-up item pickup: picking up " + ", ".join(names)
                  + (f" (the board drops at most {self.cap()})" if sum(n for _x, n in plan) >= self.cap() else ""))
            j.update(phase="settle", t=now, took_at=now, plan=plan)
            return
        if ph == "settle":
            if now - max(j["t"], j.get("took_at", 0)) < GET_SETTLE:
                return
            j["inv1"] = st.inv_seq
            s.send("i", from_bot=True)
            j["phase"], j["t"] = "dress", now
            return
        if ph == "dress":
            if st.inv_seq <= j["inv1"] and now - j["t"] < DRESS_WAIT:
                return
            picked = {name for name, _n in j.get("plan") or []}
            worn_now = {norm(n) for n, _sl in worn_list(st.carrying)}
            have = counts(st.carrying, st.keys)
            put_on = [n for n in sn.get("worn") or [] if norm(n) in picked and norm(n) not in worn_now
                      and have.get(norm(n))]
            for n in put_on[:20]:
                b.send(f"eq {n}")                # the same way redress.py puts gear back on
            if put_on:
                s.log("Hang-up item pickup: putting back on " + ", ".join(put_on))
                gm = getattr(s, "gearmodes", None)
                if gm is not None:
                    gm._applied = None           # gear modes: work the set out again from what's worn now
                s.send("i", from_bot=True)
            got = sum(n for _x, n in j.get("plan") or [])
            left = sum(j["short"].values()) - got
            return self._finish(f"done — picked up {got}" + (f"; {left} not found here (forgotten)" if left > 0 else ""))

    def _death(self, room):
        """One life fewer and somewhere else: the hang-up's HP share killed us while we were off. Recorded as a
        death; the gear is on the corpse back there, which is death recovery's job (comeback / redress)."""
        s, b = self.s, self.s.bot
        self._finish("one life fewer and back in a different room — the hang-up killed us; leaving the gear to death "
                     "recovery")
        b._last_room, b._last_mobs = room, ["the hang-up penalty"]
        b.on_death()
        # it's over already: a 'hang up after dying' now would only be another hang-up, standing where the dead arrive
        b._death_hangup_at = 0
