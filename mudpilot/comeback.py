"""Party comeback: nobody gets left behind.

Like pMUD's party cohort. You lead and walk a loop:
  * A member drops ("Revolution just disconnected!!!" / "just left the Realm."): the loop pauses
    where you are and waits for them (Party tab: up to N minutes, then carries on without them).
  * They log back in ("Revolution just entered the Realm."), or a member stopped following but is
    still around ("Revolution is no longer following you."): MudPilot telepaths them @where, walks
    to the room they answer with, invites them again (they get the @join), then goes back to the loop.
You follow someone and the party breaks without you leaving it: you telepath the leader
"@comeback <your room>", and their MudPilot walks to you (MegaMUD leaders ignore it harmlessly).
"""
from __future__ import annotations

import re
import time

DISC_RE = re.compile(r"^([A-Z][a-z]+) just (?:disconnected!*|left the Realm\.?)\s*$")
BACK_RE = re.compile(r"^([A-Z][a-z]+) just entered the Realm\.?\s*$")
NOT_HERE_RE = re.compile(r"^You don't see (\w+) here\.?\s*$", re.I)
UNFOLLOW_RE = re.compile(r"^([A-Z][a-z]+) is no longer following you\.?\s*$")
LEFT_LEADER_RE = re.compile(r"^(?:You are no longer following ([A-Z][a-z]+)|Your party has been disbanded)\.?", re.I)
ARRIVE_RE = re.compile(r"^([A-Z][a-z]+) (?:walks|strides|moves|runs|sneaks|steps|wanders|limps) into the room\b")
WHERE_RE = re.compile(r"map\s+(\d{1,3})\s+room\s+(\d{1,5})|(?<![\d/])(\d{1,3})\s*/\s*(\d{1,5})(?![\d/])", re.I)


