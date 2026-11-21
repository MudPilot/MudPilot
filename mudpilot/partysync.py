"""Party sync between MudPilots: rest together instead of taking turns.

MegaMUD parties coordinate with @wait/@ok (and MudPilot still does that, so mixed parties work).
Between two MudPilots it goes further: each tells the other — quietly, by telepath — whether it's
resting and how its HP and mana stand. When one sits down, the other uses the time to top up too,
so the next rest isn't needed a minute later. Nothing is sent to anyone who isn't a MudPilot:
each party member gets one "@mpsync hi" per session, and only MudPilots answer it.

Wire format (party members only, hidden by the Conversations '@ / bot' filter):
    @mpsync hi                      → {mpsync ok <version>}
    @mpsync st r=1 h=62 m=40        resting?, HP %, mana % — sent when you sit down / get up, nothing between
    @mpsync lv … / sk …             spells tuned together (see spelltune.py)
    @mpsync lvl 47                  my level — on hi/ok and whenever it changes, so the leader routes on the
                                    party's lowest level (Negative Power Plane is level 40)
    @mpsync me lvl=47 hp=847 ma=408 ac=66 dr=15 dmg=520 cls=Druid   (once per teammate a session)
    @mpsync q 134=13 133=9          quest flags (ability id = value): all of them once per teammate a session, then
                                    each one that changes - their MudPilot logs and alerts "Revolution's quest flag:
                                    DaoLordQuest 12 -> 13" (Dan, 2026-11-09)
    @mpsync qwatch 600              the leader did something that may finish a quest step (say / ask / give...):
                                    read 'abil' every 30 s in quiet moments for that long, and tell any change
                                    about me — level, max HP/mana, AC/DR, my best attack spell's damage a round,
                                    class: the leader judges danger by the weakest member and the party's
                                    combined damage (Dan, 2026-10-28)
"""
from __future__ import annotations

import re
import time

from . import __version__

ST_RE = re.compile(r"r=(\d)\s+h=(\d+)\s+m=(\d+)")
LVL_RE = re.compile(r"\blvl[= ](\d+)")
FRESH = 900          # a rest is told when it starts and when it ends — no heartbeat (Dan: too many telepaths)
QWATCH_SECS = 600    # a quest watch: the party checks its flags for 10 minutes after the leader's quest-style command


