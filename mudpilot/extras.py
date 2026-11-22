"""More MegaMUD behaviours, kept out of automation.py's main loop:

* cures (poison, blindness, disease, held/webbed) and the Spells-tab extras
  (HP/mana regen when resting, a spell when HP/mana tops out, max attack casts per fight)
* party: party blesses, @wait/@ok while resting, leader waits for the party, attack
  what the leader attacks, help bash, share cash, @panic when running, par after combat
* PvP spells: a prioritised list cast each round at a player (e.g. mystic mist every
  25 rounds, sleep every round), then melee
* auto-roam: wander through allowed exits, opening doors where allowed
"""
from __future__ import annotations

import random
import re
import time

from .gamestate import CHAT_LINE_RE
from .worlddb import DIR_WORDS, norm_dir


def room_text(txt):
    r"""'14/6534' as a (map, room) key, and also '14\6534', '14 6534', '14,6534', '14-6534'. 0.8.200: Miserable's
    Stonecaps stash was typed as '14\6534'; only '/' was read, so the loop had no stash room and kept its cash."""
    m = re.match(r"^\s*(\d+)\s*[/\\,\s-]\s*(\d+)\s*$", txt or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def coin_kind_(name):
    from .gamestate import coin_kind
    return coin_kind(name)


def parse_carry(text):
    from .gamestate import parse_item_list
    return parse_item_list(text or "")

STATUS_RES = {
    # ("You feel sick." is the rotting beholder's stench, not poison — gamestate.sick has it; as poison it cast
    #  cure poison every 4 s and "You feel less sick." never cleared it. 0.8.201, bug hunt)
    "poison": (re.compile(r"you (?:are|have been|were) poisoned|poison (?:courses|seeps)", re.I),
               re.compile(r"no longer poisoned|poison (?:wears off|is cured|leaves)|you feel (?:much )?better|cured? (?:of )?(?:the )?poison", re.I)),
    "blind": (re.compile(r"you (?:are|have been|go) blind|you can'?t see a thing|you are blinded|blinds you", re.I),
              re.compile(r"(?:you can|able to) see again|no longer blind|your (?:sight|vision) (?:returns|clears)", re.I)),
    "disease": (re.compile(r"you (?:are|have been|feel) diseased|you feel (?:feverish|a disease)|disease (?:takes|spreads)", re.I),
                re.compile(r"no longer diseased|disease (?:wears off|is cured|leaves)|fever breaks", re.I)),
    "held": (re.compile(r"you are (?:held|paralyz|webbed|entangled|stuck)|you can'?t move|holds you in place", re.I),
             re.compile(r"you can move again|you (?:are|break) free|no longer (?:held|paralyz|webbed|entangled)", re.I)),
    "confused": (re.compile(r"you (?:are|feel) confused", re.I), re.compile(r"no longer confused|mind clears", re.I)),
    "knocked": (re.compile(r"you are knocked (?:off your feet|down|to the ground)|you are flat on your back", re.I),
                re.compile(r"you (?:get|climb|scramble|struggle) back (?:on|onto|to) your feet|you stand (?:back )?up", re.I)),
    "stunned": (re.compile(r"^you are stunned|^you have been stunned|stuns you\b", re.I),
                re.compile(r"no longer stunned|you (?:recover|shake off) (?:from )?(?:the |your )?stun", re.I)),
}
WEAR_OFF_RE = re.compile(r"wears? off|no longer|fades?\b|dissipates?|disappears?|vanish|returns? to normal|less (?:protected|"
                         r"evasive|quick)|you feel (?:less|weaker|slower|vulnerable)", re.I)
OTHER_OUTPUT_RE = re.compile(r"travel party|^obvious exits|^also here|^you notice|^\[|experience|^\*combat|"
                             r"^you (?:gain|hit|miss)|^the following|telepaths|gossips|says|^\w+ just ", re.I)
# party / movement / state lines that say "no longer" but are never a bless (Dan, 2026-11-12: PVEREV's crozier
# learned "You are no longer following Evolution." as divine intervention's wear-off, so it was never recast)
NOT_BLESS_RE = re.compile(r"follow|party|\bgroup\b|no longer (?:hidden|sneaking|resting|meditating|afk|in |on |at )|"
                          r"you (?:stop|are no longer) (?:resting|meditating|sneaking|hiding)|^-- ", re.I)
# a hit is never a wear-off: "A fire elemental appears and scorches X for 300 damage, then vanishes!"
DAMAGE_RE = re.compile(r"\bfor \d+ damage\b", re.I)
CAST_NOISE_RE = re.compile(r"^(?:you cast|you attempt|you don't have|you can't|huh\?|\[hp=|obvious exits|also here|you notice)", re.I)
PICKUP_RE = re.compile(r"^You picked up (\d+) (.+?)\.?$", re.I)
BASH_RE = re.compile(r"^([A-Z][a-z]+) (?:bashes|smashes|tries to bash|throws (?:him|her)self against) (?:the |a )?(?:\w+ )?"
                     r"(?:door|gate|portcullis)[^.]*?\b(north(?:east|west)?|south(?:east|west)?|east|west|up|down|above|below)", re.I)
PVP_ON_RE = re.compile(r"^([A-Z][a-z]+)\s+(?:swings|attacks|hits|slashes|smashes|stabs|bashes|punches|kicks|strikes|lunges|"
                       r"casts|fires|shoots|backstabs|crushes|cuts|pierces|whips|clubs|jumpkicks)\b.*?\b([A-Z][a-z]+)\b")
DEAD_RE = re.compile(r"^([A-Z][a-z]+) (?:collapses|falls to the ground|is dead|dies|has been slain)", re.I)


class Extras:
    def __init__(self, bot):
        self.b = bot
        self.ailments: dict = {}          # name -> since
        from .partycare import PartyCare
        self.care = PartyCare(self)
        self._was_full_hp = self._was_full_ma = True
        self._casts_this_fight = 0
        self._pblessed: dict = {}         # (cast, name) -> time cast
        self.pvp_target: str | None = None
        self.pvp_seen = 0.0
        self._pvp_cast: dict = {}         # cast -> time
        self._sent_wait = False
        self._wait_since = 0.0
        self._left_behind = None
        self._behind_since = 0.0
        self._leader_gone_since = 0.0
        self._followed = None
        self._leader_target = None        # (monster word, time)
        self.roaming = False
        self.waiting_on: list = []
        self._roam_from = None
        self._roam_cmd_room = None
        self._last_cast_buff = None       # (buff key, time) — to learn its start message
        self._bless_active: dict = {}     # buff key -> since
        self._was_combat = False
        self.looted: set = set()          # items the Get button picked up this session (to stash)
        self.held_for_me: dict = {}       # member -> {item: count} they picked up because it was too heavy for us

    @property
    def st(self):
        return self.b.st

    @property
    def cfg(self):
        return self.b.cfg

    def send(self, c):
        self.b.send(c)

    def me(self):
        return (self.cfg.my_name or "").lower()

    def leader(self) -> str | None:
        cfg, st = self.cfg, self.st
        if cfg.party_leader:
            return None if cfg.party_leader.lower() == self.me() else cfg.party_leader
        fl = getattr(self, "_following", None)     # "You are now following Revolution."
        if fl and (not st.party or any(n.lower() == fl.lower() for n in st.party)):
            return fl
        first = next(iter(st.party), None)         # MajorMUD lists the leader first
        return first if first and first.lower() != self.me() else None

    def leading(self) -> bool:
        st = self.st
        if not st.party:
            return False
        if self.cfg.party_leader:
            return self.cfg.party_leader.lower() == self.me()
        return self.b.walking or self.roaming or getattr(self, "_own_party", False)

    # ------------------------------------------------------------ leader gone
    LEADER_LEFT_RE = re.compile(r"^([A-Z][a-z]+) just (left the Realm|disconnected|hung up|logged off)", re.I)
    LEADER_BACK_RE = re.compile(r"^([A-Z][a-z]+) just entered the Realm", re.I)
    BEHIND_SECS = 30
    WALKS_IN_RE = re.compile(r"^([A-Z][a-z]+) (?:walks|sneaks|runs|wanders) into the room from", re.I)
    WALKED_IN_SECS = 8

    def _walk_in_break(self, t, now):
        """Someone outside the party walks in — or logs back in here ("Miserable walks into the room from nowhere")
        — on a PvP realm: no area spells from this moment (walked_in() holds them until the room list shows who's
        here), and if the game is repeating our area spell, break off at once so the next round doesn't hit them.
        Dan, 2026-11-18: Miserable logged back in where he'd hung up, straight into Revolution's tempest; holding
        area spells the whole time a member is out would cost too much in rooms that spawn big."""
        cfg, st = self.cfg, self.st
        if not cfg.pvp_realm:
            return
        m = self.WALKS_IN_RE.match(t)
        if not m:
            return
        n = m.group(1)
        if n.lower() == self.me() or any(n.lower() == x.lower() for x in (st.party or [])):
            return
        self._walked_in = (n, now)
        if not st.in_combat or not cfg.break_cmd or now - (getattr(self.b, "_area_cast_t", 0) or 0) > 60:
            return
        self.b._area_cast_t = 0
        self.b.log(f"{n} walked in while the area spell is repeating — breaking off so it doesn't hit them")
        self.b.send(cfg.break_cmd)

    def walked_in(self, now=None) -> str | None:
        """Who walked in just now (under 8 s, until a fresh room list says who's here)."""
        w = getattr(self, "_walked_in", None)
        now = now or time.time()
        if not w or now - w[1] > self.WALKED_IN_SECS:
            return None
        v = self.st.view
        if v is not None and (v.t or 0) > w[1] + 0.5:
            return None                       # the room list after they came in: aoe_blocked reads the players there
        return w[0]

    def _leader_lines(self, t, now):
        self._walk_in_break(t, now)
        fl = getattr(self, "_following", None) or getattr(self, "_followed", None)
        m = self.LEADER_LEFT_RE.match(t)
        if m and not getattr(self, "_following", None) and \
                now - (getattr(self, "_followed_t", 0) or 0) >= self.b.s.LEADER_MEMORY:
            # someone we followed hours ago isn't our leader any more: their logging off and back on mustn't send
            # us across the realm to them (Evolution, 2026-11-21: camping outside Lallim, 3.5 h after leaving
            # Miserable's party — Miserable restarted for an update and Evolution walked 481 steps, through 10
            # dangerous lairs, to the zombie pen)
            fl = None
        tr = getattr(self.b.s, "training", None)
        if m and fl and m.group(1).lower() == fl.lower() and tr is not None and tr.holding_comeback() \
                and m.group(2).lower() == "left the realm":
            # the leader went to train (its 'trip on' came first): a realm excursion, back in a moment and it
            # invites us again — no alarm, no waiting game (0.8.200 auto-train)
            self._followed = fl
            self.b.log(f"Leader {fl} is training — waiting for its invite")
            return
        if m and fl and m.group(1).lower() == fl.lower():
            self._followed = fl
            self._leader_gone_since = now
            why = m.group(2).lower()
            self.b.log(f"Leader {fl} {why} — staying put and resting up")
            self.b.s.notify.send("leader", f"{fl} (your party leader) {why}. Waiting where we are.")
            self.b.s.on_alert(f"Leader {fl} {why}")
            return
        m = self.LEADER_BACK_RE.match(t)
        if m and getattr(self, "_leader_gone_since", 0) and m.group(1).lower() == (fl or "").lower():
            self._leader_gone_since = 0
            self.b.log(f"Leader {m.group(1)} is back in the Realm — asking for an @invite, then @rego")
            self.b.s.notify.send("leader", f"{m.group(1)} is back in the Realm")
            # Dan, 2026-10-29: Buddy stood in Revolution's room for 8 minutes after Revolution came back, waiting
            # to be invited — ask, join, then @rego them (same as after our own restart)
            self.b.s._rejoin = {"leader": m.group(1), "t": now, "asked": now - 15, "tries": 0, "joined": False,
                                "ask_first": True}

    @property
    def leader_gone(self) -> str | None:
        """Our leader logged off / dropped, or we've been left behind in another room."""
        if not self.cfg.leader_watch:
            return None
        fl = getattr(self, "_followed", None)
        if getattr(self, "_leader_gone_since", 0) and fl:
            return f"{fl} left the Realm"
        return getattr(self, "_left_behind", None)

    def portal_follow(self) -> bool:
        """The leader stepped through a portal that breaks the party (the Negative Power Plane vortex):
        go through after them. The leader invites us again on the far side (Join if invited / @join)."""
        pw = getattr(self, "_portal_watch", None)
        st = self.st
        if not pw:
            return False
        tr = getattr(self.b.s, "training", None)
        if tr is not None and tr.holding_comeback():
            self._portal_watch = None                 # the party broke for a training trip, not a portal (0.8.200)
            return False
        now = time.time()
        if now - pw["t"] > 10 or not self.cfg.party_teleport_bring or st.in_combat:
            self._portal_watch = None
            return False
        if now - pw["t"] < 1.0 or not st.view or (pw["room"] and st.room and st.room != pw["room"]):
            return False
        if any(pw["leader"].lower() == p.split()[0].strip(".,*").lower() for p in (st.view.players or []) if p):
            return False                              # still here — it was a plain disband
        r = self.b.s.world.room(st.room) if st.room else None
        cmds = []
        for ex in (r.exits.values() if r else []):
            if ex.kind == "text" and ex.text_commands:
                cmds.append(ex.text_commands)
        word = (pw.get("word") or ("", 0))[0]
        pick = None
        if word:
            pick = next((c[0] for c in cmds if any(w in " ".join(c).lower() for w in word.split()[-1:])), None)
        if pick is None and len(cmds) == 1:
            pick = cmds[0][0]
        self._portal_watch = None
        if not pick:
            return False
        self.b.log(f"{pw['leader']} went through ('{pick}') and the party broke — following")
        self.send(pick)
        return True

    def leader_watch(self):
        """Following someone and they're not in our room any more for a while (we got left behind:
        resting, held, a door): say so once, and on the phone."""
        cfg, st = self.cfg, self.st
        if self.portal_follow():
            return
        fl = getattr(self, "_following", None)
        if fl:
            self._followed = fl
            self._followed_t = time.time()
        if not cfg.leader_watch or not fl or self.b.walking or st.in_combat or not st.view:
            self._behind_since = 0
            self._left_behind = None
            return
        here = {p.lower() for p in (st.view.players or [])}
        # a pitch-black room shows nobody — that's not the leader gone (Revolution, 2026-11-06, in the Frozen
        # Cavern's Dark Hole with Miserable right there: '@wait', 'Miserable isn't here — left behind')
        dark = st.view.name == "(dark)" or time.time() - (getattr(st, "dark_at", 0) or 0) < 5
        if dark or fl.lower() in here or any(fl.lower() in p for p in here):
            self._behind_since = 0
            if self._left_behind:
                self.b.log(f"Back with {fl}")
            self._left_behind = None
            return
        now = time.time()
        if not getattr(self, "_behind_since", 0):
            self._behind_since = now
        if now - self._behind_since >= self.BEHIND_SECS and not self._left_behind:
            self._left_behind = f"{fl} isn't here — left behind"
            self.b.log(f"Following {fl} but they haven't been in this room for {self.BEHIND_SECS} s — waiting here")
            self.b.s.notify.send("leader", f"Left behind: {fl} hasn't been in the room for {self.BEHIND_SECS} s")
            if cfg.leader_gone_wait_cmd:
                self.send(cfg.leader_gone_wait_cmd.replace("{name}", fl))

    def say_party(self, msg):
        self.send(f"bg {msg}")

    # ------------------------------------------------------------ lines
    def note_line(self, text: str):
        t = text.strip()
        low = t.lower()
        st, cfg = self.st, self.cfg
        now = time.time()
        # an item spell that needs the item in hand: equip it, use it, put the weapon back — and remember
        if re.search(r"must (?:be )?(?:have|hold|wield|equip|wear)\w*.*(?:to (?:use|cast)|equipped)|"
                     r"not (?:equipped|wielding|holding) (?:that|it)", low):
            self._fix_item_bless()
        # Paradigm's 'stat' lists what's up and for how long: "You feel armoured! (111s)"
        mt = re.match(r"^(.+?[!.])\s*\((?:(\d+)s|(\d+):(\d\d)|(\d+)m\s*(\d+)s)\)$", t)
        if mt:
            secs = int(mt.group(2)) if mt.group(2) else (int(mt.group(3)) * 60 + int(mt.group(4))) if mt.group(3) \
                else int(mt.group(5)) * 60 + int(mt.group(6))
            self._sync_bless(mt.group(1).strip().lower(), secs)
            if getattr(self, "_stat_block", None):
                self._stat_block["seen"].add(mt.group(1).strip().lower().rstrip("!. "))
        sb_ = getattr(self, "_stat_block", None)
        if sb_ is not None and now - sb_["t"] < 3:
            if low.startswith("willpower:") or " willpower:" in low:
                sb_["effects"] = True                # what follows is the list of what's on you now
            elif sb_.get("effects") and t and not t.startswith("["):
                sb_.setdefault("lines", []).append(low)
        if "lives/cp" in low and low.startswith("name:"):
            # the 'st' listing starts: whatever bless isn't in its effects list is down (pMUD) — catches a
            # dispel or a wear-off line we missed
            self._stat_block = {"t": now, "seen": set()}
        # whose party is it? (the leader can't change rank — don't keep trying)
        if low.startswith("you may not leave your current rank in your own party"):
            self._own_party, self._rank_tries = True, 99
        elif re.match(r"^you have invited \w+ to follow you|^\w+ started to follow you", low):
            self._own_party = True
        if re.match(r"^you are no longer in a party|^you have left the party|^you leave the party|"
                    r"^your party has been disbanded|^\w+ is no longer following you|^you are no longer following", low):
            self._party_broke_at = time.time()
            ld = getattr(self, "_following", None)
            if ld and not self.leading():
                # following, and the party broke: if the leader just stepped through a portal, go after them
                self._portal_watch = {"leader": ld, "t": time.time(), "room": st.room,
                                      "word": getattr(self, "_leader_went", None)}
        mw = re.match(r"^([A-Z][a-z]+) (?:steps|walks|jumps|dives|climbs|disappears|vanishes|leaps) (?:in|into|through) "
                      r"(?:the |a |an )?(.+?)[.!]?$", t)
        if mw and getattr(self, "_following", None) and mw.group(1).lower() == self._following.lower():
            self._leader_went = (mw.group(2).lower(), time.time())
            pw = getattr(self, "_portal_watch", None)
            if pw and pw["leader"].lower() == mw.group(1).lower():
                pw["word"] = self._leader_went
        if re.match(r"^you are now following|^you are no longer in a party|^you are not in a party|"
                      r"^you have left the party|^you leave the party|^your party has been disbanded|"
                      r"^you are no longer following", low):
            self._own_party = False
            mf = re.match(r"^you are now following (\w+)", low)
            self._following = mf.group(1).capitalize() if mf else None
            if mf:
                self._followed, self._leader_gone_since, self._left_behind = self._following, 0, None
                self._followed_t = time.time()
                if self.b.walking:
                    # joined someone's party: they lead now — our own Go to / loop stops (Buddy ran off on a
                    # Go to after joining Revolution's party), and Rego has nothing of ours to pick back up
                    self.b.stop(f"Joined {self._following}'s party — stopping my own walk to follow them")
                    self.b.resume = None
            if not mf:
                self._sent_wait = False
        self._leader_lines(t, now)
        md = re.match(r"^([A-Z][a-z]+) drops to the ground!", t)
        if md and cfg.aid_party and md.group(1).lower() != self.me() and \
                any(n.lower() == md.group(1).lower() for n in st.party) and \
                now - getattr(self, "_aided", {}).get(md.group(1).lower(), 0) > 20:
            # bleeding out: 'aid' stops the bleeding — the heal can come after
            self._aided = {**getattr(self, "_aided", {}), md.group(1).lower(): now}
            self.b.log(f"{md.group(1)} dropped — aiding")
            self.send(f"aid {md.group(1)}")
        talk = bool(CHAT_LINE_RE.match(t))     # "Bob gossips: you are poisoned lol" isn't your poison
        for name, (on, off) in (() if talk else STATUS_RES.items()):
            if off.search(t):
                if self.ailments.pop(name, None):
                    self.care.report_mine(name, False)
            elif on.search(t):
                if name == "stunned":
                    self.ailments[name] = now        # stunned again: the clock starts over
                else:
                    if name not in self.ailments:
                        self.care.report_mine(name, True)
                    self.ailments.setdefault(name, now)
        self.care.feed_line(t)
        # bless start / wear-off messages: the line right after "You cast ..." is the start
        # message candidate; it's only kept once two casts in a row agree on it.
        lc = self._last_cast_buff
        if lc and now - lc[1] < 3:
            if re.match(r"^you cast\b", low):
                self._last_cast_buff = (lc[0], now, True)
            elif len(lc) > 2 and t and not CAST_NOISE_RE.search(t) and not OTHER_OUTPUT_RE.search(t) and len(t) < 120:
                b = next((x for x in cfg.buffs or [] if x.get("cast") == lc[0]), None)
                theirs = any((x.get("on_msg") or "").strip() == t for x in cfg.buffs or [] if x.get("cast") != lc[0])
                room = (getattr(st.view, "name", "") or "").strip().lower() if st.view else ""
                plausible = re.search(r"\byou", low) and low.strip() != room and not NOT_BLESS_RE.search(t)
                if b is not None and not (b.get("on_msg") or "").strip() and not theirs and plausible:
                    if b.get("_on_candidate") == t:
                        b["on_msg"] = t
                        b["on_msg_learned"] = True
                        b.pop("_on_candidate", None)
                        self.b.log(f"Learned how '{b.get('name') or lc[0]}' starts: \"{t}\"")
                    else:
                        b["_on_candidate"] = t
                self._last_cast_buff = None
        for b in cfg.buffs or []:
            key = b.get("cast", "")
            on = (b.get("on_msg") or "").strip().lower()
            off = (b.get("off_msg") or "").strip().lower()
            if on and on in low:
                self._bless_active[key] = now
                self.b._buff_off.pop(key, None)
            if off and off in low:
                self._bless_active.pop(key, None)
        if WEAR_OFF_RE.search(t) and not CAST_NOISE_RE.search(t) and not DAMAGE_RE.search(t) and \
                not NOT_BLESS_RE.search(t):
            self._learn_off(t)
        mo = re.match(r"^(\w+) picks up (?:an? |the |some )?(.+?)\.?$", t)
        if mo and mo.group(1) in (st.party or {}) and not coin_kind_(mo.group(2)):
            # 0.8.200 (Dan): a member picked up what was too heavy for us — an Auto-stash item goes in our stash
            want = {k[1] for k in getattr(self.b, "_grab_asked", {})}
            got = mo.group(2).strip().lower()
            if got in want and any(w in got for w in self.stash_flagged_names()):
                d = self.held_for_me.setdefault(mo.group(1), {})
                d[mo.group(2).strip().lower()] = d.get(mo.group(2).strip().lower(), 0) + 1
        mp_ = re.match(r"^You (?:picked up|took) (?:an? |the |some |\d+ )?(.+?)\.?$", t, re.I)
        if mp_ and not coin_kind_(mp_.group(1)):
            self.looted.add(mp_.group(1).strip().lower())
        if PICKUP_RE.match(t) and cfg.share_cash and st.party:
            m = PICKUP_RE.match(t)
            if any(c in m.group(2).lower() for c in ("copper", "silver", "gold", "platinum", "runic")):
                self.send(cfg.share_cmd.replace("{qty}", m.group(1)).replace("{item}", m.group(2)))
        m = BASH_RE.match(t)
        if m and cfg.help_bash and st.party and m.group(1) in st.party and m.group(1).lower() != self.me():
            d = norm_dir(m.group(2)) or {"above": "U", "below": "D"}.get(m.group(2).lower())
            if d and self.b.ready("helpbash", 2):
                self.send(cfg.bash_cmd.replace("{dir}", DIR_WORDS[d]))
        # attack what the leader attacks
        ld = self.leader()
        if ld and t.startswith(ld + " ") and st.view:
            for shown, _rec in st.view.monsters:
                if shown.lower() in low:
                    self._leader_target = (shown, now)
                    break
        # someone attacks a party member / you
        m = PVP_ON_RE.match(t)
        if m and re.match(r"^\w+\s+casts\b", t) and not DAMAGE_RE.search(t):
            m = None                         # a heal / bless on them (Buddy, 2026-10-31: went for Revolution over a heal)
        if m and st.view:
            att, vic = m.group(1), m.group(2)
            players = {p.split()[0].strip(".,") for p in st.view.players}
            if att in players and att not in st.party:
                if vic.lower() == "you" or "you" in low.split():
                    if cfg.pvp_auto_fight and not cfg.hangup_on_pvp:
                        self.start_pvp(att, "attacked you")
                elif vic in st.party and (cfg.defend_party_pvp or not cfg.hangup_on_pvp):
                    self.start_pvp(att, f"attacked {vic}")
        m = DEAD_RE.match(t)
        if m and self.pvp_target and m.group(1).lower() == self.pvp_target.lower():
            self.b.log(f"PvP: {self.pvp_target} is down")
            self.stop_pvp()
        if "*combat off*" in low:
            self._casts_this_fight = 0
            if cfg.par_after_round and st.party:
                self.b._cool["par"] = 0

    def _learn_off(self, line):
        """A wear-off line arrives: tie it to the one active bless that has no wear-off text yet
        and has been up for at least half its duration."""
        from .spells import spell_duration
        now = time.time()
        low = line.lower()

        def names(b):
            sp = self.b.spell_for_cast(b.get("cast", "")) if b.get("cast") else None
            out = {(b.get("name") or "").strip().lower()}
            if isinstance(sp, dict):
                out.add((sp.get("Name") or sp.get("name") or "").strip().lower())
            return {n for n in out if len(n) > 3}
        if any((b.get("off_msg") or "").strip().lower() == low.strip() for b in self.cfg.buffs or []):
            return                          # already another bless's wear-off ("The effects of magic armour…")
        owner = self._msg_rule_for_end(low)
        if owner is not None:
            # the Messages file says whose line this is: that bless's, if it's one of yours (blur's "Your image is
            # no longer blurred"); a line of something else (poison, confusion…) never goes on a bless
            on_ = self._norm_msg(owner.get("start"))
            mine = [b for b in self.cfg.buffs or [] if self._norm_msg(owner.get("name")) in
                    {self._norm_msg(n) for n in names(b)} or (on_ and self._norm_msg(b.get("on_msg")) == on_)]
            if len(mine) != 1:
                return
            named = mine
        else:
            # "The mana flux dissipates rapidly." belongs to Mana flux, never to whichever other bless is up
            named = [b for b in self.cfg.buffs or [] if any(n in low for n in names(b))]
        cands = []
        for b in named or self.cfg.buffs or []:
            if (b.get("off_msg") or "").strip():
                continue
            if named:
                cands.append(b)
                continue
            key = b.get("cast", "")
            cast_at = self.b._buff_cast.get(key, 0)
            sp = self.b.spell_for_cast(key) if key else None
            dur = spell_duration(sp, self.cfg.char_level or self.st.level) or 0
            if cast_at and dur and now - cast_at >= dur * 0.5:
                cands.append(b)
        if len(cands) == 1:
            b = cands[0]
            b["off_msg"] = line
            b["off_msg_learned"] = True
            self.b._buff_off[b.get("cast", "")] = True
            self._bless_active.pop(b.get("cast", ""), None)
            self.b.log(f"Learned how '{b.get('name') or b.get('cast')}' wears off: \"{line}\"")

    def _fix_item_bless(self):
        lc = self._last_cast_buff
        if not lc or time.time() - lc[1] > 5:
            return
        b = next((x for x in self.cfg.buffs or [] if x.get("cast") == lc[0]), None)
        cast = (b or {}).get("cast", "")
        if not b or not cast.lower().startswith("use ") or (b.get("equip_cmd") or "").strip():
            return
        word = cast.split(None, 1)[1].lower()
        from .gamestate import parse_item_list, wielded
        item = next((re.sub(r"\s*\([^)]*\)\s*$", "", n).strip() for _q, n in parse_item_list(self.st.carrying or "")
                     if word in n.lower()), None)
        if not item:
            return
        was = wielded(self.st.carrying or "")
        b["equip_cmd"] = f"eq {item}"
        self.cfg.save()
        self.b.log(f"'{cast}' needs the {item} in hand — equipping it for that bless from now on")
        self.send(f"eq {item}")
        self.send(cast)
        if was:
            self.send(f"eq {was}")

    @staticmethod
    def _norm_msg(x) -> str:
        return re.sub(r"[!.\s]+$", "", (x or "").strip().lower())

    def _msg_rules(self):
        return [r for r in (getattr(getattr(self.b.s, "msgrules", None), "rules", None) or [])
                if r.get("end") and "{" not in (r.get("start") or "")]

    def _msg_rule_for_end(self, line):
        n = self._norm_msg(line)
        return next((r for r in self._msg_rules() if self._norm_msg(r["end"]) == n), None)

    def _drop_bad_learned(self) -> int:
        """Start / wear-off lines MudPilot learned itself that are party or movement lines ("You are no longer following
        Evolution.") are forgotten so the real ones get learned. Lines you typed yourself are never touched."""
        n = 0
        for b in self.cfg.buffs or []:
            for k in ("on_msg", "off_msg"):
                if b.get(k + "_learned") and NOT_BLESS_RE.search(b.get(k) or ""):
                    what = "start" if k == "on_msg" else "wear-off"
                    self.b.log(f"'{b.get('name') or b.get('cast')}': forgetting the {what} line \"{b[k]}\""
                               " - that's not a bless line")
                    b[k] = ""
                    b.pop(k + "_learned", None)
                    n += 1
            if NOT_BLESS_RE.search(b.get("_on_candidate") or ""):
                b.pop("_on_candidate", None)
        return n

    def fix_bless_messages(self) -> int:
        """Each bless's 'it ended' line from the Messages file (MegaMUD's — bundled): mageshield's is "Your
        mageshield shimmers and fades", not "The effects of the poison wear off" a guess picked up (Dan,
        2026-10-28: so a bless that drops is noticed at once, and poison ending doesn't recast mageshield).
        Lines you typed yourself are kept. Returns how many it fixed."""
        fixed = self._drop_bad_learned()
        rules = self._msg_rules()
        if not rules:
            return fixed
        for b in self.cfg.buffs or []:
            sp = self.b.spell_for_cast(b.get("cast", "")) if b.get("cast") else None
            names = {self._norm_msg(b.get("name")), self._norm_msg((sp or {}).get("Name") if isinstance(sp, dict) else "")}
            names.discard("")
            on = self._norm_msg(b.get("on_msg"))
            # the spell's own entry first; its start line only when no other spell shares it ("You feel
            # protected" is mageshield's and ethereal shield's)
            r = next((r for r in rules if self._norm_msg(r["name"]) in names), None)
            if r is None and on:
                same = [x for x in rules if self._norm_msg(x["start"]) == on]
                r = same[0] if len({self._norm_msg(x["end"]) for x in same}) == 1 else None
            if not r:
                continue
            start = (r.get("start") or "").strip()
            if start and "{" not in start and on and b.get("on_msg_learned") and on != self._norm_msg(start) \
                    and self._norm_msg(r["name"]) in names:
                # the start line too: a learned guess can be wrong (Revolution, 2026-10-30: nity's was "Dark
                # Corridor" — the effects list never showed it, so it recast every 15 s)
                self.b.log(f"'{b.get('name') or b.get('cast')}' starts with \"{start}\" (Messages file)"
                           + (f" — was \"{b.get('on_msg')}\"" if on else ""))
                b["on_msg"], b["on_msg_learned"] = start, True
                b.pop("_on_candidate", None)
                fixed += 1
            end = r["end"].strip()
            cur = (b.get("off_msg") or "").strip()
            if cur and not b.get("off_msg_learned"):
                continue                                # yours: leave it
            if self._norm_msg(cur) != self._norm_msg(end):
                b["off_msg"], b["off_msg_learned"] = end, True
                fixed += 1
                self.b.log(f"'{b.get('name') or b.get('cast')}' ends with \"{end}\" (Messages file)"
                           + (f" — was \"{cur}\"" if cur else ""))
        if fixed:
            try:
                self.cfg.save()
            except Exception:
                pass
        return fixed

    def stat_block_tick(self):
        """A second after the 'st' listing ends, mark blesses it didn't list as worn off."""
        sb = getattr(self, "_stat_block", None)
        if not sb or time.time() - sb["t"] < 1.5:
            return
        self._stat_block = None
        if sb.get("lines") or sb["seen"]:
            self._stat_lists_effects = True          # this board's 'st' does list what's on you
        if sb.get("effects") and getattr(self, "_stat_lists_effects", False):
            # pMUD: the effects list is the truth — a blind / held / stunned / confused we picked up from a
            # message but that isn't listed any more is over (we missed the 'wears off' line)
            text = " ".join(sb.get("lines") or [])
            for name in ("blind", "held", "stunned", "confused"):
                since = self.ailments.get(name)
                if since and sb["t"] - since > 3 and not STATUS_RES[name][0].search(text) and name not in text:
                    self.ailments.pop(name, None)
                    self.care.report_mine(name, False)
                    self.b.log(f"Not {name} any more (your stat effects don't list it)")
            mr = getattr(self.b.s, "msgrules", None)
            for cond in list(getattr(mr, "conditions", {}) or {}):
                c = mr.conditions[cond]
                word = cond.replace("_", " ")
                if sb["t"] - c.get("since", sb["t"]) > 3 and cond in ("blind", "held", "confused") and word not in text:
                    mr._clear(cond, "not in your stat effects")
        if not sb["seen"] and not self._bless_active:
            return                                   # a board whose 'st' doesn't list effects at all
        if not sb["seen"] and not getattr(self, "_stat_lists_effects", False):
            # stock MajorMUD's 'st' never lists effects: an empty list there says nothing about blesses — going
            # by it recast every bless after every 'st', every ~15 s (0.8.201, bug hunt: stock bless recast loop)
            return
        for b in self.cfg.buffs or []:
            on = (b.get("on_msg") or "").strip().lower().rstrip("!. ")
            key = b.get("cast", "")
            if on and key in self._bless_active and on not in sb["seen"] and not str(b.get("ability") or "").strip():
                self._bless_active.pop(key, None)
                self.b._buff_off[key] = True
                self.b.log(f"'{b.get('name') or key}' isn't in your effects list — recasting")

    def _sync_bless(self, msg, left):
        """A bless is up with `left` seconds to go: recast it when it's down to the margin, not before."""
        from .spells import spell_duration
        cfg, now = self.cfg, time.time()
        for b in cfg.buffs or []:
            on = (b.get("on_msg") or "").strip().lower()
            if not on or on.rstrip("!. ") != msg.rstrip("!. "):
                continue
            margin = self.b.bless_margin(b)               # (AC / DR blesses: 5% of their duration, at least)
            key = b.get("cast", "")
            every = int(b.get("every") or 0)
            if every:
                last = now - every + max(0, left - margin)
            else:
                sp = self.b.spell_for_cast(key)
                dur = self.b.learned_duration(b) or spell_duration(sp, cfg.char_level or self.st.level)
                last = now - (dur - left) if dur else now - 300 + max(0, left - margin)
            self.b._buff_cast[key] = last
            self.b._buff_off.pop(key, None)
            self._bless_active[key] = now - max(0, (spell_duration(self.b.spell_for_cast(key),
                                                                    cfg.char_level or self.st.level) or left) - left)

    def note_cast_buff(self, key):
        self._last_cast_buff = (key, time.time())
        self._bless_active.pop(key, None)

    def bless_state(self, b) -> str:
        """'active 3m left', 'wore off' or ''."""
        from .spells import spell_duration
        key = b.get("cast", "")
        if self.b._buff_off.get(key):
            return "wore off"
        since = self._bless_active.get(key) or self.b._buff_cast.get(key, 0)
        if not since:
            return ""
        sp = self.b.spell_for_cast(key) if key else None
        dur = spell_duration(sp, self.cfg.char_level or self.st.level)
        if not dur:
            return "active" if key in self._bless_active else ""
        left = int(dur - (time.time() - since))
        if left <= 0:
            return "should have worn off"
        return f"active, {left // 60}m {left % 60:02d}s left" if left >= 60 else f"active, {left}s left"

    # ------------------------------------------------------------ cures / spells-tab extras
    def _is_spell(self, cmd) -> bool:
        w = (cmd or "").split()
        if not w:
            return False
        first = w[1] if w[0].lower() in ("cast", "c") and len(w) > 1 else w[0]
        return bool(self.b.s.spellbook.find(first))

    def cure_tick(self) -> bool:
        cfg, st = self.cfg, self.st
        if not self.ailments:
            return self.care.tick()
        order = (("held", cfg.freedom_cmd, False), ("poison", cfg.cure_poison_cmd, cfg.ignore_poison),
                 ("blind", cfg.cure_blind_cmd, cfg.ignore_blindness), ("disease", cfg.cure_disease_cmd, False))
        for name, cmd, ignore in order:
            if name == "held" and name in self.ailments and self.st.party and self.care.healing_first():
                continue                        # (yourself too: the party heals / rests first, freedom after)
            if name in self.ailments and cmd and not ignore and self._is_spell(cmd) and not self.b.slot_free():
                return False                    # this round's spell is gone — cure next round
            if name in self.ailments and cmd and not ignore and self.b.ready("cure_" + name, 4):
                # three tries per bout, then take it as gone (a missed 'cured' line cast the cure every 4 s for
                # good; party cures already stop at 3) — another sting starts a new bout (0.8.201, bug hunt)
                tries = self.__dict__.setdefault("_cure_tries", {})
                since = self.ailments[name]
                bout, n = tries.get(name, (None, 0))
                n = n if bout == since else 0
                if n >= 3:
                    self.ailments.pop(name, None)
                    tries.pop(name, None)
                    self.care.report_mine(name, False)
                    self.b.log(f"Cured {name}? No 'cured' line after 3 tries — going on as if it's gone")
                    continue
                tries[name] = (since, n + 1)
                self.b.status = f"Curing {name}"
                self.b.log(self.b.status)
                self.send(cmd)
                return True
        return self.care.tick()

    def stunned(self) -> bool:
        """Stunned: nothing you type does anything until it wears off (30 s at most, in case we miss the
        'no longer stunned' line)."""
        t = self.ailments.get("stunned")
        if t and time.time() - t > 30:
            self.ailments.pop("stunned", None)
            return False
        return bool(t)

    def blocked_by_ailment(self) -> bool:
        """Blind or confused (and not ignoring it): don't start fights or walk blind."""
        cfg = self.cfg
        if "blind" in self.ailments and not cfg.ignore_blindness and cfg.cure_blind_cmd:
            return True
        if "confused" in self.ailments and not cfg.ignore_confusion:
            return time.time() - self.ailments["confused"] < 60
        return False

    def before_rest(self, low_hp, medi):
        cfg = self.cfg
        if low_hp and cfg.hp_regen_cmd and not getattr(cfg, "smart_rest", False):   # smart resting casts it itself
            self.send(cfg.hp_regen_cmd)
        if (medi or not low_hp) and cfg.ma_regen_cmd:
            self.send(cfg.ma_regen_cmd)
        self.need_hold("meditating" if medi else "resting")

    def after_rest(self):
        self.release_hold("meditating")
        self.release_hold("resting")

    # MegaMUD party protocol: a follower telepaths the leader "@wait" when it needs the party to stop,
    # and "@ok" once nothing is holding it any more (rest/meditate, blind, held…).
    WAIT_AGAIN = 60          # still holding: say @wait again this often (the leader lets a silent one go)

    def need_hold(self, why, label=None):
        """'@wait (confused)': always with the reason — parked by a bare @wait, nobody knows why or for how long
        (Dan, 2026-11-02). Still needed a minute on, it's said again, so a leader that let it go (or was told
        @ok by hand) stops again; a stuck one just lapses."""
        cfg, st = self.cfg, self.st
        reasons = self.__dict__.setdefault("_hold_reasons", set())
        reasons.add(why)
        labels = self.__dict__.setdefault("_hold_labels", {})
        labels[why] = label or why
        again = self._sent_wait and time.time() - getattr(self, "_wait_sent_at", 0) > self.WAIT_AGAIN
        if st.party and not self.leading() and (not self._sent_wait or again) and \
                (cfg.party_wait_msg or "").strip() and not self.b.waiting_off():
            ld = self.leader()
            if ld:
                why_txt = ", ".join(labels.get(r, r) for r in sorted(reasons))
                self.send(f"/{ld} {cfg.party_wait_msg.strip()} ({why_txt})")
                self._sent_wait = True
                self._wait_sent_at = time.time()
                self._wait_to = ld
                self.b.log(f"Told {ld} to wait ({why_txt})" + (" — still" if again else ""))

    def release_hold(self, why):
        reasons = self.__dict__.setdefault("_hold_reasons", set())
        reasons.discard(why)
        self.__dict__.setdefault("_hold_labels", {}).pop(why, None)
        if self._sent_wait and not reasons:
            # whoever we told @wait hears the @ok — even with the party broken for the moment (a telepath gets there
            # anyway): Revolution's confusion wore off while the fear had split the party, nothing was said, and
            # Miserable sat 2 min on the @wait (Dan, 2026-11-10: "that shoulda came before I even scooped him back up")
            ld = getattr(self, "_wait_to", None) or self.leader()
            if ld and (self.cfg.party_resume_msg or "").strip():
                self.send(f"/{ld} {self.cfg.party_resume_msg}")
                self.b.log(f"Told {ld} @ok — ready to go")
            self._sent_wait = False

    def full_tick(self) -> bool:
        cfg, st = self.cfg, self.st
        # told the leader @wait but we're up and not resting any more (rest switched off, moved…)?
        # send @ok so a MegaMUD leader isn't left waiting forever
        if self._sent_wait and not st.resting and not st.in_combat and \
                time.time() - getattr(self, "_wait_sent_at", 0) > 20 and not getattr(self.b, "_rest_begun", False):
            self.after_rest()
        # told the leader @wait, and we're back where we wanted to be — but still sitting, because the leader sat down
        # too (party sync: resting together). Say @ok now: the leader was resting because of our @wait and we were
        # resting because of theirs — both at ~100% for most of a minute until a timeout broke it (Dan, 2026-10-28)
        if self._sent_wait and st.resting and not st.in_combat and \
                time.time() - getattr(self, "_wait_sent_at", 0) > self.WAIT_AGAIN:
            for r in [r for r in ("meditating", "resting") if r in self.__dict__.get("_hold_reasons", ())][:1]:
                self.need_hold(r, self.__dict__.get("_hold_labels", {}).get(r))
        if self._sent_wait and st.resting and not st.in_combat and st.max_hp and \
                st.hp_pct() >= int(cfg.rest_until_hp or 100) - 2 and \
                (not st.max_ma or st.ma_pct() >= int(cfg.rest_until_ma or 100) - 2):
            self.release_hold("resting")
            self.release_hold("meditating")
        # blind / confused: we can't keep up — hold the party until it clears; cleared → @ok straight away, in a party
        # right now or not (the fear that confuses you often splits the party too)
        if st.party and not self.leading() and self.blocked_by_ailment():
            self.need_hold("ailment", "blind" if "blind" in self.ailments and not self.cfg.ignore_blindness
                           else "confused")
        elif "ailment" in self.__dict__.get("_hold_reasons", ()) and not self.blocked_by_ailment():
            self.release_hold("ailment")
        if not st.max_hp or st.in_combat:
            return False
        full_hp = st.hp >= st.max_hp
        full_ma = bool(st.max_ma) and st.ma >= st.max_ma
        sent = False
        if full_hp and not self._was_full_hp and cfg.hp_full_cmd:
            self.send(cfg.hp_full_cmd)
            sent = True
        if full_ma and not self._was_full_ma and cfg.ma_full_cmd:
            self.send(cfg.ma_full_cmd)
            sent = True
        self._was_full_hp, self._was_full_ma = full_hp, full_ma
        return sent

    def may_cast_attack(self) -> bool:
        n = int(self.cfg.max_off_casts or 0)
        return not n or self._casts_this_fight < n

    def counted_cast(self):
        self._casts_this_fight += 1

    # ------------------------------------------------------------ party
    def party_bless_tick(self) -> bool:
        from .spells import default_recast
        cfg, st = self.cfg, self.st
        if not cfg.party_blesses or not st.party or st.in_combat:
            return False
        now = time.time()
        for pb in cfg.party_blesses:
            cast = (pb.get("cast") or "").strip()
            if not cast or not pb.get("enabled", True):
                continue
            secs = int(pb.get("secs") or 0)
            if not secs:
                sp = self.b.spell_for_cast(cast)
                secs = (default_recast(sp, cfg.char_level or st.level, cfg.bless_margin_secs) or 300)
            targets = [n for n in st.party if n.lower() != self.me()] if "{name}" in cast else [None]
            for who in targets:
                k = (cast, who)
                if now - self._pblessed.get(k, 0) >= secs and self.b.slot_free() and self.b.ready("pbless", 3):
                    self._pblessed[k] = now
                    cmd = cast.replace("{name}", who) if who else cast
                    self.b.status = f"Party bless: {cmd}"
                    self.send(cmd)
                    return True
        return False

    def wait_for_party(self) -> bool:
        """Leading: hold the walk while a member is below the wait %, for at most party_wait_mins."""
        cfg, st = self.cfg, self.st
        if not st.party or not self.leading() or not cfg.party_wait_pct or self.b.waiting_off():
            self._wait_since = 0.0
            self.waiting_on = []
            return False
        now = time.time()
        fresh = max(20.0, 4 * float(cfg.party_check_secs or 5))
        members = {n: i for n, i in st.party.items() if n.lower() != self.me()}
        stale = [n for n, i in members.items() if now - i.get("t", 0) > fresh]
        if stale and float(cfg.party_check_secs or 0) > 0:
            # don't walk on an old 'par' (it can lapse on a long walk): ask, and hold a few seconds for it
            if not getattr(self, "_stale_since", 0):
                self._stale_since = now
                self.b._cool["par"] = 0
            if now - self._stale_since < 6:
                self.b.status = "Checking the party before moving on"
                return True
        else:
            self._stale_since = 0
        was = set(getattr(self, "waiting_on", []) or [])
        hp_until = max(int(cfg.party_wait_pct or 0), int(cfg.party_wait_until_pct or 0))
        ma_at, ma_until = int(cfg.party_wait_ma_pct or 0), int(cfg.party_wait_ma_until or 0)
        try:
            sync = {k.lower(): v for k, v in self.b.s.partysync.info().items()}
        except Exception:
            sync = {}
        low = []
        for n, i in members.items():
            if now - i.get("t", 0) >= 60:
                continue
            hp, ma = i.get("hp", 100), i.get("ma", 100)
            # start waiting below the line; once waiting, keep at it until they're well back up
            if hp < cfg.party_wait_pct or (n in was and hp < hp_until):
                low.append(n)
            elif ma_at and (ma < ma_at or (n in was and ma < max(ma_at, ma_until))) and \
                    (sync.get(n.lower()) or {}).get("rma", 1) != 0:
                # (a member whose own 'Rest below MA' is 0 — Buddy, a melee Paladin — doesn't need mana to walk:
                #  their MudPilot rests it if it wants to. 0.8.208, Dan)
                low.append(n)
        # already waited the full time for these: leave them out until they're back over the line, then a new wait
        # can start (0.8.201, bug hunt: after a timeout it logged "Waiting for …" every tick and never waited again)
        out = getattr(self, "_waited_out", set()) & set(low)
        self._waited_out = out
        low = [n for n in low if n not in out]
        self.waiting_on = low
        if not low:
            self._wait_since = 0.0
            return False
        if not self._wait_since:
            self._wait_since = now
        if set(low) - was:
            # say so (Dan, 2026-10-30: Revolution sat ~3 min on a Go to for Buddy's mana — "logs show nothing")
            why = ", ".join(f"{n} (HP {members[n].get('hp', 100)}%, MA {members[n].get('ma', 100)}%)" for n in low)
            self.b.log(f"Waiting for {why} to rest up — up to {cfg.party_wait_mins:g} min "
                       f"(Settings → Party: wait below {cfg.party_wait_pct}% HP / {ma_at}% mana)")
        if now - self._wait_since > float(cfg.party_wait_mins or 0) * 60:
            if low and self.b.ready("party_wait_done", 60):
                self.b.log(f"Done waiting for {', '.join(low)} ({cfg.party_wait_mins:g} min) — walking on")
            self._waited_out = out | set(low)
            self._wait_since = 0.0
            self.waiting_on = []
            return False
        self.b.status = f"Waiting for {', '.join(low)} to rest up"
        return True

    def leader_target(self, mobs):
        """Reorder mobs: the leader's target first (if seen recently), reverse order if asked."""
        cfg = self.cfg
        if cfg.attack_reverse and self.st.party:
            mobs = list(reversed(mobs))
        if getattr(cfg, "target_biggest", True) and len(mobs) > 1:
            # the biggest threat first (Dan, 2026-10-30: in the prismatic dragon's arena MudPilot killed every
            # serpent before the dragon) — by MME exp, the room's order between equals
            mobs = sorted(mobs, key=lambda m: -float((m[1] or {}).get("exp") or 0))
        # pMUD's target priority: two bots can split a room (one takes the first monster, one the second)
        pr = (getattr(cfg, "target_priority", "first") or "first").lower()
        if len(mobs) > 1 and pr != "first":
            i = {"second": 1, "third": 2}.get(pr, len(mobs) - 1 if pr == "last" else 0)
            i = min(i, len(mobs) - 1)
            mobs = [mobs[i]] + mobs[:i] + mobs[i + 1:]
        lt = self._leader_target
        if cfg.attack_leaders_target and lt and time.time() - lt[1] < 20:
            first = [m for m in mobs if m[0] == lt[0]]
            mobs = first + [m for m in mobs if m[0] != lt[0]]
        return mobs

    def party_limits(self, mobs) -> list:
        cfg, st = self.cfg, self.st
        if not st.party:
            return mobs
        if cfg.party_max_mob_exp:
            mobs = [m for m in mobs if not m[1] or m[1].get("exp", 0) <= cfg.party_max_mob_exp]
        return mobs

    def max_mobs(self) -> int:
        cfg = self.cfg
        return cfg.party_max_mobs if (self.st.party and cfg.party_max_mobs) else cfg.max_mobs

    def rank_tick(self) -> bool:
        """Keep your party rank where the Party tab says (Front / Mid / Back)."""
        cfg, st = self.cfg, self.st
        want = (cfg.party_rank or "").lower()
        if not want or not st.party or st.in_combat or self.leading():
            return False                  # the party leader can't change rank
        me = next((info for n, info in st.party.items() if n.lower() == self.me()), None)
        if not me:
            return False
        have = (me.get("rank") or "").lower()
        if have.startswith(want):
            self._rank_tries = 0
            return False
        if getattr(self, "_rank_tries", 0) >= 3:
            return False                  # the game won't let us (3 tries) — don't spam it
        if not self.b.ready("rank", 30):
            return False
        self._rank_tries = getattr(self, "_rank_tries", 0) + 1
        self.b.log(f"Party rank: {have or '?'} → {want}")
        self.send(cfg.rank_cmd.replace("{rank}", want))
        self.b._cool["par"] = time.time() - float(cfg.party_check_secs or 5) + 2
        return True

    def on_flee(self):
        if self.cfg.say_panic and self.st.party and self.leading():
            self.say_party("@panic")

    # ------------------------------------------------------------ cash + stash
    COIN_ORDER = ["copper farthing", "silver noble", "gold crown", "platinum piece", "runic coin"]

    def want_coin(self, kind, level) -> bool:
        r = (self.cfg.cash_rules or {}).get(kind, {})
        if not r.get("get", True):
            return False
        skip = int(r.get("skip_at") or 0)
        return not (skip and level >= skip)

    def make_room_for(self, kind, qty=None) -> list:
        """Heavy and about to pick up a better coin? Drop the cheaper ones you carry first.
        0.8.201, bug hunt: only as many as the pile needs (coins all weigh the same), cheapest first, never a stash
        coin, and only when what's dropped is worth less than what's picked up — it dropped all 300 gold crowns
        (30,000 copper) for 1 platinum piece (10,000)."""
        from .gamestate import COIN_VALUE
        cfg, st = self.cfg, self.st
        if not cfg.drop_small_coins or not st.enc or st.enc[3] < cfg.drop_coins_enc:
            return []
        rank = self.COIN_ORDER.index(kind) if kind in self.COIN_ORDER else 0
        need = int(qty) if qty else sum(int(st.coins.get(k, 0) or 0) for k in self.COIN_ORDER[:rank])
        keep = set(cfg.stash_coins or [])
        out, dropped, lost = [], 0, 0
        for lower in self.COIN_ORDER[:rank]:
            if lower in keep or dropped >= need:
                continue
            n = min(int(st.coins.get(lower, 0) or 0), need - dropped)
            if n > 0:
                out.append(cfg.drop_cmd.format(qty=n, item=self._coin_word(lower, n)))
                dropped += n
                lost += n * COIN_VALUE.get(lower, 0)
        if qty and lost >= int(qty) * COIN_VALUE.get(kind, 0):
            return []
        return out

    @staticmethod
    def _coin_word(kind, n):
        return kind + ("s" if n != 1 else "")

    def drop_unwanted(self) -> bool:
        cfg, st = self.cfg, self.st
        if cfg.item_rules and not st.in_combat:
            # Item rules: 'drop' items go as soon as they're in your pack (never anything worn)
            from .gamestate import parse_item_list, worn_list
            worn = {n.lower() for n, _s in worn_list(st.carrying)}
            for q, n in parse_item_list(st.carrying or ""):
                nm = re.sub(r"\s*\([^)]*\)\s*$", "", n)
                rule = self.b.item_rule(nm)
                if rule.get("drop") and nm.lower() not in worn and not self.b.s.world.not_droppable(nm) \
                        and self.b.ready("dropitem_" + nm, 30):
                    keep = int(rule.get("keep") or 0)
                    if q > keep:
                        self.b.log(f"Item rules: dropping {nm}")
                        self.send(cfg.drop_cmd.format(qty=q - keep, item=nm))
                        return True
        if not cfg.drop_unwanted_coins:
            return False
        lvl = st.level or cfg.char_level or 0
        for k, n in list(st.coins.items()):
            if n > 0 and not self.want_coin(k, lvl) and self.b.ready("dropcoin_" + k, 20):
                self.send(cfg.drop_cmd.format(qty=n, item=self._coin_word(k, n)))
                return True
        return False

    @staticmethod
    def loop_key(mp) -> str:
        import os
        return (os.path.basename(mp.filename) if getattr(mp, "filename", None) else mp.title).lower()

    def stash_room(self, loop=None):
        """The stash for this loop (set per loop in the Paths tab), else the Loot tab's default one."""
        loop = loop or getattr(self.b, "_lap_path", None)
        txt = ""
        if loop is not None:
            txt = (self.cfg.loop_stash or {}).get(self.loop_key(loop), "")
        return room_text(txt or self.cfg.stash_room or "")

    def stash_rooms(self) -> set:
        """Every stash room set: this loop's, the default, every loop's, and the party stash a member told us."""
        cfg = self.cfg
        out = {self.stash_room(), room_text(cfg.stash_room or ""), room_text(cfg.party_stash_room or "")}
        out |= {room_text(t) for t in (cfg.loop_stash or {}).values()}
        out.discard(None)
        return out

    def in_any_stash(self, room) -> bool:
        """0.8.201, bug hunt: loot's 'never pick the stash back up' only knew this loop's stash room — after a loop
        rotation the other loop's stash, and the party stash a member hides its things in, were searched and looted
        (then stashed again, over and over)."""
        return bool(room) and room in self.stash_rooms()

    def stash_flagged_names(self) -> list:
        """Items ticked Auto-stash in Game Data → Items ('runed stone cudgel: get, stash' in the item rules)."""
        out = []
        for ln in self.cfg.item_rules or []:
            if ":" in ln:
                k, spec = ln.split(":", 1)
                if "stash" in [x.strip().lower() for x in re.split(r"[,;]", spec)] and k.strip():
                    out.append(k.strip().lower())
        return out

    def collect_names(self) -> list:
        """Items set to Auto-get in Game Data → Items."""
        out = []
        for ln in self.cfg.item_rules or []:
            if ":" in ln:
                k, spec = ln.split(":", 1)
                if "get" in [x.strip().lower() for x in re.split(r"[,;]", spec)] and k.strip():
                    out.append(k.strip().lower())
        return out

    def item_by_name(self, text):
        """(item name, "") for '@collect cudgel' — MME's item list, exact first, then a unique part of a name. (None,
        why) when several match. Not in MME at all: taken as typed (a board's own item)."""
        low = re.sub(r"\s+", " ", (text or "").strip().lower())
        if not low:
            return None, "which item?"
        names = sorted({(g.get("name") or "").strip() for g in (getattr(self.b.s.world, "gear", {}) or {}).values()}
                       - {""})
        exact = [n for n in names if n.lower() == low]
        if exact:
            return exact[0], ""
        part = [n for n in names if low in n.lower()]
        if len(part) == 1:
            return part[0], ""
        if part:
            return None, f"which one? {', '.join(part[:5])}" + (f" +{len(part) - 5} more" if len(part) > 5 else "")
        return text.strip(), ""

    def set_item_flag(self, name, stash, on=True):
        """The same item rule Game Data → Items' Auto-get / Auto-stash buttons write. stash=False: auto-get on/off;
        stash=True: auto-get + stash on, or just the stash off (it's still picked up)."""
        cfg = self.cfg
        low = name.lower()
        parts = []
        for ln in cfg.item_rules or []:
            if ":" in ln and ln.split(":", 1)[0].strip().lower() == low:
                parts = [p.strip() for p in re.split(r"[,;]", ln.split(":", 1)[1]) if p.strip()]
        drop = {"stash", "never"} if stash or on else {"get", "stash", "never"}
        ps = [p for p in parts if p.lower() not in drop and not (not stash and not on and p.lower().startswith("max"))]
        if on:
            if not any(p.lower() == "get" for p in ps):
                ps.insert(0, "get")
            if stash:
                ps.append("stash")
            cfg.auto_loot = True
        cfg.item_rules = [ln for ln in (cfg.item_rules or []) if not (":" in ln and ln.split(":", 1)[0].strip().lower()
                                                                       == low)] + ([f"{name}: {', '.join(ps)}"] if ps else [])
        cfg.save()

    def to_stash(self, flagged_only=False) -> list:
        """[(qty, name)] you carry that belong in the stash. flagged_only: just the Auto-stash items (a member's
        stash room, set with '@stash': no coins, no ears — Dan, 2026-11-15)."""
        cfg, st = self.cfg, self.st
        out = []
        for k in ([] if flagged_only else cfg.stash_coins or []):
            n = st.coins.get(k, 0)
            if n > 0:
                out.append((n, self._coin_word(k, n)))
        # Dan, 2026-11-15: auto-get and auto-stash are two different things. Only items ticked Auto-stash (and the
        # Loot tab's "Stash these items") are stashed — the sellables, so we don't walk round heavy. Everything else
        # you auto-get (rares) stays in the pack for good. ("Also stash everything the Get button picks up" is gone.)
        wanted = self.stash_flagged_names()
        if not flagged_only:
            wanted += [w.lower() for w in (cfg.stash_items or []) if w.strip()]
        if wanted:
            got = {}
            for qty, name in parse_carry(st.carrying):
                if "(" in name or coin_kind_(name):
                    continue                      # worn/wielded gear and coins are handled elsewhere
                if any(w in name.lower() for w in wanted):
                    got[name] = got.get(name, 0) + qty      # the pack can list the same item many times over
            out += [(q, n) for n, q in got.items()]
        return out

    def is_stash_item(self, name) -> bool:
        """Something that belongs in the stash: never picked back up off the stash room's floor."""
        low = (name or "").lower()
        return any(w in low for w in self.stash_flagged_names() + [w.lower() for w in (self.cfg.stash_items or [])
                                                                    if w.strip()])

    def stash_value(self) -> int:
        from .gamestate import COIN_VALUE
        return sum(self.st.coins.get(k, 0) * COIN_VALUE.get(k, 0) for k in self.cfg.stash_coins or [])

    def stash_tick(self) -> bool:
        """Standing in the stash room with things to stash: drop (and hide) them."""
        st, cfg = self.st, self.cfg
        room = self.stash_room()
        mine = bool(room) and st.room == room
        if not mine and st.room and getattr(self.b, "_lap_path", None) is None and self.leader() is not None:
            # following: no lap of our own, so no loop's stash — but walking through one of our loops' stash rooms
            # behind the leader stashes too (0.8.208, Dan 2026-11-19: Miserable following Revolution round Stonecaps
            # never stashed in 14/6534 once Revolution led)
            mine = st.room in {room_text(t) for t in (cfg.loop_stash or {}).values()} - {None}
        member = not mine and bool(st.room) and st.room == room_text(cfg.party_stash_room)
        if not (mine or member):
            self._stashed_visit = False          # left the room: the next visit may stash again
            return False
        if getattr(self, "_stashed_visit", False):
            # once a visit (Dan, 2026-11-18: following Revolution, he searched the stash room, picked up the 10,800
            # gold to use his coin bag on it — and it was hidden again behind him, six bag uses in)
            return False
        if time.time() - getattr(self.b.s, "_user_sent_at", 0) < 60:
            return False                         # you're doing something here by hand
        if (mine or member) and not self.b.walking and self.leader() is None:   # (a follower moves with its leader)
            # only while looping / walking (Dan, 2026-11-16: he walked to the stash room to collect the cash and
            # use his coin bag on it — 3 a day — and it hid the cash again first, wasting a use). Standing here by
            # hand also holds it for 3 minutes after, so a quick Rego doesn't hide it straight back either.
            self._stash_manual_at = time.time()
            return False
        if time.time() - getattr(self, "_stash_manual_at", 0) < 180:
            return False
        if not (mine or member) or st.in_combat or not self.b.ready("stash", 6):
            return False
        if mine and self._party_stash():
            return True
        items = self.to_stash(flagged_only=member)
        if not items:
            if self.looted and not member and self.b.ready("stash_inv", 30):
                self.send("i")                   # picked things up since the last 'i' — recount first
                return True
            return False
        self.b.status = "Stashing"
        for qty, name in items:
            # MajorMUD hides straight from your pack ("hide 56 gold crowns"); dropping first leaves
            # nothing to hide ("You don't have gold crowns to hide!")
            hide = cfg.stash_hide and (cfg.stash_hide_cmd or "").strip()
            cmd = cfg.stash_hide_cmd if hide else cfg.stash_cmd
            if coin_kind_(name):
                self.send(cmd.format(qty=qty, item=name))
                continue
            for _ in range(min(qty, 30)):            # items one at a time, as before (14 cudgels = 14 hides)
                self.send(cmd.replace("{qty} ", "").format(qty=1, item=name))
        self.b.log("Stashed " + ", ".join(f"{q} {n}" for q, n in items))
        self._stashed_visit = True
        for _q, n in items:
            self.looted.discard(n.lower())
        self.send("i")                       # recount what you carry
        return True

    def _party_stash(self) -> bool:
        """In the stash room: members standing here hide what they picked up for us ('/Revolution @do hide runed
        stone cudgel'). Dan, 2026-11-15: a mage's cudgels went to the druid and never reached the stash."""
        here = {p.split()[0].strip(".,").lower() for p in ((self.st.view.players if self.st.view else []) or [])
                if p.split()}
        for who, items in list(self.held_for_me.items()):
            if who.lower() not in here or not items:
                continue
            cmds = [f"hide {name}" for name, n in items.items() for _ in range(min(n, 10))]
            self.send(f"/{who} @do " + "^M".join(cmds))
            self.b.log(f"Asked {who} to hide what they picked up for me: "
                       + ", ".join(f"{n} {name}" for name, n in items.items()))
            del self.held_for_me[who]
            return True
        return False

    def stash_at_lap_end(self, loop) -> bool:
        """End of a lap: if the loop doesn't pass the stash room and you're carrying enough, go stash."""
        cfg = self.cfg
        room = self.stash_room(loop)
        if not cfg.stash_each_lap or not room or not self.to_stash():
            return False
        if any(s.room == room for s in loop.steps):
            return False                     # the loop goes there anyway; stash_tick handles it
        here = self.st.room
        far = int(cfg.stash_max_steps or 0)
        if here and far:
            rt = self.b.s.world.route(here, room, level=self.st.level or None)
            if rt is None or len(rt) > far:
                if getattr(self, "_stash_far_said", None) != (self.loop_key(loop), room):
                    self._stash_far_said = (self.loop_key(loop), room)
                    self.b.log(f"Stash room {room[0]}/{room[1]} is {'out of reach' if rt is None else f'{len(rt)} steps'} "
                               f"from this loop (limit {far}) — not stashing. Set one for this loop: Paths → More.")
                return False
        has_items = any(not coin_kind_(n) for _q, n in self.to_stash())
        if self.stash_value() < int(cfg.stash_min_copper or 0) and not has_items:
            return False
        if self.b.goto(room, then=loop):
            self.b.log(f"Lap done — taking the stash to {room[0]}/{room[1]}")
            return True
        return False

    # ------------------------------------------------------------ PvP
    def is_friend(self, name) -> bool:
        """Someone we never fight: in the party (now, or in the last half hour — parties reshuffle when someone
        reconnects), our leader, a MudPilot partner, on the PvP friends list or allowed to remote-control us."""
        low = (name or "").lower()
        cfg, st = self.cfg, self.st
        seen = self.__dict__.setdefault("_party_seen", {})
        now = time.time()
        for n in (st.party or {}):
            seen[n.lower()] = now
        if now - seen.get(low, 0) < 1800:
            return True
        if low == (self.leader() or "").lower() or low == (getattr(self, "_following", "") or "").lower():
            return True
        try:
            if low in {p.lower() for p in self.b.s.partysync.peers}:
                return True
        except Exception:
            pass
        friends = {str(x).lower() for x in (cfg.pvp_friends or [])} | {str(x).lower() for x in (cfg.remote_players or {})}
        try:
            if self.b.s.players.relationship(name) == "Friend":
                return True                  # marked Friend in Game Data → Players: whatever they were before
        except Exception:
            pass
        return low in friends

    def start_pvp(self, name, why=""):
        if self.is_friend(name):
            if self.b.ready(f"pvp_friend_{name.lower()}", 60):
                self.b.log(f"PvP: not fighting {name} — a friend (party / MudPilot partner / remote list)"
                           + (f"; it looked like they {why}" if why else ""))
            return
        if self.pvp_target != name:
            self.b.log(f"PvP: fighting {name}{f' ({why})' if why else ''}")
        self.pvp_target = name
        self.pvp_seen = time.time()
        self._pvp_cast = {}

    def stop_pvp(self):
        self.pvp_target = None
        self._pvp_cast = {}

    def pvp_tick(self) -> bool:
        cfg, st = self.cfg, self.st
        name = self.pvp_target
        if not name:
            return False
        if self.is_friend(name):
            self.b.log(f"PvP: {name} is a friend — not fighting them")
            self.stop_pvp()
            return False
        now = time.time()
        here = st.view and any(p.split()[0].strip(".,").lower() == name.lower() for p in st.view.players)
        if here:
            self.pvp_seen = now
        elif now - self.pvp_seen > 15:
            self.b.log(f"PvP: {name} is gone")
            self.stop_pvp()
            return False
        else:
            return False
        rnd = float(cfg.spell_round_secs or 5)
        if not self.b.ready("pvp_round", rnd):
            # (0.8.201, bug hunt: True here held the heals and cures behind it for the whole fight — a priest never
            # healed itself or the party between PvP rounds. tick() lets those go out, then holds everything else)
            self.pvp_hold = now
            return False
        for ps in cfg.pvp_spells or []:
            cast = (ps.get("cast") or "").strip()
            if not cast or not ps.get("enabled", True):
                continue
            every = float(ps.get("rounds") or 0) * rnd
            if every and now - self._pvp_cast.get(cast, 0) < every:
                continue
            self._pvp_cast[cast] = now
            cmd = cfg.pvp_target_cmd.replace("{cast}", cast).replace("{name}", name) if "{name}" not in cast \
                else cast.replace("{name}", name)
            self.b.status = f"PvP: {cmd}"
            self.send(cmd)
            return True
        self.b.status = f"PvP: attacking {name}"
        self.send(cfg.attack_cmd.format(target=name))
        return True

    # ------------------------------------------------------------ auto-roam
    def start_roam(self):
        self.roaming = True
        self.b.log("Auto-roaming")

    def stop_roam(self):
        self.roaming = False

    def roam_tick(self) -> bool:
        cfg, st = self.cfg, self.st
        if not self.roaming or st.in_combat or st.pending or not st.view or st.resting:
            return False
        if not self.b.ready("roam", 1.2):
            return True
        here = st.room
        # special room commands
        if here and here != self._roam_cmd_room:
            self._roam_cmd_room = here
            for sr in cfg.roam_rooms or []:
                m = re.match(r"^\s*(\d+)\s*/\s*(\d+)", sr.get("room") or "")
                if m and (int(m.group(1)), int(m.group(2))) == here and (sr.get("cmd") or "").strip():
                    self.b.send_macro(sr["cmd"])
                    return True
        allowed = {d.upper() for d in cfg.roam_dirs or []}
        exits = [d for d in st.view.exits if d in allowed]
        room = self.b.s.world.room(here) if here else None
        if room:
            opens = {d.upper() for d in cfg.roam_open_dirs or []}
            exits += [d for d, e in room.exits.items() if e.door and d in opens and d not in exits and e.visible]
        if not exits:
            self.b.status = "Auto-roam: no allowed exit here"
            return True
        back = None
        if room and self._roam_from:
            back = next((d for d, e in room.exits.items() if e.to == self._roam_from), None)
        choices = [d for d in exits if d != back] or exits
        d = random.choice(choices)
        self._roam_from = here
        if room and d in room.exits and room.exits[d].door:
            self.send(f"open {DIR_WORDS[d]}")
        self.b.status = f"Auto-roam: {DIR_WORDS[d]}"
        self.send(d.lower())
        return True