class Comeback:
    def __init__(self, session):
        self.s = session
        self.missing: dict = {}     # name -> {"t", "why"}
        self.fetch = None           # {"name", "asked", "room", "back", "phase", "t"}
        self._self_left = 0.0
        self.away: dict = {}        # name -> when they @stop'd us (a restart): they come back here, don't go looking
        self.rego_when_back = None  # (who, when): an @rego held until everyone away for a restart is back

    AWAY_SECS = 15 * 60
    SCATTER_HOLD_SECS = 30      # a scattered member's @where answer: the walk waits this long at most (0.8.222)
    STILL_HERE_SECS = 120       # @stop'd but still in the party and following after this: they never left (0.8.222)

    def stepped_away(self, name) -> bool:
        t = self.away.get((name or "").lower())
        return bool(t) and time.time() - t < self.AWAY_SECS

    @property
    def cfg(self):
        return self.s.settings

    def reset(self, why=""):
        self.missing, self.fetch = {}, None
        self.queued = []

    def leading(self) -> bool:
        x = self.s.bot.x
        return bool(getattr(x, "_own_party", False)) or (bool(self.s.state.party) and not getattr(x, "_following", None))

    # ------------------------------------------------------------ lines
    _last_members: list = []

    PARTY_MOVE_SECS = 20

    def note_sent(self, cmd):
        if re.match(r"^\s*(?:leave|disband|follow|join)\b", cmd or "", re.I):
            self._self_left = time.time()           # we left on purpose: no @comeback
        elif re.match(r"^\s*\.?\s*@party\s+\S", cmd or "", re.I):
            self.party_move()                        # the leader takes the party through: '@party go hole'

    def party_move(self):
        """'@party go hole': everyone goes through and the party breaks on the way — that's expected. For a while
        nobody sends @comeback and nobody walks back for anybody; they regroup on the other side (Dan, 2026-10-30:
        Revolution went hole, Buddy and Evolution @comeback'd him and he walked back down for them)."""
        self._self_left = time.time() + self.PARTY_MOVE_SECS - 10   # (checks are 'more than 10 s since')

    def moving_together(self) -> bool:
        return time.time() - self._self_left < 10

    def _training(self, name=None) -> bool:
        """0.8.200 auto-train: training is a realm excursion ("X just left the Realm." … "just entered the Realm."),
        drops a follower from the party and disbands the leader's. On a training trip that's expected: the trip
        re-invites everyone itself, so comeback leaves it alone."""
        tr = getattr(self.s, "training", None)
        if tr is None:
            return False
        if name is None:
            return tr.leader_trip_on() or tr.holding_comeback()
        return tr.expects(name)

    def feed_line(self, text: str):
        t = text.strip()
        mj = re.match(r"^(\w+) (?:started to follow|is now following) you\b", t)
        if mj:
            # (ahead of the party_comeback check — 0.8.221, bug hunt: c_rego holds an @rego here whatever that switch
            # says, and with it off nothing ever let it go, so the leader stood there for good)
            self.away.pop(mj.group(1).lower(), None)   # back with us: the restart's over
            rw = self.rego_when_back
            if rw and not any(self.stepped_away(n) for n in list(self.away)):
                self.rego_when_back = None
                if time.time() - rw[1] < self.AWAY_SECS and not self.s.bot.walking:
                    self.s.log(f"Everyone's back — carrying on ({rw[0]}'s @rego)")
                    self.s.bot.rego()
        if not self.cfg.party_comeback:
            return
        me = (self.cfg.my_name or "").lower()
        ma = ARRIVE_RE.match(t)
        if ma and self.s.state.room and any(ma.group(1).lower() == n.lower() for n in (self.s.state.party or {})):
            # "Revolution walks into the room from the south." — with us (the room display came before they did)
            self.__dict__.setdefault("last_seen", {})[ma.group(1).lower()] = (self.s.state.room, time.time())
        m = NOT_HERE_RE.match(t)
        if m:
            # the invite on getting back in found nobody: they're not in yet (Evolution, 2026-11-03, back from an
            # update before Buddy — invited him, then walked off; "Buddy just entered the Realm" meant nothing to
            # him). Wait for them like a member who dropped, and go and get them when they're in
            rec = (getattr(self.s, "_reinvited", None) or {}).get(m.group(1).lower())
            if rec and time.time() - rec[1] < 10 and rec[0] not in self.missing:
                self.missing[rec[0]] = {"t": time.time(), "why": "dropped"}
                self.s.log(f"Comeback: {rec[0]} isn't back in yet — waiting here for them "
                           f"(up to {self.cfg.comeback_wait_mins} min)")
            return
        m = DISC_RE.match(t)
        if m and self._training(m.group(1)):
            return                                   # gone to train (auto-train's trip invites them back)
        if m and self.leading() and m.group(1) in self.s.state.party and m.group(1).lower() != me:
            self.missing[m.group(1)] = {"t": time.time(), "why": "dropped"}
            self.s.log(f"Comeback: {m.group(1)} dropped — waiting here for them "
                       f"(up to {self.cfg.comeback_wait_mins} min)")
            return
        m = BACK_RE.match(t)
        if m and self._training(m.group(1)):
            return
        if m and m.group(1) in self.missing and self.leading():
            self._ask_where(m.group(1))
            return
        m = UNFOLLOW_RE.match(t)
        if m and self.s.bot.portal_cmd_just_sent():
            return                                   # through a portal: the bot is getting them through (@do)
        if m and self._training(m.group(1)):
            return                                   # training dropped them from the party: the trip re-invites
        if m and self.stepped_away(m.group(1)):
            # they @stop'd us and logged off for a restart: they come back to this room and ask to be invited.
            # Going after them walked the leader off, and Buddy came back alone through the dark elves and hung up
            # (2026-10-30). Stay put.
            self.s.log(f"Comeback: {m.group(1)} stopped us for a restart — staying here for them")
            return
        if m and self.fetch and time.time() - self._self_left > 10 and \
                time.time() - getattr(self.s.bot, "_user_stop_at", 0) > 60 and \
                m.group(1).lower() != (self.fetch.get("name") or "").lower() and self.leading():
            # (0.8.201, party hunt: a second member stopped following while the first was being fetched — it was
            #  ignored, and once the first rejoined the loop went on without them) — fetch them next
            name = m.group(1)
            self.missing.setdefault(name, {"t": time.time(), "why": "left behind"})
            q = self.__dict__.setdefault("queued", [])
            if name not in q:
                q.append(name)
            self.s.log(f"Comeback: {name} stopped following too — fetching them after {self.fetch['name']}")
            return
        if m and time.time() - self._self_left > 10 and not self.fetch and \
                time.time() - getattr(self.s.bot, "_user_stop_at", 0) > 60 and \
                (self.leading() or self.s.bot.walking):
            # stopped following (got left behind, wandered off, a portal took them back): hold the walk, find
            # out where they are, go get them. Even if they're still in the room this second — they're
            # often just leaving it.
            name = m.group(1)
            self.missing[name] = {"t": time.time(), "why": "left behind"}
            self.s.log(f"Comeback: {name} stopped following — holding the walk and finding them")
            self._ask_where(name)
            return
        if re.match(r"^your party has been disbanded", t, re.I) and time.time() - self._self_left > 10 \
                and self.s.bot.walking and not self.fetch and not self.s.bot.portal_cmd_just_sent() \
                and not self._training():
            # 'Your party has been disbanded' while we walk = someone got left (a room spell flung us, a trap,
            # a portal): find whoever isn't here, and hold the walk till they're back
            me = (self.cfg.my_name or "").lower()
            for name in [n for n in (self._last_members or []) if n.lower() != me]:
                if name in self.missing or self.stepped_away(name):
                    continue
                self.missing[name] = {"t": time.time(), "why": "left behind"}
                self.s.log(f"Comeback: the party broke — {name} isn't with us; holding the walk and finding them")
                if self._here(name):
                    self.s.send(f"invite {name}", from_bot=True)
                    self.fetch = {"name": name, "phase": "invited", "room": self.s.state.room, "back": None,
                                  "t": time.time()}
                else:
                    self._ask_where(name)
                break
            return
        m = LEFT_LEADER_RE.match(t)
        own_loop = bool(self.s.bot.walking and self.s.bot.loop)      # (looping on our own: nobody to come back for)
        if m and self._training():
            # the leader's training trip (or our own train on its order): no @comeback — it invites us back (0.8.200)
            return
        if m and not own_loop and not self.leading() and time.time() - self._self_left > 10 and not self.moving_together():
            leader = m.group(1) or getattr(self.s.bot.x, "_followed", None)
            room = self.s.state.room
            if leader and room and self.s.world.look_alike(room) and self.s.bot.locate_now("left the party"):
                # a room that looks like others: the board's room number first, so the leader comes to the right
                # one (Evolution, 2026-10-30, sent 8/848 from 8/16 — Revolution searched the wrong courtyard)
                self._comeback_ask = (leader, time.time(), self.s.state.locate_ok)
                self.s.log(f"Comeback: the party broke — checking which room this is, then asking {leader} to come back")
            elif leader and room:
                self.s.log(f"Comeback: the party broke — asking {leader} to come back for me")
                self.s.send(f"/{leader} @comeback {room[0]}/{room[1]}", from_bot=True)

    def answer(self, sender, msg) -> bool:
        """'{Rotting Glade, Trail - map 17 room 1637; exits: …}' from the member we asked @where."""
        f = self.fetch
        if not f or f["phase"] != "asked" or sender.lower() != f["name"].lower():
            return False
        m = WHERE_RE.search(msg)
        room = (int(m.group(1) or m.group(3)), int(m.group(2) or m.group(4))) if m else None
        if not room or not self.s.world.room(room):
            room = self._room_from_megamud(msg)       # MegaMUD: '{Eastern Road (Exits: N,NW)}'
        if not room:
            return False
        b = self.s.bot
        f["room"], f["phase"], f["t"] = room, "going", time.time()
        if b.path and b.loop and not f.get("back"):
            f["back"] = (b.path, True)
        f.setdefault("resume_before", getattr(b, "resume", None))   # what Rego carried on with before this trip
        self.s.log(f"Comeback: {f['name']} is at {room[0]}/{room[1]} — going to get them")
        if self.meet_outside_toll(f, room):
            return True
        if self.s.state.room == room:
            f["phase"] = "invite" if not f.get("no_invite") else "going"
        elif not b.goto(room):
            self.s.log(f"Comeback: no route to {f['name']} — carrying on")
            self._finish()
        return True

    MM_WHERE_RE = re.compile(r"^\{?\s*(.+?)\s*\(Exits?:\s*([A-Z, ]*)\)", re.I)

    def _room_from_megamud(self, msg):
        """A MegaMUD @where answer has the room's name and exits, not its number: the nearest room that fits."""
        m = self.MM_WHERE_RE.match(msg.strip())
        if not m:
            return None
        w, here = self.s.world, self.s.state.room
        exits = {x.strip().upper() for x in m.group(2).split(",") if x.strip()}
        cands = w.candidates(m.group(1), exits) or w.by_name.get(m.group(1).lower(), [])
        if not cands:
            return None
        if len(cands) == 1 or not here:
            return cands[0] if len(cands) == 1 else None
        # they were following us: the room they're in is almost always one we just walked through (Dan) — the
        # latest room on our own trail that fits beats the nearest look-alike (Temple Colonnade has dozens)
        trail = list(getattr(self.s.state, "history", None) or [])[-40:]
        for room in reversed(trail):
            if room in cands and room != here:
                return room
        best = None
        for c in cands[:40]:
            rt = w.route(here, c, level=self.s.state.level or None)
            if rt is not None and (best is None or len(rt) < best[1]):
                best = (c, len(rt))
        return best[0] if best and best[1] <= 60 else None

    # ------------------------------------------------------------ tolls
    def toll_stop(self, room):
        """(the room before the toll, copper) when the way from here to `room` pays a toll, else None."""
        w, b, here = self.s.world, self.s.bot, self.s.state.room
        if not here or not room:
            return None
        try:
            rt = w.route(here, tuple(room), level=b.route_level(), have=b.held_items() or set())
        except Exception:
            return None
        prev = tuple(here)
        for ex in rt or []:
            if getattr(ex, "kind", "") == "toll":
                m = re.search(r"Toll:\s*(\d+)", getattr(ex, "etype", "") or "")
                return prev, int(m.group(1)) if m else 0
            prev = tuple(ex.to)
        return None

    def meet_outside_toll(self, f, room) -> bool:
        """Dan, 2026-11-17: Revolution walked into Rodolfo's Training Hall (80,000-copper toll each way in) four times
        to regroup with Miserable, who was training there. Don't pay to fetch someone: stop before the toll and
        @summon them out to us. True = doing that (the walk / the wait is under way)."""
        ts = self.toll_stop(room)
        if not ts or ts[1] < self.MEET_TOLL:
            return False                          # (a few copper at a town gate: just pay it)
        stop, toll = ts
        name = f["name"]
        f.update(room=stop, phase="going", t=time.time(), meet=time.time())
        self.s.send(f"/{name} @summon {stop[0]} {stop[1]}", from_bot=True)
        self.s.log(f"Comeback: the way to {name} pays a {toll:,}-copper toll — waiting outside it at "
                   f"{stop[0]}/{stop[1]} and asking them to come out (@summon)")
        b = self.s.bot
        if tuple(self.s.state.room or ()) != stop and not b.goto(stop):
            self.s.log(f"Comeback: no route to {stop[0]}/{stop[1]} — carrying on")
            self._finish()
        return True

    MEET_WAIT = 120
    MEET_TOLL = 10_000      # copper (1 platinum): below that, paying beats waiting

    def _meet_tick(self, f, now) -> bool:
        """Outside the toll, waiting for them to come out. True = still waiting."""
        st = self.s.state
        if not f.get("meet") or tuple(st.room or ()) != tuple(f["room"]) or self.s.bot.walking:
            return False
        if self._here(f["name"]) or any(n.lower() == f["name"].lower() for n in (st.party or {})):
            f["meet"] = None                      # out: on as usual (invite them / carry on together)
            return False
        if now - f["meet"] > self.MEET_WAIT:
            self.s.log(f"Comeback: {f['name']} didn't come out to {f['room'][0]}/{f['room'][1]} — waiting for them "
                       "here, not paying the toll")
            self.fetch = None
            self.s.bot.stop(f"Waiting for {f['name']} outside the toll at {f['room'][0]}/{f['room'][1]}")
            return True
        self.s.bot.status = f"Waiting outside the toll for {f['name']} (@summon sent)"
        f["t"] = now
        return True

    # ------------------------------------------------------------ helpers
    def _here(self, name):
        v = self.s.state.view
        return bool(v and any(p.split()[0].strip(".,").lower() == name.lower() for p in (v.players or []) if p.split()))

    def _ask_where(self, name, ask=True):
        b = self.s.bot
        back = (b.path, True) if b.path and b.loop else None
        if back is None and b.walking and b.path and b.path.title.startswith("Go to ") and \
                getattr(b, "_goto_target", None):
            back = ("goto", b._goto_target, b.after_goto)   # a Go to: pick it up again once they're back
            # — and what it was for: '@loop' walking to the loop's start lost the loop and Evolution sat at
            # 17/183 resting for 18 min (Revolution's PVE party, 2026-11-03)
        prev = self.fetch
        if prev and prev.get("name") and prev["name"].lower() != name.lower():
            # a second member's @comeback while we're fetching the first (a three-character party broke): fetch this
            # one, keep the first for afterwards, and keep where we were really going — not the first one's room
            back = prev.get("back")
            q = self.__dict__.setdefault("queued", [])
            if name in q:
                q.remove(name)                       # (fetching them now: not again afterwards)
            if prev["name"] not in q:
                q.append(prev["name"])
            # (0.8.201, party hunt: _next_queued only fetches a name in `missing` — a member queued here never was,
            #  so after the second one was back the first was dropped and the loop went on)
            self.missing.setdefault(prev["name"], {"t": prev.get("t0") or prev.get("t") or time.time(),
                                                   "why": "left behind"})
            self.s.log(f"Comeback: {name} too — fetching {name}, then {prev['name']}")
        keep = {}
        if prev and prev.get("name") and prev["name"].lower() == name.lower():
            # already fetching this one: what we do afterwards stays the same. 0.8.197 (Dan, 2026-11-15): Miserable
            # was on the Go to back to Revolution when Revolution's own @comeback came in — the new fetch's 'back'
            # became that Go to, the Stonecaps loop was forgotten, and he stood in 14/6559 from 02:25 till morning
            back = prev.get("back") if prev.get("back") is not None else back
            if "resume_before" in prev:
                keep["resume_before"] = prev["resume_before"]
        self.fetch = {"name": name, "phase": "asked", "room": None, "back": back, "t": time.time(), **keep}
        if ask:
            self.s.send(f"/{name} @where", from_bot=True)

    def holding(self) -> str | None:
        """Leader waiting for a dropped member (the loop stays put)."""
        if not self.cfg.party_comeback:
            return None
        now = time.time()
        lim = float(self.cfg.comeback_wait_mins or 0) * 60
        f = self.fetch
        if f and f["phase"] in ("asked", "invite", "invited") and f["name"] in self.missing:
            return f["name"]                         # finding / inviting them back: stay put
        if f and f.get("no_invite") and f["phase"] == "asked" and now - f["t"] < self.SCATTER_HOLD_SECS:
            # 0.8.222 (Dan, 11-20 bug hunt D1): a member still in the party but not with us — stand still while their
            # @where answer comes in (30 s at most), instead of walking on further away from them
            return f["name"]
        for n, m in list(self.missing.items()):
            if m["why"] == "dropped" and not self.fetch:
                if now - m["t"] > lim:
                    self.s.log(f"Comeback: {n} didn't come back in {self.cfg.comeback_wait_mins} min — carrying on without them")
                    del self.missing[n]
                    continue
                return n
        return None

    REFIND_TRIES = 3            # invited where they said and they weren't there: ask @where again this many times
    SEARCH_HOPS = 4            # no @where answer: rooms back along our trail to look in, past where we last saw them

    def _note_seen(self):
        """Where each party member was last in the room with us (their 'Also here')."""
        st = self.s.state
        v = st.view
        if not v or not st.room or not v.players:
            return
        seen = getattr(self, "last_seen", None)
        if seen is None:
            seen = self.last_seen = {}
        for p in v.players:
            n = p.split()[0].strip(".,") if p.split() else ""
            if n and any(n.lower() == m.lower() for m in (getattr(self, "_last_members", None) or [])):
                seen[n.lower()] = (st.room, time.time())

    def _trail_back(self, room) -> list:
        """The rooms we walked through before `room`, most recent first (where a dropped follower might be)."""
        hist = list(getattr(self.s.state, "history", None) or [])
        if room not in hist:
            return []
        i = len(hist) - 1 - hist[::-1].index(room)
        out = []
        for r in reversed(hist[:i]):
            if r != room and r not in out:
                out.append(r)
            if len(out) >= self.SEARCH_HOPS:
                break
        return out

    def _search_from(self, name):
        """No answer to @where (MegaMUD in the dark doesn't): the room we last saw them in, if recent."""
        seen = (getattr(self, "last_seen", None) or {}).get(name.lower())
        if seen and time.time() - seen[1] < 600 and seen[0] != self.s.state.room:
            return seen[0]
        trail = self._trail_back(self.s.state.room) if self.s.state.room else []
        return trail[0] if trail else None

    def _scattered(self) -> str | None:
        """Leading and walking, a member still in the party but not with us for a while (Dan, 2026-10-28: the
        Caves of Chaos scatter the party on the phoenix feather quest — find them before heading up to Morukai).
        Their name, once, or None."""
        s, st, b, cfg = self.s, self.s.state, self.s.bot, self.cfg
        secs = int(getattr(cfg, "party_missing_secs", 30) or 0)
        if not secs or not cfg.party_comeback or not self.leading() or not b.walking or st.in_combat or self.fetch:
            return None
        if self._training():
            return None                              # a training trip regroups everyone itself
        me = (cfg.my_name or "").lower()
        seen = getattr(self, "last_seen", None) or {}
        now = time.time()
        hist = list(getattr(st, "history", None) or [])
        for n in list(st.party or {}):
            if n.lower() == me or n in self.missing or self._here(n):
                continue
            ls = seen.get(n.lower())
            if not ls:
                continue                             # never seen them with us yet (just joined): not this
            if now - ls[1] < secs:
                continue
            moved = hist[::-1].index(ls[0]) if ls[0] in hist else 99    # rooms we've been to since
            if moved < 3:
                continue                             # only a step or two ahead: they're catching up
            done = self.__dict__.setdefault("_scatter_asked", {})
            if now - done.get(n.lower(), 0) < 120:
                continue
            done[n.lower()] = now
            return n
        return None

    def _rego_check(self):
        """0.8.222 (Dan, 11-20 bug hunt D2): an @rego held for a member who sent @stop but never logged off (no
        "started to follow you" ever comes). Still in the party and following ~2 minutes after the @stop (seen in a
        'par' since): count them back and go ahead, logged. Held 15 minutes anyway: dropped, logged — not silently."""
        rw = self.rego_when_back
        if not rw:
            return
        now, st, b = time.time(), self.s.state, self.s.bot
        party = {n.split()[0].lower(): rec for n, rec in (st.party or {}).items() if n and n.split()}
        stale = False
        for n in list(self.away):
            t0 = self.away.get(n) or 0
            if not self.stepped_away(n) or now - t0 < self.STILL_HERE_SECS or n not in party:
                continue
            if float((party.get(n) or {}).get("t") or 0) >= t0 + self.STILL_HERE_SECS:
                self.away.pop(n, None)
                self.s.log(f"Comeback: {n.capitalize()} sent @stop but is still in the party and following "
                           f"{int((now - t0) // 60)} min later — counting them back")
            else:
                stale = True                         # in the list from before: a fresh 'par' says if they're still in
        if stale and b.ready("rego_par", 30) and not b.walking:
            b.send("par")
        if any(self.stepped_away(n) for n in list(self.away)):
            return
        self.rego_when_back = None
        if now - rw[1] >= self.AWAY_SECS:
            self.s.log(f"Comeback: dropped {rw[0]}'s @rego — held {int(self.AWAY_SECS // 60)} min and not everyone "
                       f"came back")
        elif not b.walking:
            self.s.log(f"Everyone's back — carrying on ({rw[0]}'s @rego)")
            b.rego()

    def tick(self):
        self._rego_check()
        ca = getattr(self, "_comeback_ask", None)
        if ca and (self.s.state.locate_ok > ca[2] or time.time() - ca[1] > 6):
            self._comeback_ask = None               # the room number's in (or never came): now ask the leader
            room = self.s.state.room
            if room:
                self.s.log(f"Comeback: asking {ca[0]} to come back for me at {room[0]}/{room[1]}")
                self.s.send(f"/{ca[0]} @comeback {room[0]}/{room[1]}", from_bot=True)
        if self.s.state.party:
            self._last_members = list(self.s.state.party)
        self._note_seen()
        self._prune_back()
        n = self._scattered()
        if n:
            self.s.log(f"Comeback: {n} hasn't been with us for {int(getattr(self.cfg, 'party_missing_secs', 30))} s "
                       f"(still in the party) — asking @where and going to get them before carrying on")
            self._ask_where(n)
            self.fetch["no_invite"] = True           # still in the party: walk to them, no invite
        f = self.fetch
        if not f:
            return
        s, b, st = self.s, self.s.bot, self.s.state
        now = time.time()
        gone_at = (self.missing.get(f["name"]) or {}).get("t") or f.setdefault("t0", f["t"])
        rejoined = any(n.lower() == f["name"].lower() and (rec or {}).get("t", 0) > gone_at
                       for n, rec in (st.party or {}).items())   # seen in a 'par' / joined since they went missing
        if f["phase"] in ("asked", "going") and rejoined and not f.get("no_invite"):
            # back in the party already (Dan, 2026-10-28: Revolution re-joined a second after we set off for the
            # tomb where we'd last seen him — 313 steps back up the pyramid). Call off the search
            s.log(f"Comeback: {f['name']} is back in the party — not going looking")
            walking_there = b.walking and b.path and b.path.title.startswith("Go to ") and \
                getattr(b, "_goto_target", None) == f.get("room")
            if f["phase"] == "going" and f.get("room"):
                # stops it — and one still being worked out on the planner's thread mustn't set off when it's done
                b.call_off_goto(f["room"], f"{f['name']} is back — no need to go to {f['room'][0]}/{f['room'][1]}")
            if f["phase"] == "going" and walking_there:
                if f.get("resume_before") and not f.get("back"):
                    # Rego carries on with what we were doing before the search (the loop), not the called-off
                    # trip to them (2026-10-30: Revolution's @rego after his restart walked us to 17/1630 and
                    # we stood there idle, the Full Glades loop forgotten)
                    b.resume = f["resume_before"]
            return self._finish()
        if f["phase"] == "asked" and self._here(f["name"]) and not f.get("invited_here"):
            f["invited_here"] = now                  # standing right here: just ask them back in
            s.send(f"invite {f['name']}", from_bot=True)
        if f["phase"] == "asked" and f.get("invited_here") and now - f["invited_here"] < 15:
            return                                   # …and give them the chance before going anywhere
        if st.in_combat or st.resting:
            return
        if f["phase"] == "asked" and now - f["t"] > 10 and not f.get("searched"):
            room = self._search_from(f["name"])
            if room:
                s.log(f"Comeback: {f['name']} didn't answer @where — going back to {room[0]}/{room[1]}, where we "
                      "last saw them")
                f.update(phase="going", room=room, t=now, searched=1, trail=self._trail_back(room))
                f.setdefault("resume_before", getattr(b, "resume", None))
                if not b.goto(room):
                    s.log(f"Comeback: no route back to {room[0]}/{room[1]} — carrying on")
                    return self._finish()
                return
        if f["phase"] == "asked" and now - f["t"] > 30:
            s.log(f"Comeback: {f['name']} didn't say where they are — carrying on")
            return self._finish()
        if f["phase"] == "going" and b.walking and self._here(f["name"]) and st.room != f.get("room"):
            # walked into them on the way to where they said they were: stop here (Dan, 2026-10-30: Buddy found
            # Revolution, got the invite — and walked on to the room Revolution had been in)
            b.stop(f"Found {f['name']} on the way")
            f["room"] = st.room
        if f["phase"] == "going" and self._meet_tick(f, now):
            return
        if f["phase"] == "going":
            if st.room == f["room"] and not b.walking and f.get("searched") and not self._here(f["name"]):
                # looking for them without an answer: not here — the next room back along our trail
                nxt = (f.get("trail") or [None])[0]
                if nxt and f["searched"] <= self.SEARCH_HOPS:
                    f["trail"] = f["trail"][1:]
                    f.update(room=nxt, t=now, searched=f["searched"] + 1)
                    s.log(f"Comeback: {f['name']} isn't here — trying {nxt[0]}/{nxt[1]}")
                    if b.goto(nxt):
                        return
                s.log(f"Comeback: couldn't find {f['name']} along our way back — carrying on")
                return self._finish()
            if st.room == f["room"] and not b.walking:
                if f.get("no_invite"):
                    self.s.log(f"Found {f['name']}")
                    rs = getattr(b, "resume", None) or {}
                    if rs.get("target") == f["room"] and not rs.get("after"):
                        b.resume, b.stop_note = None, ""   # the walk to them is done: nothing left to Rego
                    return self._finish()            # …and carry on with the trip (the loop / the Go to)
                f["phase"], f["t"] = "invite", now
            elif not b.walking and now - f["t"] > 30:
                return self._finish()
        if f["phase"] == "invite":
            s.send(f"invite {f['name']}", from_bot=True)
            f["phase"], f["t"] = "invited", now
        elif f["phase"] == "invited" and (f["name"] in st.party or now - f["t"] > 20):
            if f["name"] in st.party:
                return self._finish()
            # invited, and they're still not with us: they weren't where they said (a look-alike room — Evolution,
            # 2026-10-30, said 8/847 from 8/16). Never walk off without them (Dan: Revolution 'didn't care'):
            # ask again a few times, then stop and wait
            tries = f.get("tries", 0) + 1
            if tries <= self.REFIND_TRIES:
                back = f.get("back")
                s.log(f"Comeback: {f['name']} still isn't with us — asking where they are again ({tries}/{self.REFIND_TRIES})")
                self._ask_where(f["name"])
                self.fetch.update(back=back, tries=tries)
                return
            self.fetch = None
            b.stop(f"Stopped: lost {f['name']} — they never turned up where they said. Waiting for them "
                   f"(Rego carries on without them)")
            s.on_alert(f"Lost {f['name']} — stopped and waiting")

    def _prune_back(self):
        """0.8.179: a 'dropped' member who's back in the party (seen in a 'par' since) or standing here isn't
        missing any more. Evolution noted Buddy 'dropped' while following him, Buddy was back 22 s later, and the
        note (only cleared when we lead) held Evolution's walk 'waiting for Buddy (regrouping)' with all three
        grouped up at 100% (2026-11-12)."""
        party = self.s.state.party or {}
        for n, m in list(self.missing.items()):
            if m.get("why") != "dropped" or (self.fetch and self.fetch.get("name") == n):
                continue
            back = any(p.lower() == n.lower() and (rec or {}).get("t", 0) > m["t"] for p, rec in party.items())
            if back or self._here(n):
                self.s.log(f"Comeback: {n} is back with us — not waiting any more")
                del self.missing[n]

    def _next_queued(self):
        q = self.__dict__.setdefault("queued", [])
        while q:
            n = q.pop(0)
            if n in self.missing and not any(p.lower() == n.lower() and (rec or {}).get("t", 0) > self.missing[n]["t"]
                                             for p, rec in (self.s.state.party or {}).items()):
                return n
        return None

    def _finish(self):
        f, self.fetch = self.fetch, None
        if f:
            self.missing.pop(f["name"], None)
            nxt = self._next_queued()
            if nxt:
                self.s.log(f"Comeback: {f['name']} is back — now fetching {nxt}")
                self._ask_where(nxt)
                self.fetch["back"] = f.get("back")       # (and afterwards, on to where we were going)
                return
            back = f.get("back")
            if back and back[0] == "goto" and not self.s.state.dead:
                if not self.s.bot.walking or (self.s.bot.path and self.s.bot.path.title.startswith("Go to ")
                                              and getattr(self.s.bot, "_goto_target", None) != back[1]):
                    self.s.log(f"Comeback: carrying on to {back[1][0]}/{back[1][1]}")
                    self.s.bot.goto(back[1], then=back[2] if len(back) > 2 else None)
            elif back and not self.s.bot.walking and not self.s.state.dead:
                self.s.log(f"Comeback: back to {back[0].title}")
                self.s.bot.start_path(back[0], loop=True, checked=True)
            elif not back and f.get("resume_before") and not self.s.bot.walking:
                self.s.bot.resume = f["resume_before"]   # we were stopped: Rego still carries on with the loop