class PartySync:
    def __init__(self, session):
        self.s = session
        self.peers: dict = {}          # name -> {"rest", "hp", "ma", "t"}
        self.asked: set = set()
        self._last_push = 0.0
        self._last_rest = None
        self._told_lvl = None
        for n, rec in (getattr(session.settings, "mpsync_peers", None) or {}).items():
            # their last stats, kept till they send newer: a restarted Buddy judged every lair as if alone — the
            # others had told the old Buddy and never again (Dan, 2026-11-03: 338 rooms round the Dirt Path)
            if isinstance(rec, dict) and (rec.get("me") or rec.get("lvl")):
                p = self.peers.setdefault(rec.get("name") or n, {"rest": 0, "hp": 100, "ma": 100, "t": 0})
                if rec.get("me"):
                    p["me"] = dict(rec["me"])
                if rec.get("lvl"):
                    p["lvl"] = int(rec["lvl"])

    def _my_lvl(self) -> str:
        lv = self.s.state.level
        if lv:
            self._told_lvl = lv
        return f" lvl={lv}" if lv else ""

    def _note_lvl(self, sender, text):
        m = LVL_RE.search(text or "")
        if m:
            p = self.peers.setdefault(sender, {"rest": 0, "hp": 100, "ma": 100, "t": time.time()})
            if p.get("lvl") != int(m.group(1)):
                p["lvl"] = int(m.group(1))
                self.s.log(f"Party sync: {sender} is level {p['lvl']}")
                self._keep(sender, p)
        return bool(m)

    ME_RE = re.compile(r"\b(lvl|hp|ma|ac|dr|dmg|str|pick|traps|rma)=(-?\d+)|\bcls=([A-Za-z-]+)")

    def _note_me(self, sender, text):
        p = self.peers.setdefault(sender, {"rest": 0, "hp": 100, "ma": 100, "t": time.time()})
        me = {}
        for k, v, cls in self.ME_RE.findall(text or ""):
            if cls:
                me["cls"] = cls
            elif k:
                me[k] = int(v)
        km = re.search(r"\bkit=([\d.]*)", text or "")
        if km:
            # the items each walker needs their own of that they carry (the golden idol): routing a party (0.8.190)
            me["kit"] = [int(x) for x in km.group(1).split(".") if x.isdigit()]
        if me:
            if me.get("lvl") and p.get("lvl") != me["lvl"]:
                p["lvl"] = me["lvl"]
            if p.get("me") != me:
                self.s.log(f"Party sync: {sender} — " + ", ".join(f"{k} {v}" for k, v in me.items()))
                p["me"] = me
                self._keep(sender, p)
            p["me"] = me

    def _keep(self, sender, p):
        """Remember a teammate's stats in the profile, so a restart still knows them."""
        d = getattr(self.s.settings, "mpsync_peers", None)
        if not isinstance(d, dict):
            d = {}
        d = {**d, sender.lower(): {"name": sender, "me": p.get("me") or {}, "lvl": p.get("lvl"), "t": time.time()}}
        self.s.settings.mpsync_peers = d
        self._save()

    def my_info(self) -> str:
        """'lvl=47 hp=847 ma=408 ac=66 dr=15 dmg=520 cls=Druid' — what the party leader needs to judge a fight."""
        s, st, cfg = self.s, self.s.state, self.s.settings
        dmg = 0
        try:
            best = 0
            mons = [m for m in (s.world.monster_names or {}).values() if m.get("hp")][:1]
            rows = s.spellbook.evaluate(list(s.spell_candidates()), mons[0], st.level or cfg.char_level or 1,
                                        s.bot.spellcasting(), cfg.spell_dmg_bonus) if mons else []
            for _sp, rated, _eff, _ratio, _c, _src in rows:
                best = max(best, int(rated or 0))
            dmg = best
        except Exception:
            dmg = 0
        cls = (st.char_class or cfg.char_class or "").replace(" ", "-")
        bits = [f"lvl={st.level}" if st.level else "", f"hp={st.max_hp}" if st.max_hp else "",
                f"ma={st.max_ma}" if st.max_ma else "", f"ac={st.ac}" if st.ac else "", f"dr={st.dr}" if st.dr else "",
                f"dmg={dmg}" if dmg else "", f"cls={cls}" if cls else "",
                f"str={st.strength}" if st.strength else "", f"pick={st.picklocks}" if st.picklocks else "",
                f"traps={st.traps}" if getattr(st, "traps", 0) else "",
                # my own 'Rest below MA' line: 0 = mana's a bonus (a melee Paladin) — the leader doesn't wait on it
                # (0.8.208, Dan: the walk sat waiting on Buddy's mana)
                f"rma={int(getattr(cfg, 'rest_below_ma', 0) or 0)}" if st.max_ma else ""]
        try:
            held = s.bot.held_items()
            if held is not None:
                # 'kit=1281': of the items every walker needs their own of (the golden idol), the ones we carry —
                # the leader only takes the idol teleport when every follower has one (0.8.190, Dan)
                bits.append("kit=" + ".".join(str(n) for n in sorted(set(held) & set(s.world.carry_item_set()))))
        except Exception:
            pass
        return " ".join(b for b in bits if b)

    def info(self) -> dict:
        """{member: {lvl, hp, ma, ac, dr, dmg, cls}} from party members' MudPilots."""
        party = {n.lower() for n in self.members()}
        return {n: p["me"] for n, p in self.peers.items() if p.get("me") and n.lower() in party}

    def levels(self) -> dict:
        """{member: level} for party members whose MudPilot told us its level."""
        party = {n.lower() for n in self.members()}
        return {n: p["lvl"] for n, p in self.peers.items() if p.get("lvl") and n.lower() in party}

    # ------------------------------------------------------------ inbound
    def command(self, sender, args) -> str | None:
        a = (args or "").strip()
        if a.startswith("hi"):
            if self._not_mudpilot().pop(sender.lower(), None):
                self._save()
            p = self.peers.setdefault(sender, {"rest": 0, "hp": 100, "ma": 100, "t": time.time()})
            p["t"] = time.time()
            if "tune" in a:
                p["tune"] = True
            self._note_lvl(sender, a)
            # they've (re)started: a new MudPilot knows nothing about us — tell them again on the next tick
            self._told_me = {k: v for k, v in getattr(self, "_told_me", {}).items() if k != sender.lower()}
            self._me_checked = 0
            return f"mpsync ok {__version__} tune{self._my_lvl()}"
        if a.startswith("lvl"):
            self._note_lvl(sender, a)
            return None
        if a.startswith("path "):
            return self.s.pathshare.receive(sender, a[5:])     # a path / loop sent to us (pathshare.py)
        if a.startswith("me "):
            self._note_me(sender, a)
            return None
        if a.startswith("q "):
            self._note_quest(sender, a[2:])
            return None
        if a.startswith("qwatch"):
            m = re.search(r"\d+", a)
            secs = min(int(m.group(0)) if m else QWATCH_SECS, 3600)
            b = self.s.bot
            first = getattr(b, "_quest_watch_until", 0) < time.time()
            b._quest_watch_until = time.time() + secs
            b._quest_poke = time.time()              # one read straight away (in a quiet moment)
            if first:
                self.s.log(f"Party sync: {sender} is on a quest step - checking your quest flags every "
                           f"{b.QUEST_WATCH_EVERY} s for {secs // 60} min")
            return None
        if self.s.spelltune.on_message(sender, a):
            return None
        m = ST_RE.search(a)
        if m:
            p = self.peers.setdefault(sender, {})
            p.update({"rest": int(m.group(1)), "hp": int(m.group(2)), "ma": int(m.group(3)), "t": time.time()})
        return None

    NOT_FOR = 7 * 24 * 3600      # don't ask a non-MudPilot again for a week (they say hi first if they switch)

    # ------------------------------------------------------------ quest flags
    Q_RE = re.compile(r"\b(\d{1,4})=(-?\d+)\b")

    def _peers_now(self) -> list:
        party = {m.lower() for m in self.members()}
        return [n for n in self.peers if n.lower() in party]

    def _send_q(self, n, flags: dict):
        bits = [f"{a}={v}" for a, v in sorted(flags.items(), key=lambda kv: int(kv[0]))]
        while bits:                                  # one telepath line each (the board cuts long ones)
            line, bits = bits[:12], bits[12:]
            self.s.send(f"/{n} @mpsync q {' '.join(line)}", from_bot=True)

    def tell_quest(self, gained: dict) -> set:
        """Our quest flags changed: tell every MudPilot in the party. Returns who was told (lower case)."""
        if not getattr(self.s.settings, "party_sync", True):
            return set()
        told = set()
        for n in self._peers_now():
            self._send_q(n, gained)
            told.add(n.lower())
        return told

    def quest_read(self, granted: dict):
        """A fresh 'abil' read: a teammate we haven't told our quest flags this session gets them all, once."""
        if not getattr(self.s.settings, "party_sync", True):
            return
        b = self.s.bot
        flags = {a: v for a, v in granted.items() if b.is_quest_flag(a)}
        if not flags:
            return
        told = getattr(self, "_q_told", {})
        for n in self._peers_now():
            if n.lower() not in told:
                self._send_q(n, flags)
                told[n.lower()] = True
        self._q_told = told

    def quest_watch(self, secs=None):
        """Leading, we did something that may finish a quest step: the party's MudPilots check their flags for a
        while. Once a minute at most."""
        if not getattr(self.s.settings, "party_sync", True):
            return
        now = time.time()
        if now - getattr(self, "_qwatch_sent", 0) < 60:
            return
        peers = self._peers_now()
        if not peers:
            return
        self._qwatch_sent = now
        for n in peers:
            self.s.send(f"/{n} @mpsync qwatch {int(secs or QWATCH_SECS)}", from_bot=True)

    def _note_quest(self, sender, text):
        """A teammate's quest flags: remember them; one that went up (or changed) is said, and alerted."""
        p = self.peers.setdefault(sender, {"rest": 0, "hp": 100, "ma": 100, "t": time.time()})
        had = p.get("q")
        q = dict(had or {})
        changes = []
        b = self.s.bot
        for a, v in self.Q_RE.findall(text or ""):
            v = int(v)
            if had is not None and a in had and had[a] != v:
                changes.append(f"{b.flag_name(a)} {had[a]} \u2192 {v}")
            elif had is not None and a not in had:
                changes.append(f"{b.flag_name(a)} = {v} (new)")
            q[a] = v
        p["q"] = q
        if changes:
            msg = f"{sender}'s quest flag: " + ", ".join(changes)
            self.s.log("Party sync: " + msg)
            try:
                self.s.notify.send("quest", msg)
            except Exception:
                pass
        elif had is None and q:
            self.s.log(f"Party sync: {sender}'s quest flags: " + ", ".join(
                f"{b.flag_name(a)} {v}" for a, v in sorted(q.items(), key=lambda kv: int(kv[0]))))

    def quest_flags(self) -> dict:
        """{member: {ability id: value}} - what the party's MudPilots last told us."""
        party = {n.lower() for n in self.members()}
        return {n: dict(p["q"]) for n, p in self.peers.items() if p.get("q") and n.lower() in party}

    def _not_mudpilot(self) -> dict:
        d = getattr(self.s.settings, "mpsync_not", None)
        if not isinstance(d, dict):
            d = {}
            self.s.settings.mpsync_not = d
        return d

    def answer(self, sender, msg) -> bool:
        """'{mpsync ok …}' — they're a MudPilot. '{command invalid or not allowed}' just after asking —
        they're on MegaMUD: note it, so they don't get asked every session."""
        low = msg.strip("{} ").lower()
        asked = getattr(self, "_asked_at", {}).get(sender.lower(), 0)
        if asked and time.time() - asked < 20 and ("invalid" in low or "not allowed" in low):
            self._asked_at.pop(sender.lower(), None)
            self._not_mudpilot()[sender.lower()] = time.time()
            self._save()
            self.s.log(f"Party sync: {sender} isn't running MudPilot — won't ask again this week "
                       "(if they start, their MudPilot says hi first)")
            return True
        if low.startswith("mpsync ok") and sender.lower() not in {n.lower() for n in self.members()} and \
                not (asked and time.time() - asked < 120):
            # (0.8.201, bug hunt: any stranger's '{mpsync ok lvl=1}' went into peers and saved the profile, a fake
            #  level and a settings save per line — only a party member, or someone we just asked, answers this)
            return False
        if low.startswith("mpsync ok"):
            self._not_mudpilot().pop(sender.lower(), None)
            p = self.peers.setdefault(sender, {"rest": 0, "hp": 100, "ma": 100, "t": time.time()})
            p["tune"] = " tune" in msg.lower()      # 0.8.32+: tunes spells together with us
            p["t"] = time.time()
            self._note_lvl(sender, msg)
            self.s.log(f"Party sync: {sender} runs MudPilot — resting together from now on")
            self._last_rest = None                  # tell the new MudPilot where we stand once
            return True
        return False

    def _save(self):
        try:
            self.s.settings.save()
        except Exception:
            pass

    # ------------------------------------------------------------ state
    def members(self):
        me = (self.s.settings.my_name or "").lower()
        return [n for n in self.s.state.party if n.lower() != me]

    def peer_resting(self) -> str | None:
        """A MudPilot party member who's resting right now: 'par' marks them — "[H: 94%]R" resting, "M"
        meditating (Dan, 2026-10-28: no need to telepath it). An older MudPilot's "@mpsync st" still counts."""
        now = time.time()
        me = (self.s.settings.my_name or "").lower()
        for n, rec in (self.s.state.party or {}).items():
            if n.lower() != me and now - (rec or {}).get("t", 0) < 60 and \
                    set((rec or {}).get("flags") or "") & {"R", "M"} and n.lower() in {p.lower() for p in self.peers}:
                return n
        party = {n.lower() for n in self.members()}
        for n, p in self.peers.items():
            if p.get("rest") and now - p.get("t", 0) < FRESH and n.lower() in party:
                return n
        return None

    def tick(self):
        s, cfg = self.s, self.s.settings
        if not cfg.party_sync or not s.telnet.connected or not s._entered:
            return
        now = time.time()
        skip = self._not_mudpilot()
        for n in self.members():
            if n.lower() not in self.asked:
                self.asked.add(n.lower())
                if now - skip.get(n.lower(), 0) < self.NOT_FOR:
                    continue                         # on MegaMUD last time we asked
                self._asked_at = {**getattr(self, "_asked_at", {}), n.lower(): now}
                s.send(f"/{n} @mpsync hi tune{self._my_lvl()}", from_bot=True)
        peers = [n for n in self.peers if n.lower() in {m.lower() for m in self.members()}]
        if not peers:
            return
        st = s.state
        if st.level and st.level != self._told_lvl:  # levelled (or wasn't known at hi/ok): tell them
            for n in peers:
                s.send(f"/{n} @mpsync lvl {st.level}", from_bot=True)
            self._told_lvl = st.level
        if now - getattr(self, "_me_checked", 0) > 60:
            self._me_checked = now
            info = self.my_info()
            told = getattr(self, "_told_me", {})
            skills = lambda i: re.findall(r"\b(?:str|pick|traps|rma)=\d+|\bkit=[\d.]*", i or "")
            for n in peers:
                # once per teammate (Dan) — a level-up has its own 'lvl'; again only when strength / picklocks / traps
                # change (or turn up: 'st' hadn't been read the first time — the leader never knew who could bash)
                if info and (n.lower() not in told or skills(told[n.lower()]) != skills(info)):
                    s.send(f"/{n} @mpsync me {info}", from_bot=True)
                    told[n.lower()] = info
            self._told_me = told
        resting = bool(st.resting)
        # (no "@mpsync st" any more: who's resting, their HP and mana are all in 'par' — "[H: 94%]R")
        self._last_rest = resting
