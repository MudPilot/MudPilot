"""PvP safety and awareness.

* Hang up the moment a player attacks you (MegaMUD's "hang up on PvP").
* Optionally hang up when any player shows up (except friends / your party).
* Look toward movement you hear, once per direction per few seconds, so a pile of
  monsters chasing you doesn't send five looks in a row.
"""
from __future__ import annotations

import re
import time

from .worlddb import norm_dir, DIR_WORDS

DIR_WORDS_RE = r"(north(?:east|west)?|south(?:east|west)?|east|west|up|down|above|below|upwards|downwards)"
HEAR_RE = re.compile(r"you hear (?:[\w' -]{0,30}?)(?:to|from|coming from|in) (?:the )?" + DIR_WORDS_RE, re.I)
HEAR_ABOVE_RE = re.compile(r"you hear (?:[\w' -]{0,30}?)(above|below) you", re.I)
NOT_NAMES = {"The", "A", "An", "You", "Your", "It", "Its", "Some", "Someone", "Something", "Also", "Obvious",
             "There", "This", "That", "Broadcast", "Server",
             # a monster's follow-up line: "He bites into Skittles, drinking their blood!" (the vampire magus — hung
             # Revolution PVE up as 'PvP: He attacked Skittles', 2026-11-06)
             "He", "She", "They", "His", "Her", "Hers", "Their", "Them", "We", "Our", "One", "Another"}
ATTACK_VERBS = (r"(?:swings?|attacks?|hits?|slashes|smashes|stabs|bashes|punches|kicks|bites|claws|strikes?|lunges?|"
                r"casts?|fires?|shoots?|backstabs?|crushes|cuts|pierces|whips|clubs|jumpkicks?|sneaks? up)")
PVP_RE = re.compile(rf"^([A-Z][a-z]+)\s+{ATTACK_VERBS}\b.*\byou\b")
PVP_ANY_RE = re.compile(rf"^([A-Z][a-z]+)\s+{ATTACK_VERBS}\b(.*)$")
# a trap going off: "Spikes shoot out and stab Revolution viciously!" (the trap below the docks, 9/150 — Evolution
# hung up on 'Spikes', 2026-10-30). A plural verb plus out/up/down/from is never a player's attack line
TRAP_RE = re.compile(r"^[A-Z][a-z]+\s+(?:shoot|jut|spring|burst|fly|swing|drop|slam|fall|rain)\s+(?:out|up|down|from|in)\b")
PDEAD_RE = re.compile(r"^([A-Z][a-z]+) (?:collapses|falls to the ground|is dead|dies|has been slain|has been killed|"
                      r"is killed)", re.I)
SERVER_PVP_RE = re.compile(r"^Server PvP Message:.*\byou\b", re.I)
# the game's first warning, before any damage: "Bob moves to attack you!" / "…attack everyone in the room!"
MOVE_ATTACK_RE = re.compile(r"^([A-Z][a-z]+) (?:moves|turns|charges) to attack (you|everyone in the room)\b")
ARRIVE_RE = re.compile(r"^([A-Z][a-z]+)\s+(?:just\s+)?(?:walks|runs|sneaks|wanders|arrives|enters|appears|stumbles|flies|"
                       r"limps|crawls|steps|comes)\b.*(?:into the room|from|out of)")


HIDDEN_REVEAL_RE = re.compile(r"^you see ([A-Z][A-Za-z'-]+)\*?(?: [A-Z][a-z]+)? hiding in the shadows[.!]?$", re.I)


def as_dir(word: str) -> str | None:
    w = word.lower()
    return {"above": "U", "upwards": "U", "below": "D", "downwards": "D"}.get(w) or norm_dir(w)


