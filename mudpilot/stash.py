"""Rafts are heavy (Dan, 2026-11-05: "have the party stash the log rafts at the start of the loop then grab them and
reuse rather than rebuying"). A loop that doesn't cross water: on arriving, everyone hides their raft (canoe, punt…)
in the loop's room and remembers where. A walk that needs one again: the errand goes to the stash first ('search',
'get log raft', the party told '@unstash'), before any shop — and one that's gone missing is bought, as before.

Each character keeps its own record (settings.raft_stash: {"room": [map, room], "items": [names], "t": when})."""
from __future__ import annotations

import time

HIDE_SECS = 1.5           # between 'hide <item>' lines
CHECK_SECS = 4            # then 'i' to see they're out of the pack
GET_TRIES = 5             # 'search' + 'get' rounds at the stash before it's called gone (Dan, 2026-11-08: Buddy,
#                           half-ogre, low int, can take 3 or 4 searches to find his own raft)


class Stash:
    def __init__(self, bot):
        self.bot = bot
        self._job = None          # {"do": "hide"/"get", "names": [...], "room", "step", "t", "seq"}
        self._boats = None

    @property
    def s(self):
        return self.bot.s

    # ------------------------------------------------------------ what counts
    def boats(self) -> frozenset:
        """Item numbers that get you over water: whatever keeps a log raft's rooms off you (raft, skiff, canoe…)."""
        if self._boats is None:
            w = self.s.world
            raft = ((getattr(w, "item_names", None) or {}).get("log raft") or {}).get("num")
            out = set()
            if raft:
                for sp in set((getattr(w, "room_spells", None) or {}).values()):
                    try:
                        its = w.spell_items(sp)
                    except Exception:
                        continue
                    if raft in its:
                        out |= set(its)
            self._boats = frozenset(out)
        return self._boats

    def record(self) -> dict:
        return dict(getattr(self.s.settings, "raft_stash", None) or {})

    def stashed(self) -> set:
        """Item numbers in the stash."""
        w = self.s.world
        return {(w.item_names.get(n.lower()) or {}).get("num") for n in self.record().get("items") or []} - {None}

    def room(self):
        r = self.record().get("room")
        return tuple(r) if r else None

    def _save(self, rec):
        cfg = self.s.settings
        cfg.raft_stash = rec
        try:
            cfg.save()
        except OSError:
            pass

    # ------------------------------------------------------------ hiding
    def on_loop(self, mp, tell=False) -> bool | None:
        """Arrived on a loop (leading or alone): if it doesn't cross water, hide the rafts here and tell the party —
        when we hid one, on a new loop (tell: just back in, who knows what they carry), or when the party's @have
        said they carry one. None = the pack isn't read yet ('i' sent): ask again."""
        bot = self.bot
        if not getattr(self.s.settings, "stash_rafts", True) or not self.boats():
            return False
        if any(c & self.boats() for c in bot.carry_sets(mp)):
            return False                             # this loop crosses water itself: keep them
        hid = False
        if bot.held_items() is None:
            # just back in after a restart, the pack not read yet (Evolution, 2026-11-06: on the loop 2 min after
            # the relog, raft and all): read it, and the walk asks again
            asked = getattr(self, "_inv_asked", None)
            if not (asked and bot.st.inv_seq != asked[1]):       # (read since: an empty pack, nothing to hide)
                if not asked or time.time() - asked[0] > 20:
                    self._inv_asked = (time.time(), bot.st.inv_seq)
                    bot.send("i")
                return None
        else:
            hid = self.hide_here()
        er = bot.errands
        # Evolution leads with no raft of his own — Buddy and Revolution carry them (2026-11-06): the party's told
        # whatever the leader has
        if self.s.comeback.leading() and (hid or tell or getattr(er, "party_boats", False)):
            er.party_boats = False
            me = (self.s.settings.my_name or "").lower()
            for m in [n for n in (self.s.state.party or {}) if n.lower() != me]:
                bot.send(f"/{m} @stash raft")       # (bare '@stash' now sets their item stash room)
            return True
        return hid

    def hide_here(self) -> bool:
        st, w = self.bot.st, self.s.world
        if self._job or not st.room:
            return False
        have = (self.bot.held_items() or set()) & self.boats()
        if not have:
            return False
        names = [w.item_name(n) for n in sorted(have)]
        self._job = {"do": "hide", "names": names, "room": tuple(st.room), "step": 0, "t": 0, "seq": None}
        self.bot.log(f"Stashing {', '.join(names)} here ({st.room[0]}/{st.room[1]}) — this loop doesn't need "
                     f"{'it' if len(names) == 1 else 'them'}; picked up again on the way out")
        return True

    # ------------------------------------------------------------ getting them back
    def get_here(self, tell_party=False) -> bool:
        """At the stash: 'search', then 'get' each one. True = started."""
        st = self.bot.st
        names = self.record().get("items") or []
        if self._job or not names or not st.room or tuple(st.room) != self.room():
            return False
        self._job = {"do": "get", "names": list(names), "room": tuple(st.room), "step": 0, "t": 0, "seq": None,
                     "tries": 0}
        if tell_party and self.s.comeback.leading():
            me = (self.s.settings.my_name or "").lower()
            for m in [n for n in (self.s.state.party or {}) if n.lower() != me]:
                self.bot.send(f"/{m} @unstash")
        return True

    def busy(self) -> bool:
        return self._job is not None

    def hide_asked(self) -> bool:
        """The leader's '@stash': hide the raft here. The pack not read yet (just back in): read it, then hide.
        True = hiding, or will once the pack's read."""
        if self.bot.held_items() is None:
            self._want_hide = (time.time(), self.bot.st.inv_seq)
            self.bot.send("i")
            return True
        return self.hide_here()

    def tick(self) -> bool:
        """True = took the tick (hiding / searching)."""
        wh = getattr(self, "_want_hide", None)
        if wh and not self._job:
            if self.bot.held_items() is not None or self.bot.st.inv_seq != wh[1] or time.time() - wh[0] > 30:
                self._want_hide = None
                if self.bot.held_items() is not None:
                    self.hide_here()
        j = self._job
        if not j:
            return False
        bot, st = self.bot, self.bot.st
        now = time.time()
        if st.in_combat:
            return False
        if not st.room or tuple(st.room) != j["room"]:
            self._job = None                         # moved off: drop it (nothing recorded unless it went in)
            if j["do"] == "hide" and j["step"] >= len(j["names"]):
                # the 'hide's went out, then the leader walked on before the 'i' check (Buddy and Revolution,
                # 2026-11-06: 'You hid log raft.', nothing remembered, the rafts lost at 17/1631). Remember them:
                # the pick-up checks, and buys one if it's gone
                self._save({"room": list(j["room"]), "items": list(j["names"]), "t": now})
                bot.log(f"Stashed {', '.join(j['names'])} at {j['room'][0]}/{j['room'][1]} (moved on before checking)")
            return False
        if now - j["t"] < HIDE_SECS:
            return True
        n = len(j["names"])
        if j["do"] == "hide":
            if j["step"] < n:
                bot.send(f"hide {j['names'][j['step']]}")
                j["step"] += 1
                j["t"] = now
                return True
            if j["seq"] is None:
                j["seq"] = st.inv_seq
                bot.send("i")
                j["t"] = now
                return True
            if st.inv_seq == j["seq"] and now - j["t"] < CHECK_SECS * 2:
                return True
            have = bot.held_items() or set()
            w = self.s.world
            hid = [nm for nm in j["names"] if (w.item_names.get(nm.lower()) or {}).get("num") not in have]
            self._job = None
            if hid:
                self._save({"room": list(j["room"]), "items": hid, "t": now})
                bot.log(f"Stashed {', '.join(hid)} at {j['room'][0]}/{j['room'][1]}")
            else:
                bot.log("Couldn't stash the raft (still in the pack) — carrying it")
            return True
        # get
        if j["step"] == 0:
            bot.send("search")
            j["step"], j["t"] = 1, now
            return True
        if j["step"] <= n:
            nm = j["names"][j["step"] - 1]
            rc = self.s.remote
            if rc.making_room():
                return True                          # dropping coins for it: the get after
            if not j.get("roomed", {}).get(nm) and rc.needs_room(nm):
                j.setdefault("roomed", {})[nm] = True
                bot.log(f"Too heavy to pick the {nm} back up — dropping coins here to make room")
                rc.make_room(nm)
                return True
            bot.send(f"get {nm}")
            j["step"] += 1
            j["t"] = now
            return True
        if j["seq"] is None:
            j["seq"] = st.inv_seq
            bot.send("i")
            j["t"] = now
            return True
        if st.inv_seq == j["seq"] and now - j["t"] < CHECK_SECS * 2:
            return True
        have = bot.held_items() or set()
        w = self.s.world
        left = [nm for nm in j["names"] if (w.item_names.get(nm.lower()) or {}).get("num") not in have]
        if left and j["tries"] + 1 < GET_TRIES:
            j.update(step=0, seq=None, t=now, tries=j["tries"] + 1)
            return True
        self._job = None
        got = [nm for nm in j["names"] if nm not in left]
        self._save({})                               # picked up, or gone: either way nothing's there now
        if got:
            bot.log(f"Picked up the stashed {', '.join(got)}")
        if left:
            bot.log(f"Stashed {', '.join(left)} gone from {j['room'][0]}/{j['room'][1]} — buying "
                    f"{'one' if len(left) == 1 else 'them'} instead")
        return True