class Safety:
    def __init__(self, session):
        self.s = session
        self._heard: dict = {}       # dir -> last time we looked that way
        self.hung_up_until = 0.0
        self.last_reason = ""
        self._was_in = False
        self._hp_armed = True        # low-HP hang-up armed (off after re-entering low, until HP recovers)
        self._hp_floor = None
        self._pvp_hang = None        # {"at", "hard", "reason", "victim", "looted"}: a PvP hang-up about to happen

    @property
    def cfg(self):
        return self.s.settings

    def friends(self) -> set:
        names = {n.lower() for n in (self.cfg.pvp_friends or [])}
        names |= {n.lower() for n in self.s.state.party}
        names |= {n.lower() for n in (self.cfg.remote_players or {})}
        names |= {k for k, p in self.s.players.data.items() if p.get("relationship") == "Friend"}
        if self.cfg.my_name:
            names.add(self.cfg.my_name.lower())
        return names

    @staticmethod
    def _benign(t: str) -> bool:
        """A heal / bless / buff on you, not an attack: "X casts greater mend on you, healing 26 damage!" (the word
        'damage' is in a heal), "X casts bless on you"."""
        if re.search(r"\bheal(?:s|ing|ed)?\b|\bcures?\b|\bmends?\b|\brestor", t, re.I):
            return True
        return bool(re.search(r"\bcasts?\b.*\b(?:on|upon) you\b", t, re.I)) and not re.search(r"\bfor \d+ damage\b", t, re.I)

    def is_player(self, name: str, sneak: bool = False) -> bool:
        if name in NOT_NAMES:
            return False
        w = self.s.world
        if w.loaded and w.identify_monster(name):
            return False                # a capitalised monster (e.g. a named boss)
        if w.loaded and name.lower() in self._spell_words():
            return False                # a room spell / trap ("Darts" in the pyramid) — not a player
        # Miserable PVE, 2026-11-05, fighting the manscorpion king: "Lightning strikes you for 2 damage!" hung him up.
        # The first word of a monster / room spell ('lightning', 'shards', 'poison') is the spell talking — unless
        # it's a player we've actually seen by that name
        v = self.s.state.view
        if not sneak and w.loaded and name.lower() in self._spell_heads() and name.lower() not in self.s.players.data \
                and not (v is not None and name in (v.players or [])):
            return False
        return True

    def spell_line(self, t: str) -> bool:
        """The line starts with the name of a room spell / trap ('Darts shoot out…', 'Poison darts…')."""
        if TRAP_RE.match(t):
            return True
        words = t.lower().split()
        sw = self._spell_words()
        return any(" ".join(words[:n]).strip(".,!") in sw for n in range(1, 5))

    def _spell_words(self) -> set:
        """Names of MME's non-player spells (room spells, traps, monster spells): 'darts', 'poison darts'…
        A line that starts with one is the room or a trap, never a player."""
        w = self.s.world
        if getattr(self, "_sw_for", None) is not w:
            out = set()
            for sp in (getattr(w, "spells", {}) or {}).values():
                nm = str(sp.get("Name") or "").strip().lower()
                if nm and len(nm) >= 3 and not nm.isdigit() and nm.title() not in NOT_NAMES \
                        and not sp.get("Learnable") and not sp.get("Short"):
                    out.add(nm)
            self._sw, self._sw_for = out, w
        return self._sw

    def _spell_heads(self) -> set:
        """First words of every non-learnable spell's name ('lightning hits' → 'lightning'), 4+ letters."""
        w = self.s.world
        if getattr(self, "_sh_for", None) is not w:
            out = set()
            for sp in (getattr(w, "spells", {}) or {}).values():
                words = str(sp.get("Name") or "").strip().lower().split()
                if words and len(words[0]) >= 4 and words[0].isalpha() and not sp.get("Learnable") \
                        and words[0].title() not in NOT_NAMES:
                    out.add(words[0])
            self._sh, self._sh_for = out, w
        return self._sh

    # ------------------------------------------------------------ lines
    def feed_line(self, text: str):
        t = text.strip()
        if not t or not self.s.telnet.connected:
            return
        cfg = self.cfg
        self._party_death(t)
        attacker, victim = None, None
        if (self.s.world.loaded and self.spell_line(t)) or TRAP_RE.match(t):
            return                      # a room spell / trap hitting you or the party isn't PvP
        mm = MOVE_ATTACK_RE.match(t)
        party = {n.lower() for n in self.s.state.party}
        me = (cfg.my_name or "").lower()
        mp_ = PVP_RE.match(t)
        # Strict on purpose — what fooled 0.8.131/0.8.132 (Miserable, Revolution, Buddy hung up on each other):
        #   "Revolution moves to attack everyone in the room."            his area spell: never hits the party
        #   "Revolution casts greater mend on you, healing 26 damage!"     a heal ('damage' is in it)
        # From a party member only "moves to attack you", or a hit on you "for N damage" that isn't a heal, counts.
        mate = (mm.group(1) if mm and mm.group(2).lower() == "you" and mm.group(1).lower() in party else None) or \
            (mp_.group(1) if mp_ and mp_.group(1).lower() in party and not self._benign(t) and
             re.search(r"\bfor \d+ damage\b", t, re.I) and not re.search(r"\beveryone\b", t, re.I) and
             not re.search(r"\byou (?:hit|attack|swing|cast)", t, re.I) else None)
        if mate and mate.lower() != me:
            # Dan, 2026-10-31: someone in your party attacking you — hang up, but they stay a friend with their @
            # permissions: friendly fire is nearly always an accident
            self.s.log(f"{mate} (in your party) attacked you — hanging up; they stay a friend, their @ commands too")
            return self.hangup(f"attacked by {mate} (party member — friendly fire?)")
        if SERVER_PVP_RE.match(t):
            attacker, victim = t[:60], "you"
        elif mm and self.is_player(mm.group(1)) and mm.group(1).lower() not in self.friends() \
                and mm.group(1).lower() not in party:
            attacker, victim = f"{mm.group(1)} moves to attack {mm.group(2)}", "you"
        else:
            m = PVP_RE.match(t)
            sneak = bool(re.search(r"\b(?:backstabs?|sneaks? up)\b", t, re.I))     # a hidden player: never a spell
            if m and not self._benign(t) and self.is_player(m.group(1), sneak) and m.group(1).lower() not in self.friends() \
                    and not re.search(r"\byou (?:hit|attack|swing|cast)", t, re.I):
                attacker, victim = f"attacked by {m.group(1)}", "you"
            else:
                victim = self._party_victim(t)
                if victim:
                    attacker = f"{t.split()[0]} attacked {victim}"
        if attacker:
            if cfg.hangup_on_pvp and not cfg.pvp_realm and not SERVER_PVP_RE.match(t):
                # a PVE realm: players can't hurt each other, so a line that only looks like PvP is a monster or a
                # friend's area spell. Say so, don't drop the party in the middle of the Mausoleum. (A 'Server PvP
                # Message' still hangs up — and marks the realm PvP.)
                self.s.log(f"Looks like PvP ({attacker}), but this realm is PVE — not hanging up")
                self.s.notify.send("pvp", f"Looks like PvP on a PVE realm: {attacker} — not hanging up")
            elif cfg.hangup_on_pvp:
                return self.pvp_hangup("PvP: " + attacker, victim)
            self.s.notify.send("pvp", f"PvP: {attacker} (not hanging up — @pvp on / PvP tab)")
        m = ARRIVE_RE.match(t) or HIDDEN_REVEAL_RE.match(t)
        if m and HIDDEN_REVEAL_RE.match(t) and self.is_player(m.group(1)):
            # pMUD: a search turned someone up — that's a player, and they were hiding in your room
            who = m.group(1)
            v = self.s.state.view
            if v is not None and who not in v.players:
                v.players.append(who)
            self.s.log(f"{who} was hiding here (found by searching)")
            self.s.notify.send("track", f"{who} was hiding in your room")
            try:
                self.s.players.get(who)
            except Exception:
                pass
        if m and self.is_player(m.group(1)) and m.group(1).lower() not in self.friends():
            if cfg.hangup_on_player:
                return self.hangup(f"player seen: {m.group(1)}")
            if cfg.hangup_on_enemy and self.s.players.relationship(m.group(1)) == "Enemy":
                return self.hangup(f"enemy seen: {m.group(1)}")
        if cfg.look_on_sound and not self.s.state.in_combat and \
                not any(e[0] == "move" for e in self.s.state.pending):
            m = HEAR_RE.search(t) or HEAR_ABOVE_RE.search(t)
            if m:
                d = as_dir(m.group(1))
                v = self.s.state.view
                if d and v is not None and v.exits is not None and d not in v.exits:
                    d = None     # no such exit here — a sound from beyond (a vortex / portal): don't 'l up'
                if d:
                    now = time.time()
                    if now - self._heard.get(d, 0) >= max(cfg.look_ignore_secs, 0):
                        self._heard[d] = now
                        self.s.send(f"l {d.lower()}", from_bot=True)
                        self.s.log(f"Heard something {DIR_WORDS[d]} — looking")
                    else:
                        self._heard[d] = self._heard[d]   # still inside the ignore window

    # ------------------------------------------------------------ PvP on the party
    def _party_victim(self, t):
        """'Bob backstabs Revolution for 400 damage!' — a player (not a friend) attacking someone in your party."""
        m = PVP_ANY_RE.match(t)
        if not m:
            return None
        att = m.group(1)
        if self._benign(t) or (re.search(r"\bcasts?\b", t, re.I) and not re.search(r"\bfor \d+ damage\b", t, re.I)):
            return None     # "Bob casts minor healing on Revolution!" — a stranger's heal / bless isn't an attack
        if not self.is_player(att, bool(re.search(r"\b(?:backstabs?|sneaks? up)\b", t, re.I))) or att.lower() in self.friends():
            return None
        me = (self.cfg.my_name or "").lower()
        party = {n.lower(): n for n in self.s.state.party if n.lower() != me}
        for w in re.findall(r"\b([A-Z][a-z]+)\b", m.group(2)):
            if w.lower() in party and w.lower() != att.lower():
                return party[w.lower()]
        return None

    def pvp_hangup(self, reason, victim):
        """Hang up before the next combat round. If it's a party member being hit, wait a moment to see
        whether they died — then grab what they dropped first (still before the next round)."""
        if victim == "you" or not victim:
            return self.hangup(reason)
        now = time.time()
        if self._pvp_hang:
            return
        period = getattr(self.s.clock, "period", 5.0) or 5.0
        hard = now + max(0.5, min(period - 1.2, 4.0))      # the next round never gets to go off
        self._pvp_hang = {"at": min(now + 0.6, hard), "hard": hard, "reason": reason, "victim": victim,
                          "looted": False}
        self.s.log(f"PvP on your party ({reason}) — hanging up within {hard - now:.1f}s")
        if self._dead_recently(victim):
            self._loot_dead(victim)

    def _dead_recently(self, name):
        return time.time() - getattr(self, "_deaths", {}).get(name.lower(), 0) < 3

    def _party_death(self, t):
        m = PDEAD_RE.match(t)
        if not m:
            return
        name = m.group(1)
        if name not in self.s.state.party:
            return
        self._deaths = {**getattr(self, "_deaths", {}), name.lower(): time.time()}
        ph = self._pvp_hang
        if ph and ph["victim"].lower() == name.lower():
            self._loot_dead(name)

    def _loot_dead(self, name):
        ph = self._pvp_hang
        if not ph or ph["looted"]:
            return
        ph["looted"] = True
        cmds = [c.strip() for c in (self.cfg.pvp_loot_cmds or "get all").split(";") if c.strip()]
        self.s.log(f"{name} died — grabbing what dropped before hanging up: {', '.join(cmds)}")
        for c in cmds:
            self.s.send(c, from_bot=True)
        ph["at"] = min(time.time() + 1.5, ph["hard"])     # time for the pick-ups, never past the round

    def _pvp_hang_tick(self):
        ph = self._pvp_hang
        if not ph:
            return
        if not self.s.telnet.connected:
            self._pvp_hang = None
            return
        if time.time() >= ph["at"]:
            self._pvp_hang = None
            self.hangup(ph["reason"])

    def tick(self):
        """Low-HP and naked hang-ups, checked every poll."""
        self._pvp_hang_tick()
        st, cfg = self.s.state, self.cfg
        if cfg.hangup_if_naked and self.s.telnet.connected and st.inv_seq != getattr(self, "_inv_seen", st.inv_seq):
            self._inv_seen = st.inv_seq
            from .gamestate import worn_list
            if st.carrying and not worn_list(st.carrying):
                return self.hangup("nothing worn or wielded (naked)")
        self._inv_seen = st.inv_seq
        self._low_hp_check()

    def _low_hp_check(self):
        """Hang up once when HP falls under the line. Coming back in still under it doesn't hang up
        again straight away (you'd never get back in) — it's re-armed once HP is back over the line.
        While it's disarmed, falling another 10% (something is hitting you) still hangs up."""
        st, cfg, s = self.s.state, self.cfg, self.s
        inside = s.telnet.connected and (getattr(s, "_entered", False) or not getattr(s, "_left_at", 0))
        if not inside:
            self._was_in = False
            return
        thr = cfg.hangup_hp_pct if cfg.hangup_low_hp else 0
        if not thr or thr <= 0 or not st.max_hp or st.hp is None:
            return
        if not self._was_in and getattr(st, "last_prompt", 0) <= getattr(s, "_connected_at", 0):
            return          # no HP prompt since we connected: what we have is from before the hang-up (full HP) —
                            # judging on it armed the check and the first real prompt hung up straight away (Evolution,
                            # 2026-11-01: hung up at 38/208 in an empty room the second it came back in)
        pct = st.hp_pct()
        if not self._was_in:
            self._was_in = True
            if 0 < pct < thr:
                self._hp_armed, self._hp_floor = False, pct
                s.log(f"Back in at {pct:.0f}% HP (under the {thr}% hang-up line) — not hanging up again; "
                      "it re-arms once HP is back over the line")
                return
        if pct >= thr:
            if self._hp_armed or self._hp_floor is None or pct >= thr + 3:
                self._hp_armed, self._hp_floor = True, None
            return          # (0.8.224, real logs: re-armed at 25.9%, then our own regen swap's 'remove platinum
                            #  ring' (+10 max HP) took it to 24.5% and hung up in an empty room — re-arm 3% over)
        if pct <= 0:
            return
        if self._hp_armed:
            self._hp_armed, self._hp_floor = False, pct
            self.hangup(f"HP {st.hp}/{st.max_hp} below {thr}%")
        elif self._hp_floor is not None and pct < self._hp_floor - 10:
            self._hp_floor = pct
            self.hangup(f"HP {st.hp}/{st.max_hp} still falling (under {thr}%)")

    def on_room(self, state):
        """'Also here:' list after a room display."""
        if not state.view or not self.s.telnet.connected:
            return
        if getattr(self, "_party_relog", None) and self._party_relog_look(state):
            return
        fr = self.friends()
        bad = [m.lower() for m in (self.cfg.hangup_monsters or []) if m.strip()]
        if bad:
            for sh, rec in state.view.monsters:
                nm = ((rec or {}).get("name") or sh).lower()
                if nm in bad:
                    return self.hangup(f"{(rec or {}).get('name') or sh} showed up (your hang-up list)")
        for p in state.view.players:
            nm = p.split()[0].strip(".,")
            if not self.is_player(nm) or nm.lower() in fr:
                continue
            if self.cfg.hangup_on_player:
                return self.hangup(f"player seen: {nm}")
            if self.cfg.hangup_on_enemy and self.s.players.relationship(nm) == "Enemy":
                return self.hangup(f"enemy seen: {nm}")

    def hangup(self, reason: str, manual: bool = False):
        cfg = self.cfg
        if getattr(cfg, "no_hang", False) and not manual:
            # pMUD's NoHang: one switch over every automatic hang-up (a boss, a quest step, a corpse run)
            now = time.time()
            if now - getattr(self, "_nohang_said", 0) > 30:
                self._nohang_said = now
                self.s.log(f"Would hang up — {reason} — but NoHang is on")
                self.s.on_alert(f"NoHang is on — NOT hanging up: {reason}")
                self.s.notify.send("hangup", f"NoHang on — stayed in: {reason}")
            self._pvp_hang = None
            return None
        self.last_reason = reason
        self.s.log(f"HANGING UP — {reason}")
        if hasattr(self.s, "timeline"):
            self.s.timeline.event("hangup", reason)
        self.s.on_alert(f"Hung up: {reason}")
        self.s.notify.send("hangup", f"Hung up: {reason}")
        if reason.lower().startswith("pvp") and cfg.pvp_tell_party:
            # pMUD: tell the party before going — a MegaMUD partner doesn't get your phone alert
            room = self.s.state.room
            where = f" at {room[0]}/{room[1]}" if room else ""
            me = (cfg.my_name or "").lower()
            for n in list(self.s.state.party)[:6]:
                if n.lower() != me:
                    try:
                        self.s.telnet.send_line(f"/{n} *Attacked*{where} — {reason[5:60]} — hanging up!")
                    except Exception:
                        pass
        me_ = (cfg.my_name or "").lower()
        in_party = any(n.lower() != me_ for n in (self.s.state.party or {}))
        self.s.remember_party()
        self.s.bot.stop(f"Hung up ({reason})")
        self.s.telnet.close()
        self.s.show_down(f"HUNG UP — {reason}")
        if self.is_pvp_reason(reason) and not manual:
            # 0.8.224 (Dan): NEVER back in by itself after a PvP hang-up — not with Relog instead of hanging, not
            # after Stay offline N minutes
            self.s.hold_realm = True
            self.s._want_connected = False
            self.hung_up_until = float("inf")
            self._party_relog = None
            return
        pr = getattr(self, "_party_relog", None)
        if pr and time.time() - pr.get("t", 0) > 600:
            pr = self._party_relog = None        # (an old one: this is a new bout)
        if reason.startswith("HP") and not manual and (in_party or pr):
            # 0.8.224 (Dan): a low-HP hang-up in a party — the party may well finish the fight (Miserable hung up
            # just as the last stonecap shattered and sat at the menu 3 h 45 min). Back in after a minute to look:
            # monsters still in the room = hang up again at once; twice at most, then offline for good
            n = (pr or {}).get("n", 0)
            if n < self.PARTY_RELOG_TRIES:
                self._party_relog = {"n": n + 1, "t": time.time(), "looked": False}
                self.s.hold_realm = False
                self.s._want_connected = True
                self.hung_up_until = time.time() + self.PARTY_RELOG_SECS
                self.s._closed_at = time.time() + self.PARTY_RELOG_SECS - cfg.reconnect_delay
                self.s._closed_at_kept_until = time.time() + 10
                self.s.log(f"Low-HP hang-up in a party — back in {self.PARTY_RELOG_SECS} s to see whether the party "
                           f"cleared the room (try {n + 1} of {self.PARTY_RELOG_TRIES}); monsters still there = "
                           "straight back out")
                return
            self._party_relog = None
            self.s.hold_realm = True
            self.s._want_connected = False
            self.hung_up_until = float("inf")
            self.s.log(f"Low-HP hang-up again after {self.PARTY_RELOG_TRIES} looks — staying offline until you "
                       "come back in yourself")
            return
        if not cfg.relog_instead_of_hang and float(cfg.hangup_stay_offline or 0) <= 0:
            # next connect waits at the MajorMUD menu for you. Not with "Stay offline N minutes" set: that's you
            # saying come back in after N minutes (2026-11-18: it reconnected and sat at the menu instead, so the
            # setting did nothing — Evolution stood offline all night after a low-HP hang-up)
            self.s.hold_realm = True
        if cfg.relog_instead_of_hang and reason.startswith("HP") and getattr(cfg, "stop_on_danger", True):
            # pMUD's Stop on Danger: relogging straight back in at low HP walks back into what nearly killed you
            self.s.hold_realm = True
            self.s.log("Low-HP hang-up: not relogging by itself (Stop on danger) — go back in when it's safe")
        elif cfg.relog_instead_of_hang:
            self.hung_up_until = time.time() + 5        # straight back in
            self.s._want_connected = True
            self.s._closed_at = time.time() - cfg.reconnect_delay + 5
            # (0.8.201, bug hunt: the reader thread's "closed" lands after this and reset _closed_at to now, so the
            #  5 s relog waited a full reconnect_delay — keep the time set here)
            self.s._closed_at_kept_until = time.time() + 10
            self.s.log("Relogging in 5 s (Relog instead of hanging is on)")
            return
        mins = float(cfg.hangup_stay_offline or 0)
        self.hung_up_until = time.time() + mins * 60 if mins > 0 else float("inf")
        if mins <= 0:
            self.s._want_connected = False       # stay down until you reconnect
        else:
            self.s._closed_at = time.time() + mins * 60 - cfg.reconnect_delay
            self.s._closed_at_kept_until = time.time() + 10     # (0.8.201, bug hunt: as above)

    PARTY_RELOG_SECS = 60
    PARTY_RELOG_TRIES = 2

    @staticmethod
    def is_pvp_reason(reason) -> bool:
        r = (reason or "").lower()
        return r.startswith(("pvp", "attacked by", "player seen", "enemy seen"))

    def _party_relog_look(self, state) -> bool:
        """Back in after a party low-HP hang-up: the first room display decides — monsters still here: out again."""
        pr = getattr(self, "_party_relog", None)
        if not pr or pr.get("looked") or not state.view:
            return False
        pr["looked"] = True
        mobs = [sh for sh, _r in (state.view.monsters or [])]
        if mobs:
            return bool(self.hangup(f"HP: {', '.join(mobs[:3])} still here after the relog") or True)
        self._party_relog = None
        self.s.log("Back in after the low-HP hang-up — the room's clear")
        return False

    def may_reconnect(self) -> bool:
        return time.time() >= self.hung_up_until
