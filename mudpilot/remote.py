"""MegaMUD-compatible remote (@) commands.

Commands arrive the same ways MegaMUD hears them:
    Bob telepaths: @health
    Bob says "@health"            (also: Bob says (to You) "@health")
    Bob gangpaths: @health
    Broadcast from Bob "@health"
and replies go back the MegaMUD way, wrapped in braces:
    /Bob {HP=650/650,MA=394/400, Meditating}     (telepath)
    >Bob {…}   (say)   bg {…}   (gangpath)   br {…}   (broadcast)

Security (MegaMUD-style, default deny):
  * nobody can control you unless you list them on the Remote tab and tick what
    they may do; party members may only use the party signals (@wait/@ok/...);
  * anything mentioning "suicide" or "reroll" is silently dropped, always;
  * a master switch turns it all off; broadcast is off by default.
"""
from __future__ import annotations

import re
import time

from . import __version__
from .bosses import fmt_dur
from .peruse import NAMES
from .extras import room_text as room_text_

CATEGORIES = {
    "query": "Health / exp / status",
    "location": "Location (@where @path @who)",
    "inventory": "Inventory (@inventory @what @wealth @enc @have)",
    "invite": "Party invite / join",
    "move": "Move me (@goto @loop @stop @rego @summon)",
    "execute": "Run commands (@do)",
    "settings": "Change settings (@auto-*, @reset, @bless)",
    "hangup": "Hang up / relog",
    "divert": "Divert telepaths",
}

# command -> required category ("party" = any party member)
COMMANDS = {
    "@version": "query", "@help": "query", "@health": "query", "@exp": "query", "@level": "query",
    "@status": "query", "@lives": "query", "@timer": "query", "@spawn": "query", "@ac": "query", "@death": "query",
    "@flags": "query",
    "@where": "location", "@path": "location", "@who": "location",
    "@inventory": "inventory", "@inv": "inventory",
    "@what": "inventory", "@wealth": "inventory", "@enc": "inventory", "@have": "inventory",
    "@invite": "invite", "@join": "invite", "@disband": "invite",
    "@do": "execute",
    "@goto": "move", "@loop": "move", "@stop": "move", "@rego": "move", "@summon": "move", "@hunt": "move",
    "@camp": "move",                 # 0.8.201 Camp lairs (lair_camp.py)
    "@auto-all": "settings", "@auto-combat": "settings", "@auto-nuke": "settings", "@auto-cast": "settings", "@auto-heal": "settings",
    "@auto-rest": "settings", "@auto-bless": "settings", "@auto-light": "settings", "@auto-cash": "settings",
    "@auto-get": "settings", "@auto-sneak": "settings", "@auto-hide": "settings", "@auto-search": "settings",
    "@auto-preattack": "settings", "@attack-last": "settings",
    "@settings": "settings", "@reset": "settings", "@bless": "settings", "@collect": "settings",
    "@enemy": "settings", "@neutral": "settings", "@friend": "settings",
    "@nuke": "settings", "@pvp": "settings", "@rest": "settings", "@medi": "settings", "@heal": "settings", "@run": "settings",
    "@divert": "divert",
    "@hangup": "hangup", "@relog": "hangup",
    "@panic": "party", "@party": "party",
    "@wait": "party", "@ok": "party", "@waiting": "party", "@comeback": "party", "@share": "party",
    "@mpsync": "party", "@makeroom": "party", "@stash": "party", "@unstash": "party",
    "@ptrain": "party",              # 0.8.200 party training between MudPilots (training.py)
    # condition reports (pMUD / MudPilot party cures) — read by the party-cure code, nothing to answer
    "@held": "party", "@blind": "party", "@darkness": "party", "@diseased": "party", "@major": "party",
    "@poisoned": "party",
}

# Help → Remote @ commands: (category, command, what it does, example). "★" = MudPilot only.
HELP = [
    ("query", "@health", "HP and mana, and whether resting", "/Miserable @health"),
    ("query", "@exp", "Exp made this session, exp/hr, exp to next level", "/Miserable @exp"),
    ("query", "@level", "Level", "/Miserable @level"),
    ("query", "@status", "What it's doing and where", "/Miserable @status"),
    ("query", "@timer", "Boss respawn timers (one boss by name)", "/Miserable @timer golem"),
    ("query", "@spawn", "One monster's respawn (pMUD's format, so pMUD and MudPilot share timers)",
     "/Miserable @spawn ice queen"),
    ("query", "@lives", "Lives left", "/Miserable @lives"),
    ("query", "@ac ★", "AC/DR with blesses on — vs evil and good too (from 'stat all')", "/Miserable @ac"),
    ("query", "@death ★", "Its last 3 deaths: when, what killed it, where (from 'pro')", "/Miserable @death"),
    ("query", "@flags ★", "Its quest flags (from 'abil'; reads them again). With a name or number: that one flag "
     "and MME's next step for it", "/Evolution @flags dao"),
    ("query", "@version", "Which MudPilot version", "/Miserable @version"),
    ("query", "@help", "The commands you're allowed (or one command)", "/Miserable @help goto"),
    ("location", "@where", "Room name, map and room number, and exits", "/Miserable @where"),
    ("location", "@path", "Path or loop it's on, and the step", "/Miserable @path"),
    ("location", "@who", "Who and what is in the room", "/Miserable @who"),
    ("inventory", "@inventory", "Everything it's carrying", "/Miserable @inventory"),
    ("inventory", "@what", "What's on the floor", "/Miserable @what"),
    ("inventory", "@wealth", "Cash carried (in copper)", "/Miserable @wealth"),
    ("inventory", "@enc", "Encumbrance", "/Miserable @enc"),
    ("inventory", "@have", "Is it carrying this item?", "/Miserable @have rope"),
    ("inventory", "@makeroom ★", "Buys 0 of it (the shop swaps its coins for bigger ones), then drops the cheapest "
     "coins (copper, silver, then gold) if it still won't fit — the "
     "leader asks when a raft hand-over comes back 'cannot accept your offer'", "/Miserable @makeroom log raft"),
    ("inventory", "@stash", "This room is its stash room too: items ticked Auto-stash (Game Data → Items) get hidden "
     "here each time it passes. '@stash raft' hides its raft here (the leader sends that when a loop that doesn't "
     "cross water starts)", "/Revolution @stash"),
    ("settings", "@enemy <monster> ★", "Attack this monster even if it isn't hostile (Game Data → Monsters → "
     "Attitude). '@neutral' / '@friend <monster>' leave it alone; 'off <monster>' back to default",
     "/Evolution @enemy amazon shaman"),
    ("inventory", "@stash here ★", "This room is its real stash room, coins and all: for the loop it's walking "
     "(Paths tab), else its default one (Loot tab)", "/Revolution @stash here"),
    ("inventory", "@stash <item> ★", "Auto-get that item and hide it in the stash room ('off <item>' undoes it, "
     "'list' shows them)", "/Revolution @stash runed stone cudgel"),
    ("inventory", "@collect <item> ★", "Auto-get that item, like Game Data → Items → Auto-get ('off <item>' undoes "
     "it; no item lists them)", "/Revolution @collect runed stone cudgel"),
    ("inventory", "@unstash", "Searches this room and picks its stashed raft back up", "/Miserable @unstash"),
    ("invite", "@invite", "Invites you to its party", "/Miserable @invite"),
    ("invite", "@join", "Joins your party", "/Miserable @join"),
    ("invite", "@disband", "Disbands its party — and doesn't auto-invite anyone back for a minute",
     "/Revolution @disband"),
    ("move", "@goto", "Walks to a room (name or map/room)", "/Miserable @goto 10 297"),
    ("move", "@loop", "Starts a loop by name ('last' = the last one)", "/Miserable @loop rotting glade"),
    ("move", "@loop peruse books ★", "Golden Spire Secret Library: peruse the blue book, then the red one until "
     "it takes, then says 'Books have been properly perused!' in the room", "/Buddy @loop peruse books"),
    ("move", "@stop", "Stops walking", "/Miserable @stop"),
    ("move", "@rego", "Carries on with what it was doing", "/Miserable @rego"),
    ("move", "@hunt ★", "Goes for a boss now — every lair it can be in, nearest next — then back to what it was "
     "doing. Just @hunt: the bosses it's hunting. @hunt off: no hunting at all (stops one under way); "
     "@hunt on: back on", "/Evolution @hunt crimson mist"),
    ("move", "@camp ★", "Lair camping: '@camp start' camps the lairs marked on its Paths → Camp lairs list "
     "(never on a follower), '@camp stop' ends it, '@camp' / '@camp list' shows each lair and when it's back",
     "/Miserable @camp start"),
    ("move", "@summon ★", "Comes to you (your MudPilot adds your room) or to a room", "/Miserable @summon 10 297"),
    ("execute", "@do", "Runs a command; ^M = Enter between several", "/Miserable @do go portal^Me"),
    ("settings", "@auto-combat", "Switch one on/off (also -nuke (area spells) -heal -rest -bless -light -cash -get -sneak "
                                 "-hide -search -preattack); no on/off = show it", "/Miserable @auto-rest off"),
    ("settings", "@auto-all", "Everything off (paused) / back on", "/Miserable @auto-all off"),
    ("settings", "@settings", "Which switches are on", "/Miserable @settings"),
    ("settings", "@nuke ★", "Area spell from this many monsters", "/Miserable @nuke 3"),
    ("settings", "@rest ★", "Rest below / up at HP %", "/Miserable @rest min70 max90"),
    ("settings", "@medi ★", "Meditate below / up at mana %", "/Miserable @medi min30 max80"),
    ("settings", "@heal ★", "Heal below HP %", "/Miserable @heal 60"),
    ("settings", "@run ★", "Run below HP % (0 = never)", "/Miserable @run 0"),
    ("settings", "@bless ★", "List blesses, or set one's target", "/Miserable @bless ntap 150"),
    ("settings", "@reset", "Resets its session exp/hr", "/Miserable @reset"),
    ("settings", "@pvp ★", "on = fight back and defend the party, no PvP hang-up (low-HP hang-up still works); "
                           "off = hang up when anyone in the party is attacked by a player", "/Miserable @pvp on"),
    ("hangup", "@hangup", "Hangs up (only if allowed on its Talk tab)", "/Miserable @hangup"),
    ("hangup", "@relog", "Hangs up and logs straight back in", "/Miserable @relog"),
    ("divert", "@divert", "Forwards its telepaths to you (no name = stop)", "/Miserable @divert Dan"),
    ("party", "@wait", "Hold on — I need to rest (leader waits)", "/Miserable @wait"),
    ("party", "@ok", "Done — carry on", "/Miserable @ok"),
    ("party", "@waiting", "Are you ready? (answers @ok when it is)", "/Miserable @waiting"),
    ("party", "@panic", "Everyone run", "/Miserable @panic"),
    ("party", "@party", "No words: 'par'. With a command: the whole party does it (go hole) and regroups", "/Miserable @party go hole"),
    ("party", "@comeback", "Walk back to this room", "/Miserable @comeback 17 1637"),
    ("party", "@ptrain ★", "Party training between MudPilots (Loot tab → Training): 'st …' a member's levels "
     "banked, 'ask', 'trip on/off', 'train <level> <map>/<room>' (the leader's order), 'done <levels>'. Only acted on "
     "with party training ticked, and orders only from the leader", "/Revolution @ptrain ask"),
]

# @auto-<x> -> settings attribute (None = not available in MudPilot)
AUTO_FLAGS = {
    "combat": "auto_combat", "nuke": "auto_nuke", "cast": "auto_combat", "heal": "auto_heal", "rest": "auto_rest",
    "bless": "auto_bless", "cash": "loot_cash", "get": "auto_loot",
    "light": "auto_light", "sneak": "auto_sneak", "hide": "auto_hide", "search": "auto_search",
    "preattack": "auto_preattack",
}

CHAT_PATTERNS = [
    ("telepath", re.compile(r"^(\w+) telepaths: (.+)$")),
    ("say", re.compile(r"^(\w+) says(?: \(to [^)]+\))? \"(.+)\"$")),
    ("gangpath", re.compile(r"^(\w+) gangpaths: (.+)$")),
    ("broadcast", re.compile(r"^Broadcast from (\w+) \"(.+)\"$")),
]
HARD_BLOCK = re.compile(r"suicide|reroll", re.I)
CHAIN_RE = re.compile(r"(?<![a-z0-9])@[a-z]", re.I)   # an @command inside an @do ('.@goto' too): never relayed
DENIED = "command invalid or not allowed"   # Talk tab can change the wording


class RemoteControl:
    def __init__(self, session):
        self.s = session
        self.holds: dict = {}            # sender -> time of their @wait
        self.hold_why: dict = {}         # sender -> what they said it was for ('@wait (confused)')
        self._recent: dict = {}          # sender -> [reply times] (flood guard)
        self._relog_at = 0.0
        self.log_lines: list = []
        self._inv_waiting: list = []    # (channel, sender, asked_at, inv_seq_before)
        self._channel = "telepath"

    @property
    def cfg(self):
        return self.s.settings

    # ------------------------------------------------------------ inbound
    # what you carry changed since the last 'i' (someone handed you something, you picked up / bought / gave / dropped)
    INV_CHANGE_RE = re.compile(r"^\w+ gives you\b|^\w+ (?:hands|gave) you\b|^you (?:took|picked up|get|got|drop(?:ped)?|"
                               r"give|gave|bought|just bought|sold|just sold|receive[ds]?|are now wearing|have removed|"
                               r"remove[ds]?|hid|stash)\b", re.I)

    def feed_line(self, text: str) -> bool:
        """Returns True if the line was a remote command we handled."""
        text = text.strip()
        if self.INV_CHANGE_RE.search(text):
            self._inv_dirty = True
        for channel, rx in CHAT_PATTERNS:
            m = rx.match(text)
            if not m:
                continue
            sender, msg = m.group(1), m.group(2).strip()
            if (channel == "telepath" or sender in self.s.state.party) and msg.startswith("{") and \
                    self.s.bosses.ingest_spawn_reply(sender, msg):
                return True
            if channel == "telepath" and msg.startswith("{") and (self.summon_asked(sender, msg) or
                                                                  self.s.partysync.answer(sender, msg) or
                                                                  self.s.comeback.answer(sender, msg)):
                return True
            # '@have log raft' → '{no}' / '{yes: 1}' (MegaMUD answers the way it was asked: telepath or say)
            if channel in ("telepath", "say") and msg.startswith("{") and \
                    self.s.bot.errands.have_answer(sender, msg):
                return True
            if channel == "telepath" and msg.startswith("{") and self.s.bot.partyflags.answer(sender, msg):
                return True
            if self._route_answer(sender, msg):
                return True
            if channel == "telepath" and not msg.startswith("@"):
                self._divert(sender, msg)
                if not msg.startswith("{"):
                    # (a '{…}' is a bot's answer — a MudPilot's or MegaMUD's, an AFK note too: answering it with our
                    #  own AFK note bounced '{AFK}' between three AFK characters — Dan, 2026-11-04)
                    self._afk_reply(sender)
            if not msg.startswith("@"):
                return False
            if self.cfg.my_name and sender.lower() == self.cfg.my_name.lower():
                return False
            self.handle(channel, sender, msg)
            return True
        return False

    def handle(self, channel: str, sender: str, msg: str):
        cfg = self.cfg
        if not cfg.remote_enabled:
            return
        if not cfg.remote_channels.get(channel, False):
            return
        if cfg.disallow_remote or (channel == "gangpath" and cfg.disallow_gangpath_remote):
            return
        if HARD_BLOCK.search(msg):
            self.s.log(f"Remote: blocked '{msg[:40]}' from {sender} (never allowed)")
            return
        parts = msg.split(None, 1)
        cmd = parts[0].lower().rstrip("!")
        args = parts[1].strip() if len(parts) > 1 else ""
        need = COMMANDS.get(cmd)
        if cmd == "@do" and self._only_ok(args):
            need = "party"                           # '@do .@ok' only ever lets the party go: any member may ask
        if cmd == "@stash" and args.lower() not in ("", "raft"):
            need = "settings"                        # '@stash <item>' changes what it picks up and hides
        if cmd == "@health" and not self.allowed(sender, "query"):
            need = "party"   # 0.8.182: anyone in the party may ask (a MegaMUD habit — Elbar spammed it at Miserable
                             # PVE, refused every time); a query permission still lets a non-member ask (Dan, 2026-11-12)
        if need is None:
            if self.allowed(sender, "query") and self._deny_ok(sender):
                self.reply(channel, sender, self._denied())
            return
        if cmd == "@ptrain" and getattr(self.s, "training", None) is not None and self.s.training.expects(sender):
            pass       # (on a training trip: a member dropped from the party / the leader whose trip it is — 0.8.200)
        elif not self.allowed(sender, need, cmd):
            self.s.log(f"Remote: {sender} not allowed {cmd}")
            if cfg.remote_warn_denied and need != "party" and self._deny_ok(sender):
                self.reply(channel, sender, self._denied())
            return
        if not self._flood_ok(sender):
            return
        if cmd not in ("@mpsync", "@ptrain"):
            self.s.log(f"Remote: {sender} → {msg[:60]}")
        self._channel = channel
        fn = getattr(self, "c_" + cmd[1:].replace("-", "_"), None)
        try:
            out = fn(sender, args) if fn else None
        except Exception as e:  # never let a bad command take the bot down
            out = f"error: {e}"
        if out:
            for line in ([out] if isinstance(out, str) else out):
                self.reply(channel, sender, line)

    def _deny_ok(self, sender) -> bool:
        """(0.8.201, bug hunt: a stranger spamming '@where' got a '{command invalid…}' back for every line — the flood
        guard only ran after the permission check — so anyone could make us spam the server.) One refusal per
        sender per 10 s."""
        d = self.__dict__.setdefault("_denied_at", {})
        now = time.time()
        if now - d.get(sender.lower(), 0) < 10:
            return False
        d[sender.lower()] = now
        return True

    def _denied(self) -> str:
        t = (self.cfg.remote_fail_msg or "").strip().strip("{}")
        return t or DENIED

    # (0.8.201, Dan) "party" commands any member of our party may always send; the rest of the "party" category
    # (@panic @party @share @makeroom @stash @unstash) comes only from our party's leader, or a "party" tick
    MEMBER_OK = {"@wait", "@ok", "@waiting", "@comeback", "@mpsync", "@ptrain", "@health", "@do",
                 "@held", "@blind", "@darkness", "@diseased", "@major", "@poisoned"}

    def _is_leader(self, sender: str) -> bool:
        x = getattr(self.s.bot, "x", None)
        try:
            ld = x.leader() if x is not None else None
        except Exception:
            ld = None
        return bool(ld) and ld.lower() == sender.lower()

    def allowed(self, sender: str, need: str, cmd: str | None = None) -> bool:
        perms = {k.lower(): v for k, v in (self.cfg.remote_players or {}).items()}.get(sender.lower(), [])
        if need == "party":
            # (0.8.201, bug hunt F2/F3 — Dan's call: 'or bool(perms)' gave every party command, '@stash' rewriting
            #  settings among them, to anyone ticked for anything, and any member could send them. Now: the
            #  "party" tick, our leader, or a member for the everyday ones in MEMBER_OK)
            if "party" in perms or self._is_leader(sender):
                return True
            return sender in self.s.state.party and (cmd is None or cmd in self.MEMBER_OK)
        return need in perms

    def _flood_ok(self, sender) -> bool:
        now = time.time()
        q = [t for t in self._recent.get(sender, []) if now - t < 10]
        if len(q) >= 12:
            return False
        q.append(now)
        self._recent[sender] = q
        return True

    # ------------------------------------------------------------ outbound
    PACE_SECS = 2.0          # between the pieces of a long answer: small gaps let the server keep up (Dan)

    def reply_all(self, channel: str, sender: str, lines):
        """A long answer in full (@inventory: no '...(more)'), one game line every PACE_SECS — Dan, 2026-11-11: 'two
        separate chat lines is fine… with a 2 second delay… small gaps to let the server catch up'."""
        q = self.__dict__.setdefault("_paced", [])
        now = time.time()
        due = max([now] + [d for d, _c in q])
        for i, line in enumerate(lines):
            for j, cmd in enumerate(self._pieces(channel, sender, line, cap=None)):
                due = now if not q and i == 0 and j == 0 else due + self.PACE_SECS
                q.append((due, cmd))

    def _paced_tick(self):
        q = getattr(self, "_paced", None)
        if not q or not self.s.telnet.connected:
            if q and not self.s.telnet.connected:
                q.clear()
            return
        if q[0][0] <= time.time():
            _due, cmd = q.pop(0)
            self.s.send(cmd, from_bot=True)

    def reply(self, channel: str, sender: str, text: str):
        for cmd in self._pieces(channel, sender, text):
            self.s.send(cmd, from_bot=True)

    def _pieces(self, channel: str, sender: str, text: str, cap=4) -> list:
        """The game lines an answer takes (the game cuts a line at 127 characters)."""
        text = "".join(ch for ch in text if 32 <= ord(ch) < 127)
        if cap:
            text = text[:460]
        if channel == "say" and self.s.state.sneaking:
            channel = "telepath"   # speaking would break a sneak
        head = {"telepath": f"/{sender} ", "say": f">{sender} ", "gangpath": "bg ", "broadcast": "br "}[channel]
        room = 127 - len(head) - 2                    # the game cuts a line at 127 characters
        parts = []
        while text:
            if len(text) <= room:
                parts.append(text)
                break
            cut = text.rfind(" ", 0, room)
            cut = cut if cut > room // 2 else room
            parts.append(text[:cut].rstrip())
            text = text[cut:].lstrip()
        return [head + "{" + p + "}" for p in ((parts[:cap] if cap else parts) or [""])]

    def _afk_reply(self, sender):
        cfg = self.cfg
        if not cfg.afk or not (cfg.afk_message or "").strip():
            return
        if cfg.my_name and sender.lower() == cfg.my_name.lower():
            return
        last = getattr(self, "_afk_told", {})
        if time.time() - last.get(sender, 0) < 300:
            return
        last[sender] = time.time()
        self._afk_told = last
        self.s.send(f"/{sender} {cfg.afk_message.strip()}", from_bot=True)

    def _divert(self, sender, msg):
        to = self.cfg.divert_to
        if to and sender.lower() != to.lower():
            self.s.send(f"/{to} {{{sender}: {msg[:200]}}}", from_bot=True)

    # ------------------------------------------------------------ hold (@wait)
    HOLD_SECS = 120          # a @wait not said again in this long is let go (a MudPilot says it every minute)

    def hold_text(self, who=None) -> str:
        """'Revolution @wait: confused' — or, from a bare @wait, what 'par' shows of them."""
        who = who or self.holding()
        if not who:
            return ""
        why = self.hold_why.get(who)
        if not why:
            st = self.s.state
            info = next((v for k, v in (st.party or {}).items() if k.lower() == who.lower()), None)
            if info and info.get("hp") is not None:
                ma = info.get("ma", -1)
                why = f"no reason given, H:{info['hp']}%" + (f" M:{ma}%" if ma is not None and ma >= 0 else "")
            else:
                why = "no reason given"
        return f"{who} @wait: {why}"

    def release_all(self, why):
        """You told the party @ok yourself ('.@ok', '@do .@ok', '@party .@ok'): every @wait is let go. A real one
        is said again within a minute (Dan, 2026-11-02: "with megamud its not uncommon for an @wait to get stuck")."""
        if self.holds:
            self.s.log(f"Let go of {', '.join(self.holds)}'s @wait ({why})")
            self.holds.clear()
            self.hold_why.clear()

    def holding(self) -> str | None:
        """Who we're waiting for (@wait). A @wait whose @ok never comes can't strand you: it's let go
        once 'par' shows them topped up for a while, if they've left the party, or after 2 minutes without
        another @wait."""
        now = time.time()
        st, cfg = self.s.state, self.cfg
        if self.s.bot.waiting_off():
            if self.holds:
                self.s.log("NoWait on — let go of " + ", ".join(self.holds) + "'s @wait")
                self.holds.clear()
            return None
        for who, t in list(self.holds.items()):
            info = next((v for k, v in st.party.items() if k.lower() == who.lower()), None) if st.party else None
            why = None
            if now - t > self.HOLD_SECS:
                why = f"{self.HOLD_SECS // 60} min without @ok or another @wait"
            elif st.party and info is None and now - t > 20:
                why = "not in the party any more"
            elif info and now - t > 45 and info.get("t", 0) > t + 30 and \
                    re.search(r"rest|medit|^$", self.hold_why.get(who, ""), re.I):
                # (topped up only answers a rest: '@wait (confused)' at full HP still means wait)
                hp, ma = info.get("hp", 0), info.get("ma", -1)
                if hp >= max(90, int(cfg.rest_until_hp or 0) - 5) and (ma < 0 or ma >= max(80, int(cfg.rest_until_ma or 0) - 10)):
                    why = f"they look ready (H:{hp}% M:{ma}%) but never sent @ok"
            if why:
                del self.holds[who]
                self.hold_why.pop(who, None)
                self.s.log(f"Done waiting for {who}: {why}")
        f = getattr(getattr(self.s, "comeback", None), "fetch", None)
        going = (f.get("name") or "").lower() if f and f.get("phase") == "going" else ""
        # someone left behind says '@wait (can't move)' + '@comeback': walking to them isn't something to hold for
        return next((w for w in self.holds if w.lower() != going), None)

    def tick(self):
        wa = getattr(self, "_where_ask", None)
        if wa and (self.s.state.locate_ok > wa[3] or time.time() - wa[2] > 6):
            self._where_ask = None                     # the room number's in (or never came): answer @where now
            self.reply(wa[0], wa[1], self.c_where(wa[1], "", checked=True))
        ga = getattr(self, "_goto_asker", None)
        if ga:
            b = self.s.bot
            why = self.stuck_why()
            if why or b.walking or time.time() - ga[2] > 60:
                self._goto_asker = None
                if why and not b.walking:
                    self.reply(ga[0], ga[1], f"can't go: {why}")
        self._inv_tick()
        self._paced_tick()
        self._ac_tick()
        self._death_tick()
        self._summon_tick()
        if self._relog_at and time.time() >= self._relog_at:
            self._relog_at = 0.0
            try:
                self.s.connect()
            except OSError as e:
                self.s.log(f"Relog failed: {e}")

    # ------------------------------------------------------------ helpers
    def _room_text(self):
        st, w = self.s.state, self.s.world
        if st.room:
            r = w.room(st.room)
            return f"{r.name} ({st.room[0]}/{st.room[1]})"
        if st.view:
            return f"{st.view.name} (room # unknown)"
        return "location unknown"

    def _activity(self):
        b, st = self.s.bot, self.s.state
        parts = []
        if b.walking and b.path:
            parts.append(("looping" if b.loop else "walking") + f" '{b.path.title}'")
        hold = self.holding()
        wo = list(getattr(b.x, "waiting_on", None) or []) if b.walking else []
        if st.in_combat:
            parts.append("fighting")
        elif st.resting:
            # Dan, 2026-11-04: say what it's waiting on, not just where it's walking — why it sat down
            why = str(getattr(b, "_rest_reason", "") or "").replace("—", "-")
            if why.startswith("waiting on") and (hold or wo):
                why = ""                                       # said below, with who and how far along
            parts.append(("meditating" if st.meditating else "resting") + (f" ({why})" if why else ""))
        mr = getattr(self.s, "msgrules", None)
        conds = [c.replace("_", " ") for c in (getattr(mr, "conditions", None) or {})]
        if conds:
            parts.append("has " + ", ".join(conds))           # disease, poison, held, confused…
        if getattr(mr, "_waiting", None):
            parts.append(f"waiting for {mr._waiting} to wear off")
        if hold:
            parts.append(f"waiting for {self.hold_text(hold)}")
        # whatever else it's waiting on (Dan, 2026-11-01: Buddy sat waiting for Evolution to rest up and @status
        # didn't say): a member resting up, someone joining, a lair refilling, another scripter, a door
        if wo and not hold:
            party = st.party or {}
            parts.append("waiting for " + ", ".join(
                f"{n} to rest up (HP {party.get(n, {}).get('hp', '?')}%, MA {party.get(n, {}).get('ma', '?')}%)" for n in wo))
        bs = str(getattr(b, "status", "") or "")
        if not wo and not hold and re.match(r"^(?:Waiting|Holding|Letting|Lair .* refills|Checking the party|Door |"
                                            r"Disarming|Bringing|Asking|Poisoned|Curing)", bs):
            parts.append(bs[0].lower() + bs[1:].replace("—", "-"))
        if not getattr(self.s.settings, "auto_combat", True) and (
                b.walking or getattr(getattr(b, "x", None), "_following", None) or (st.view and st.view.monsters)):
            parts.append("Combat OFF - not attacking")     # Dan, 2026-11-17: Buddy said just "idle" with it off
        if not parts:
            if getattr(b, "resume", None):
                return b.idle_text().replace("—", "-")    # stopped by someone's @stop: @rego carries on
            why = self.stuck_why()
            return f"idle - {why}" if why else "idle"
        return ", ".join(parts)

    def stuck_why(self) -> str:
        """Why the last Go to didn't go (Dan, 2026-10-30: '@status' said just 'idle' while Revolution sat there
        with 'No walkable route … blocked by the Town Gates archway' in his log)."""
        b = self.s.bot
        msg = (getattr(b, "no_route_msg", "") or "").split(" — MME's map")[0].strip()
        msg = msg.replace("—", "-").replace("…", "...")
        return msg[:200]

    # ------------------------------------------------------------ query
    def c_version(self, s, a):
        return f"MudPilot {__version__}"

    def c_help(self, s, a):
        if a:
            key = a if a.startswith("@") else "@" + a
            return f"{key.lower()}: " + (CATEGORIES.get(COMMANDS.get(key.lower(), ""), "unknown command"))
        mine = [c for c, need in COMMANDS.items() if self.allowed(s, need, c)]
        out, line = [], ""
        for c in mine:
            if len(line) + len(c) > 180:
                out.append(line.strip())
                line = ""
            line += c + " "
        if line:
            out.append(line.strip())
        return out or ["no commands allowed"]

    def c_health(self, s, a):
        st = self.s.state
        if not st.max_hp:
            return "HP unknown - no prompt observed yet"
        mana = f",MA={st.ma}/{st.max_ma}" if st.max_ma else ""
        pos = ", Meditating" if st.meditating else (", Resting" if st.resting else "")
        return f"HP={st.hp}/{st.max_hp}{mana}{pos}"

    def c_ptrain(self, s, a):
        """'@ptrain …' — party training (training.py). Nothing is answered here: the training code replies itself."""
        tr = getattr(self.s, "training", None)
        return tr.party_msg(s, a) if tr is not None else None

    def c_exp(self, s, a):
        """Made, rate, and the level picture — what's needed and how long, or 'ready to train to N' and the time to
        the one after. Not known yet? Read 'exp' first, then answer (Dan: don't say "type exp")."""
        st = self.s.state
        if not st.level or not getattr(st, "exp_line_at", 0):
            self._exp_ask = (s, self._channel, time.time())
            self.s.send("exp", from_bot=True)
            return None
        return self._exp_text()

    def _exp_text(self):
        st = self.s.state
        rate = st.exp_per_hour()
        return (f"{self._level_text()} · made {self._short(st.exp_gained)}"
                + (f" at {self._short(rate)}/hr" if rate > 0 else ""))

    def c_level(self, s, a):
        """Dan: level, exp to the next, and how long at the current rate — and if you can already train, how long
        to the level after that."""
        st = self.s.state
        if not st.level or not getattr(st, "exp_line_at", 0):
            # Dan: don't tell them it's unknown — look it up and answer
            self._level_ask = (s, self._channel, time.time())
            self.s.send("exp", from_bot=True)
            return None
        return self._level_text()

    def level_answer(self):
        """The 'exp' line just came in: answer an @level that was waiting on it."""
        la = getattr(self, "_level_ask", None)
        if la and time.time() - la[2] < 15:
            self._level_ask = None
            self.reply(la[1], la[0], self._level_text())
        ea = getattr(self, "_exp_ask", None)
        if ea and time.time() - ea[2] < 15:
            self._exp_ask = None
            self.reply(ea[1], ea[0], self._exp_text())

    @staticmethod
    def _short(n) -> str:
        """3,532,000 → '3.53M', 29,750 → '29.8k'."""
        n = float(n)
        if n >= 1e6:
            return f"{n / 1e6:.2f}M"
        if n >= 1e3:
            return f"{n / 1e3:.1f}k"
        return f"{n:.0f}"

    def _level_text(self):
        """Dan: "Level 15, can train to 17, 3.53M to 18 in 4 hours" — one level past what you can train."""
        st = self.s.state
        since = getattr(st, "_exp_since_line", 0) or 0
        have = (st.exp_total or 0) + since
        try:
            rate = float(self.s.stats.exp_rate(1800) or self.s.stats.exp_rate() or 0)
        except Exception:
            rate = 0.0

        def eta(n):
            if rate <= 0:
                return ""
            h = n / rate
            if h < 1:
                return f" in {max(1, round(h * 60))} min"
            hrs = f"{h:.1f}".rstrip("0").rstrip(".") if h < 10 else f"{round(h)}"
            return f" in {hrs} hour{'' if hrs == '1' else 's'}"
        need = (st.exp_needed or 0) - since
        if need > 0:
            return f"Level {st.level}, {self._short(need)} to {st.level + 1}{eta(need)}"
        from .expcalc import chart_for, exp_needed, level_for_exp
        cfg = self.s.settings
        chart = chart_for(self.s.world, st.char_class or cfg.char_class, st.race or cfg.char_race)
        if chart is None:
            return f"Level {st.level}, can train to {st.level + 1}"
        can = max(st.level + 1, level_for_exp(have, chart))      # banked exp can cover more than one level
        nxt = exp_needed(can + 1, chart) - have
        return f"Level {st.level}, can train to {can}" + (f", {self._short(nxt)} to {can + 1}{eta(nxt)}"
                                                           if nxt > 0 else "")

    def c_status(self, s, a):
        er = getattr(self.s.bot.errands, "active", None) or {}
        if er.get("note"):
            return f"{er['note']}; {self._room_text()}"
        return f"{self._activity()}; {self._room_text()}"

    def c_timer(self, s, a):
        """Boss timers (same command MudPlay uses): @timer [name]."""
        b = self.s.bosses
        mons = b.tracked()
        if a:
            mons = [m for m in mons if a.lower() in m["name"].lower()]
        if not mons:
            return f"no boss timers{' matching ' + a if a else ''}"
        rows = sorted(mons, key=lambda m: (b.status(m["num"])[1] is None, b.status(m["num"])[1] or 0))
        return [f"{m['name']}: {b.status(m['num'])[0]}" for m in rows[:5]]

    def c_spawn(self, s, a):
        """pMUD's @spawn <monster>: 'Name: dead - Next spawn: 2h 5m' / 'Name: live - Last known kill: 3h ago'."""
        b, w = self.s.bosses, self.s.world
        if not a:
            return "usage: @spawn <monster>"
        mon = w.boss_named(a) or w.identify_monster(a)
        if not mon:
            hit = [m for m in b.tracked() if a.lower() in m["name"].lower()]
            mon = hit[0] if hit else None
        if not mon:
            return f"{a}: no available data"
        return b.spawn_reply(mon)

    def c_lives(self, s, a):
        lv = self.s.state.lives
        if lv is None:
            self._stat_ask = [q for q in getattr(self, "_stat_ask", []) if time.time() - q[2] < 15]
            self._stat_ask.append((s, self._channel, time.time()))
            self.s.send("st", from_bot=True)                                  # read it, then answer
            return None
        return f"{lv} lives remaining"

    def stat_answer(self):
        """A stat read (Lives/CP) came in: answer any @lives that was waiting."""
        q, self._stat_ask = getattr(self, "_stat_ask", []), []
        now = time.time()
        for s, channel, t in q:
            if now - t < 15 and self.s.state.lives is not None:
                self.reply(channel, s, f"{self.s.state.lives} lives remaining")

    # ------------------------------------------------------------ location
    def c_where(self, s, a, checked=False):
        st = self.s.state
        lc = getattr(st, "located", None)
        if not checked and st.room and self.s.world.look_alike(st.room) and not (lc and lc[0] == st.room
                                                                               and time.time() - lc[1] < 20):
            # a room that looks like others: the board's room number first, then answer (Evolution, 2026-10-30,
            # said 8/847 from 8/16 and Revolution went to the wrong courtyard, then walked off without him)
            if self.s.bot.locate_now("asked @where"):
                self._where_ask = (self._channel, s, time.time(), st.locate_ok)
                return None
        ex = ", ".join({"N": "north", "S": "south", "E": "east", "W": "west", "NE": "northeast",
                        "NW": "northwest", "SE": "southeast", "SW": "southwest", "U": "up", "D": "down"}[d]
                       for d in sorted(st.view.exits or [])) if st.view and st.view.exits else "unknown"
        st, w = self.s.state, self.s.world
        if st.room:
            r = w.room(st.room)
            where = f"{r.name} - map {st.room[0]} room {st.room[1]}"
        elif st.candidates:
            c = list(st.candidates)[:3]
            where = (f"{w.room(c[0]).name if w.room(c[0]) else '?'} - not sure which: "
                     + " or ".join(f"map {k[0]} room {k[1]}" for k in c))
        else:
            where = self._room_text() + " - room number unknown"
        return f"{where}; exits: {ex}"

    AC_LINE = re.compile(r"armou?r\s*class|\bAC\b|\bDR\b|damage\s*resist|vs\.?\s*(?:evil|good)", re.I)

    def c_ac(self, s, a):
        """MudPilot extra: @ac — AC/DR with everything on (blesses included), vs evil and good where the
        board shows it ('stat all' on Paradigm)."""
        st = self.s.state
        if not self.s.telnet.connected:
            return f"AC {st.ac} / DR {st.dr} (last seen)"
        self._ac_waiting = getattr(self, "_ac_waiting", []) + [(self._channel, s, time.time())]
        self.s.send(self.cfg.ac_cmd or "stat all", from_bot=True)
        return None

    DEATH_LINE = re.compile(r"^\s*(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(.+?)\s*-\s*(\d+)/(\d+)\s*$",
                            re.I)

    def c_death(self, s, a):
        """MudPilot extra: @death — the last 3 deaths (when, what killed it, where), from 'pro'
        (Dan, 2026-10-30: 'Recent Deaths' at the bottom of pro)."""
        if not self.s.telnet.connected:
            return "not connected"
        self._death_waiting = getattr(self, "_death_waiting", []) + [(self._channel, s, time.time())]
        self.s.send(self.cfg.locate_cmd.strip() or "pro", from_bot=True)
        return None

    def _death_tick(self):
        waiting = getattr(self, "_death_waiting", [])
        if not waiting:
            return
        now, tl, w = time.time(), self.s.timeline, self.s.world
        for wt in list(waiting):
            channel, sender, asked = wt
            if now - asked < 2.5:
                continue
            waiting.remove(wt)
            out = []
            for t, x in tl.screen:
                m = self.DEATH_LINE.match(x) if t >= asked else None
                if m and len(out) < 3:
                    k = (int(m.group(3)), int(m.group(4)))
                    r = w.room(k)
                    out.append(f"{m.group(1)} {m.group(2)} at {r.name if r else '?'} ({k[0]}/{k[1]})")
            self.reply(channel, sender, " | ".join(out) if out else "no deaths listed")

    def _ac_tick(self):
        waiting = getattr(self, "_ac_waiting", [])
        if not waiting:
            return
        now = time.time()
        tl = self.s.timeline
        for w in list(waiting):
            channel, sender, asked = w
            if now - asked < 2.5:
                continue
            waiting.remove(w)
            lines = [x.strip() for t, x in tl.screen if t >= asked and self.AC_LINE.search(x)
                     and not x.strip().lower().startswith(("you ", "[hp"))]
            seen, out = set(), []
            for ln in lines:
                ln = re.sub(r"\s{2,}", " ", ln)
                if ln not in seen:
                    seen.add(ln)
                    out.append(ln)
            st = self.s.state
            msg = " | ".join(out)[:220] if out else f"AC {st.ac} / DR {st.dr}"
            self.reply(channel, sender, msg)

    def c_path(self, s, a):
        b = self.s.bot
        if b.walking and b.path:
            return f"{'looping' if b.loop else 'walking'} '{b.path.title}' step {b.idx + 1}/{len(b.path.steps)}"
        if b.last_path:
            return f"idle - last: '{b.last_path.title}'"
        return "idle"

    def c_who(self, s, a):
        v = self.s.state.view
        if not v:
            return "nothing seen yet"
        pl = ", ".join(v.players) or "none"
        mo = ", ".join(n for n, _r in v.monsters) or "none"
        return f"players: {pl}; monsters: {mo}"

    # ------------------------------------------------------------ inventory
    def c_inventory(self, s, a):
        """@inventory: type `i`, then answer with everything held once the listing comes in."""
        st = self.s.state
        if not self.s.telnet.connected:
            return "not connected"
        if not any(w[1] == s for w in self._inv_waiting):
            self._inv_waiting.append((self._channel, s, time.time(), st.inv_seq))
        if not any(time.time() - w[2] < 1 for w in self._inv_waiting[:-1]):
            self.s.send("i", from_bot=True)
        return None

    c_inv = c_inventory

    def _inv_tick(self):
        if not self._inv_waiting:
            return
        st, now = self.s.state, time.time()
        for w in list(self._inv_waiting):
            channel, sender, asked, seq = w
            fresh = st.inv_seq > seq
            if not fresh and now - asked < 6:
                continue
            self._inv_waiting.remove(w)
            if not fresh and not st.carrying:
                self.reply(channel, sender, "inventory didn't come back - try again")
                continue
            self.reply_all(channel, sender, self._inv_lines(stale=not fresh))   # all of it, 2 s apart

    def _inv_lines(self, stale=False):
        st = self.s.state
        items = [x.strip() for x in re.split(r",\s*", st.carrying.rstrip(".")) if x.strip()]
        keys = st.keys.rstrip(".") or "none"
        parts = [f"Carrying ({len(items)}): " + ", ".join(items) if items else "Carrying: nothing",
                 f"Keys: {keys}"]
        if st.wealth is not None:
            parts.append(f"Wealth: {st.wealth:,} copper")
        if st.enc:
            parts.append(f"Enc: {st.enc[0]}/{st.enc[1]} - {st.enc[2]} [{st.enc[3]}%]")
        if stale:
            parts[-1] += " (last known)"
        LINE = 100                             # one game line each (127 with '/Name {…}'): no item cut in two
        out, line = [], ""
        for part in parts:                     # telepath-sized pieces, broken between sections
            pieces = [part]
            if len(part) > LINE:                # one very long item list: break between items
                pieces, cur = [], ""
                for item in part.split(", "):
                    if cur and len(cur) + len(item) + 2 > LINE:
                        pieces.append(cur + ",")
                        cur = ""
                    cur += (", " if cur else "") + item
                pieces.append(cur)
            for pc in pieces:
                if line and len(line) + len(pc) + 2 > LINE:
                    out.append(line)
                    line = ""
                line += ("; " if line else "") + pc
        if line:
            out.append(line)
        return out                             # all of it: reply_all paces the lines

    def c_what(self, s, a):
        v = self.s.state.view
        if not v or not v.items:
            return "nothing on the floor"
        return ", ".join(f"{q} {n}" if q > 1 else n for q, n in v.items)

    def c_wealth(self, s, a):
        w = self.s.state.wealth
        if w is None:
            return self._defer_until_inv(s, lambda: (f"{self.s.state.wealth:,} copper"
                                                     if self.s.state.wealth is not None else "still can't read it"))
        return f"{w:,} copper"

    def c_enc(self, s, a):
        e = self.s.state.enc
        if not e:
            return self._defer_until_inv(s, lambda: (f"{self.s.state.enc[0]}/{self.s.state.enc[1]} - "
                                        f"{self.s.state.enc[2]} [{self.s.state.enc[3]}%]"
                                        if self.s.state.enc else "still can't read it"))
        return f"{e[0]}/{e[1]} - {e[2]} [{e[3]}%]"

    def c_have(self, s, a):
        if not a:
            return "@have needs an item name"
        if not self.s.state.carrying or getattr(self, "_inv_dirty", False):
            # read 'i' myself, then answer (Dan) — also when the pack has changed since the last look: Buddy gave
            # Revolution a log raft, asked '@have log raft' and got "no" from the old inventory, so it bought and
            # handed out another (2026-11-01)
            return self._defer_until_inv(s, lambda: self._have_answer(a))
        return self._have_answer(a)

    def _have_answer(self, a):
        inv = self.s.state.carrying
        if not inv:
            return "still can't read my inventory"
        # (one line each: the listing wraps — "2 / log raft" on two lines came back as "{yes: 2}" from Evolution,
        #  Dan 2026-11-01)
        # the keys line counts too: Miserable's golden idol is listed under "You have the following keys: golden
        # idol." and he answered Revolution "{no golden idol}", so Revolution wouldn't route to the Stone Chief
        # (Dan, 2026-11-14)
        keys = (getattr(self.s.state, "keys", "") or "").rstrip(". ")
        items = re.split(r",\s*", inv) + (re.split(r",\s*", keys) if keys else [])
        hits = [re.sub(r"\s+", " ", x).strip().rstrip(".") for x in items if a.lower() in re.sub(r"\s+", " ", x).lower()]
        return ("yes: " + ", ".join(hits[:5])) if hits else f"no {a}"

    ROOM_COINS = ("copper farthing", "silver noble", "gold crown")     # never platinum or runic for this
    COINS_PER_ENC = 3       # coins dropped per encumbrance point still short (each drop re-reads 'i' and goes again)

    def c_stash(self, s, a):
        """'@stash raft': the leader's loop doesn't cross water, hide the raft here (Dan, 2026-11-05: rafts are heavy).
        '@stash' (0.8.200, Dan): this room is my stash room too. Items ticked Auto-stash in Game Data → Items get
        hidden here every time I pass, without me needing a loop or stash room of my own."""
        if (a or "").strip().lower() in ("here", "room", "here all"):
            # '@stash here' (0.8.208, Dan): this room is my stash — coins and all, like setting it by hand: for the
            # loop I'm walking (Paths tab), else my default stash room (Loot tab)
            cfg, room, x = self.s.settings, self.s.state.room, self.s.bot.x
            if not room:
                return "not sure which room I'm in — try again in a moment"
            txt = f"{room[0]}/{room[1]}"
            loop = getattr(self.s.bot, "_lap_path", None)
            if loop is not None:
                ls = dict(cfg.loop_stash or {})
                ls[x.loop_key(loop)] = txt
                cfg.loop_stash = ls
                where = f"for {loop.title or 'this loop'}"
            else:
                cfg.stash_room = txt
                where = "(my default stash room)"
            cfg.save()
            self.s.log(f"{s} set my stash room to {txt} {where}")
            return f"stash room {txt} {where}: coins and Auto-stash items get hidden here"
        if (a or "").strip() and (a or "").strip().lower() != "raft":
            return self._item_flag(s, a, stash=True)        # '@stash runed stone cudgel'
        if (a or "").strip().lower() != "raft":
            cfg, room = self.s.settings, self.s.state.room
            if not room:
                return "not sure which room I'm in — try again in a moment"
            cfg.party_stash_room = f"{room[0]}/{room[1]}"
            cfg.save()
            n = len(self.s.bot.x.stash_flagged_names())
            self.s.log(f"{s} set my stash room to {cfg.party_stash_room}: Auto-stash items get hidden here")
            return (f"stash room {cfg.party_stash_room}: I'll hide my Auto-stash items here" if n else
                    f"stash room {cfg.party_stash_room} — but no items are ticked Auto-stash in my Game Data → Items")
        st = self.s.bot.stash
        if st.hide_asked():
            return None
        return "nothing to stash" if not st.busy() else None

    def _attitude(self, s, a, att):
        """'@enemy amazon shaman' / '@neutral …' / '@friend …' (0.8.208, Dan: farming nature tap off the non-hostile
        amazon shamans) — Game Data → Monsters' attitude, set remotely. '@enemy off <name>' (or 'default') = back to
        MME's alignment; '@enemy' alone lists them."""
        cfg, w = self.s.settings, self.s.world
        a = (a or "").strip().lower()
        cur = dict(getattr(cfg, "monster_attitude", None) or {})
        if not a or a == "list":
            names = sorted(n for n, v in cur.items() if v == att)
            return (f"{att}: " + ", ".join(names[:8]) + (f" +{len(names) - 8} more" if len(names) > 8 else "")) \
                if names else f"no monsters set {att}"
        off = False
        m = re.match(r"^(?:off|default|clear|no)\s+(.+)$", a) or re.match(r"^(.+?)\s+(?:off|default)$", a)
        if m:
            off, a = True, m.group(1).strip()
        names = sorted({(mm.get("name") or "").lower() for mm in (w.monsters or {}).values() if mm.get("name")})
        hit = [n for n in names if n == a] or [n for n in names if a in n]
        if not hit:
            return f"no monster called '{a}' in MME"
        if len(hit) > 1 and len({n for n in hit}) > 1 and a not in hit:
            return f"which one? " + ", ".join(hit[:5])
        name = hit[0]
        if off:
            cur.pop(name, None)
        else:
            cur[name] = att
        cfg.monster_attitude = cur
        cfg.save()
        self.s.log(f"Remote: {s} set {name} to " + ("default (MME's alignment)" if off else att))
        return f"{name}: " + ("back to default" if off else att + (" - I'll attack it" if att == "enemy" else
                                                                   " - I leave it alone unless it attacks"))

    def c_enemy(self, s, a):
        return self._attitude(s, a, "enemy")

    def c_neutral(self, s, a):
        return self._attitude(s, a, "neutral")

    def c_friend(self, s, a):
        return self._attitude(s, a, "friend")

    def c_collect(self, s, a):
        """'@collect <item>': auto-get it (Game Data → Items → Auto-get), from across the realm. 0.8.200 (Dan)."""
        return self._item_flag(s, a, stash=False)

    def _item_flag(self, s, a, stash):
        """'@collect <item>' / '@stash <item>' turn it on; '... off <item>' (or '<item> off') back to normal.
        '@collect' alone lists what it auto-gets, '@stash list' what it auto-stashes."""
        x = self.s.bot.x
        a = (a or "").strip()
        word = "stash" if stash else "collect"
        if not a or a.lower() == "list":
            names = x.stash_flagged_names() if stash else x.collect_names()
            return (f"{'auto-stash' if stash else 'auto-get'}: " + ", ".join(names[:8]) +
                    (f" +{len(names) - 8} more" if len(names) > 8 else "")) if names else \
                f"no items set to {'auto-stash' if stash else 'auto-get'}"
        off = False
        m = re.match(r"^(?:off|no|stop)\s+(.+)$", a, re.I) or re.match(r"^(.+?)\s+off$", a, re.I)
        if m:
            off, a = True, m.group(1).strip()
        name, why = x.item_by_name(a)
        if not name:
            return why
        x.set_item_flag(name, stash=stash, on=not off)
        self.s.log(f"Remote: {s} → @{word} {'off ' if off else ''}{name}")
        if off:
            return f"{name}: {'no longer stashed (still picked up)' if stash else 'back to normal'}"
        if stash:
            where = x.stash_room() or room_text_(self.s.settings.party_stash_room)
            return f"{name}: auto-get + stash" + ("" if where else " — no stash room yet: '@stash' in it")
        return f"{name}: auto-get"

    def c_unstash(self, s, a):
        """Leaving the loop for water again: search the stash and pick the raft back up."""
        st = self.s.bot.stash
        if st.get_here():
            return None
        r = st.room()
        if not r:
            return "nothing stashed"
        return f"my raft's stashed at {r[0]}/{r[1]}, not here"

    def c_makeroom(self, s, a):
        """The leader's raft hand-over came back '<me> cannot accept your offer': too heavy. Change the coins for
        bigger ones at the shop, and if that's not enough drop the cheapest coins,
        one kind at a time, re-reading 'i' after each, till the item fits (Dan, 2026-11-03: "can it have them drop
        gold so they have room for the raft?")."""
        if not a:
            return "@makeroom needs an item name"
        if not self.make_room(a, shop=True):
            return f"don't know what a {a} weighs"
        return None

    def make_room(self, item, shop=False) -> bool:
        """Drop copper, then silver, then gold (never platinum or runic) till the item fits — a re-read of 'i' after
        each kind. Picking up a stashed raft, buying one, taking one handed over (Dan, 2026-11-08: Buddy couldn't
        get his raft back for the gold he'd looted; 'at most he carries 1.3 runics in gold — not worth stopping a
        party for the night over'). In a shop, 'buy 0' first swaps the coins for bigger ones. False = its weight's
        unknown."""
        w = self.s.world
        it = w.item_names.get(item.lower()) or w.item_names.get(item.lower().rstrip("s"))
        need = int((it or {}).get("encum") or 0)
        if not need:
            return False
        self._room = {"item": item, "need": need, "t": time.time(), "dropped": [], "shop": shop}
        if shop:
            # in the shop: 'buy 0 <item>' changes your coins for the biggest ones (3000 gold crowns → 30 platinum) —
            # lighter and nothing lost (Dan). Only then drop any.
            self.s.send(f"buy 0 {item}", from_bot=True)
        self.s.send("i", from_bot=True)
        return True

    def needs_room(self, item) -> bool:
        """Known too heavy to pick this up right now (the pack's weight read, the item's known)."""
        st, w = self.s.state, self.s.world
        it = w.item_names.get(item.lower()) or w.item_names.get(item.lower().rstrip("s"))
        need = int((it or {}).get("encum") or 0)
        return bool(need and st.enc and st.enc[1] - st.enc[0] < need)

    def making_room(self) -> bool:
        return getattr(self, "_room", None) is not None

    def _room_tick(self):
        r = getattr(self, "_room", None)
        if not r:
            return
        st = self.s.state
        if time.time() - r["t"] > 60 or not st.enc:
            self._room = None
            return
        free = st.enc[1] - st.enc[0]
        if free >= r["need"]:
            self._room = None
            self.s.log(f"Room made for the {r['item']}" + (f": dropped {', '.join(r['dropped'])}" if r["dropped"] else ""))
            return
        # 0.8.201, bug hunt: only as many coins as the item needs (it dropped the whole stack of each kind — gold
        # too, then 'buy log raft' couldn't be paid for), and in a shop never below the item's price
        from .gamestate import COIN_VALUE
        spare = None
        if r.get("shop") and st.wealth is not None:
            try:
                price = self.s.trips.price_of(r["item"])
            except Exception:
                price = 0
            if price:
                spare = st.wealth - price
        kind, n = None, 0
        for k in self.ROOM_COINS:
            n = min(int(st.coins.get(k, 0) or 0), max(1, (r["need"] - free) * self.COINS_PER_ENC))
            if spare is not None:
                n = min(n, max(0, spare) // COIN_VALUE[k])
            if n > 0:
                kind = k
                break
        if not kind:
            self._room = None
            self.s.log(f"Can't make room for the {r['item']} ({free} free, needs {r['need']}): no copper, silver or "
                       "gold left to drop" + (" (not the coins its price needs)" if spare is not None else ""))
            return
        what = f"{n} {kind}{'s' if n != 1 else ''}"
        r["dropped"].append(what)
        self.s.log(f"Too heavy to take the {r['item']} ({free} free, needs {r['need']}): dropping {what}")
        self.s.send(self.cfg.drop_cmd.format(qty=n, item=f"{kind}{'s' if n != 1 else ''}"), from_bot=True)
        st.coins[kind] = max(0, st.coins.get(kind, 0) - n)
        self.s.send("i", from_bot=True)

    def _defer_until_inv(self, s, builder):
        """Inventory not read yet: type 'i', and answer when it comes back — don't tell them to type i (Dan)."""
        now = time.time()
        self._inv_ask = [q for q in getattr(self, "_inv_ask", []) if now - q[3] < 15]
        self._inv_ask.append((s, self._channel, builder, now))
        self.s.send("i", from_bot=True)
        return None

    def inv_answer(self):
        """A fresh inventory listing just came in: answer any @have / @inv that was waiting on it."""
        self._inv_dirty = False                       # a fresh listing: what we carry is known again
        self._room_tick()
        q, self._inv_ask = getattr(self, "_inv_ask", []), []
        now = time.time()
        for s, channel, builder, t in q:
            if now - t >= 15:
                continue
            try:
                out = builder()
            except Exception as e:
                out = f"error: {e}"
            if out:
                for line in ([out] if isinstance(out, str) else out):
                    self.reply(channel, s, line)

    # ------------------------------------------------------------ party
    def c_invite(self, s, a):
        v = self.s.state.view
        here = {p.split()[0].strip(".,").lower() for p in (v.players if v else []) if p.split()}
        if v and s.lower() not in here:
            # 'invite' only works in the same room (Dan, 2026-10-30: Revolution invited Buddy over and over
            # from rooms away)
            return "not inviting yet: you're not in my room"
        rj = getattr(self.s, "_rejoin", None)
        if rj and rj.get("leader", "").lower() == s.lower():
            # they want to follow us — we were waiting for them to invite us: that's the circle. We lead
            self.s._rejoin = None
            self.s.log(f"{s} asked me for an invite — I lead; not waiting for one from them")
        self._asked_invite = True                          # asked for: not held back by a disband pause
        try:
            self.s.send(f"invite {s}", from_bot=True)
        finally:
            self._asked_invite = False
        return f"inviting {s}"

    def c_disband(self, s, a):
        """'@disband' (Dan, 2026-11-01): the MudPilot way to '@do disband party' — and the same minute with no
        automatic invites, so the party can re-form under someone else."""
        self._in_do = True
        try:
            self.s.send("disband party", from_bot=True)
        finally:
            self._in_do = False
        self.s.log(f"{s}: @disband")
        return "disbanded - no auto-invites for a minute"

    INVITED_RE = re.compile(r"^(\w+) has invited you to (?:follow|join) (?:him|her|them|it)\b", re.I)

    def note_invite(self, text: str):
        """Dan, 2026-11-04: an invite from someone with @ commands here is joined straight away — no waiting for
        their '@join' telepath (a player without MudPilot never sends one)."""
        m = self.INVITED_RE.match(text.strip())
        if not m or self.cfg.disallow_remote:
            return
        who = m.group(1)
        perms = {k.lower(): v for k, v in (self.cfg.remote_players or {}).items()}.get(who.lower())
        if not perms:
            return
        if self.keep_my_loop(who):
            return
        self.s.log(f"{who} invited you (they have @ commands here) — joining")
        self.c_join(who, "")

    def keep_my_loop(self, who: str) -> bool:
        """0.8.179: an automatic join (their invite) while I'm walking my own loop would stop the loop — and if they
        run none, the whole party stands still (Evolution joined Buddy at 17/183 after a restart; nobody hunted).
        Ask them to follow me instead. An explicit @join from them is still obeyed."""
        b = self.s.bot
        rg = getattr(self.s, "_regroup", None) or {}
        mine = (b.walking and b.loop) or bool(getattr(b, "loop", False) and getattr(b, "path", None) is not None)
        regrouping = bool(rg) and who.lower() in {n.lower() for n in rg.get("names", [])} and mine
        if not (b.walking and b.loop) and not regrouping:
            return False
        rj = getattr(self.s, "_rejoin", None) or {}
        if who.lower() in ((rj.get("leader") or "").lower(), (getattr(b.x, "_followed", None) or "").lower()):
            return False                     # my own leader asking me back in (a restart): rejoin as before
        last = getattr(self, "_invited_back", {})
        self._invited_back = last
        ago = time.time() - last.get(who.lower(), 0)
        if ago < 0.5:
            # the same invite line, seen by both join rules (0.8.201, party hunt: this test came after the name
            # comparison, so the second rule read the first one's 'invite' as "they invited me again" and joined —
            # 'invite Miserable' AND 'join Miserable' for one line)
            return True
        if ago < 60 and not regrouping:
            # (regrouping after a restart with our loop: they're the ones coming back to us — never give way)
            # they invited me again after I invited them back: they're running a loop too. One of us has to give
            # way or we hunt apart — the name that sorts first leads (both sides work it out the same way)
            if (self.cfg.my_name or "").lower() > who.lower():
                self.s.log(f"{who} is running a loop too — joining them (they lead)")
                return False
        last[who.lower()] = time.time()
        self.s.send(f"invite {who}", from_bot=True)
        self.s.log(f"{who} invited me, but I'm running my loop — inviting them to follow me instead")
        return True

    def c_join(self, s, a):
        b = self.s.bot
        if b.walking and b.loop and time.time() - getattr(self, "_invited_back", {}).get(s.lower(), 0) < 60:
            # I lead my loop and just invited them back: their '@join' (sent with their own invite) mustn't pull me
            # into their party — they join me (0.8.212, Dan 2026-11-19: Revolution joined Miserable; both stood)
            self.s.log(f"{s} sent @join, but I'm running my loop and just invited them — not joining (they follow me)")
            return None
        last = getattr(self, "_joined", {})
        if time.time() - last.get(s.lower(), 0) < 15:
            return None                              # joined them just now (their invite, then their @join)
        last[s.lower()] = time.time()
        self._joined = last
        self.s.send(f"join {s}", from_bot=True)
        self.s.send("par", from_bot=True)            # see who's in it (no telepath back: nothing to say yet)
        return None

    def c_panic(self, s, a):
        x = self.s.bot.x
        if self.cfg.ignore_panic_following and not x.leading():
            return None
        self.s.log(f"{s} sent @panic — running")
        self.s.bot.flee()
        return None

    def c_party(self, s, a):
        if (a or "").strip():
            return self._party_move(s, a)
        if self.cfg.ignore_party_following and not self.s.bot.x.leading():
            return None
        self.s.send("par", from_bot=True)
        return None

    def _party_move(self, s, a):
        """'@party go hole' from our leader (or a party member): do it too — the whole party goes through. The
        party breaks on the way; nobody @comebacks anybody, and on the other side we ask to be invited back
        (Dan, 2026-10-30: Buddy and Evolution stood still, then sent @comeback and pulled Revolution back)."""
        st, x = self.s.state, self.s.bot.x
        lead = getattr(x, "_following", None) or ""
        if s not in (st.party or {}) and s.lower() != lead.lower():
            return None                              # not our party: not ours to follow
        if self._only_ok(a):
            return self._do_parts(s, a)                # '@party .@ok': say it, no party move
        if CHAIN_RE.search(a) or HARD_BLOCK.search(a):
            self.s.log(f"Remote: refused {s}'s @party — it would pass an @command on")
            return None
        self.s.comeback.party_move()
        for part in re.split(r"\^M", a, flags=re.I):
            if part.strip():
                self.s.send(part.strip(), from_bot=True)
        self.s.log(f"{s}: @party {a.strip()} — going through with the party")
        if lead.lower() == s.lower():
            now = time.time()
            # the other side: back in their party (an @invite once we're in the same room), no @rego needed
            self.s._rejoin = {"leader": s, "t": now, "asked": now - 8, "tries": 0, "joined": False,
                              "ask_first": True, "no_rego": True}
        return None

    def c_wait(self, s, a):
        if self.cfg.ignore_wait_leading and self.s.bot.x.leading():
            return None
        if self.s.bot.waiting_off():
            self.s.log(f"{s} said @wait — ignored (NoWait is on)")
            return None
        again = s in self.holds
        self.holds[s] = time.time()
        why = (a or "").strip().strip("()").strip()
        if why:
            self.hold_why[s] = why[:40]
        if not again:
            self.s.log(f"Holding for {s} (@wait" + (f": {why[:40]})" if why else " — no reason given)"))
        return None

    def c_ok(self, s, a):
        if self.holds.pop(s, None):
            self.hold_why.pop(s, None)
            self.s.log(f"{s} sent @ok — released")
        return None

    @staticmethod
    def _only_ok(a) -> bool:
        """'@do .@ok' / '@party .@ok': the one @command an @do may pass on — it only ever lets a party go."""
        rest = re.sub(r"(?<![a-z0-9])@ok\b", "", a or "", flags=re.I)
        return rest != (a or "") and not CHAIN_RE.search(rest)

    def c_waiting(self, s, a):
        st = self.s.state
        if not (st.resting or st.in_combat):
            self.s.send(f"/{s} @ok", from_bot=True)   # a bare @ok back, as MegaMUD does
        return None

    def c_comeback(self, s, a):
        if self.s.comeback.moving_together():
            self.s.log(f"{s} sent @comeback while the party goes through together — ignored")
            return None
        m = re.match(r"^\s*(?:map\s*)?(\d+)\s*(?:/|,|\s|\s*room\s*)\s*(\d+)", a or "", re.I)   # '3 606' as well as '3/606'
        cb = self.s.comeback
        in_party = any(n.lower() == s.lower() for n in (self.s.state.party or {}))
        if not m:
            # MegaMUD's plain @comeback (Dan, 2026-11-02: "there will be a lot of players still on megamud"): ask
            # where they are, and with no answer go back along our own trail until we see them — then invite
            cb._ask_where(s)
            cb.fetch["no_invite"] = in_party
            self.s.log(f"{s} sent @comeback — finding them (@where, then back along our trail)")
            return "coming back for you"
        key = (int(m.group(1)), int(m.group(2)))
        if not self.s.world.room(key):
            return f"room {key[0]}/{key[1]} not in MME data"
        if tuple(self.s.state.room or ()) == key or cb._here(s):
            # already together: no walk (Dan, 2026-11-11: Revolution's @comeback for the room we were both standing in
            # set off a Go to — flung out of the Dao Lord's room a moment later, it tried to walk back through the portal)
            if not in_party:
                self.s.send(f"invite {s}", from_bot=True)
            self.s.log(f"{s} sent @comeback {key[0]}/{key[1]} — we're together already, not walking")
            return "we're in the same room"
        cb._ask_where(s, ask=False)
        cb.fetch.update(phase="going", room=key, no_invite=in_party)   # there: invite them (unless still partied)
        if cb.meet_outside_toll(cb.fetch, key):
            # (Dan, 2026-11-17: 4 × 8 runic into the Training Hall) — not ignored: met outside the toll instead
            st_ = cb.fetch.get("room") if cb.fetch else None
            return f"there's a toll on the way — waiting for you at {st_[0]}/{st_[1]}" if st_ else "can't get there"
        return self._goto_bg(s, key, f"{key[0]}/{key[1]}").replace("walking to", "coming to")

    def c_share(self, s, a):
        return "@share isn't available in MudPilot yet"

    # ------------------------------------------------------------ execute / move
    def c_do(self, s, a):
        if not a:
            return "@do needs a command"
        if CHAIN_RE.search(a) and not self._only_ok(a):
            # no passing @commands on (Dan, 2026-10-30, as MegaMUD does): someone you trust could make you send
            # '/Buddy @goto …' — and an enemy who shares a friend with you would be steering everyone who trusts it
            self.s.log(f"Remote: refused {s}'s @do — it would pass an @command on to someone else")
            return "can't @do another @command"
        self._in_do = True                                 # (a 'disband' in here is meant: see session.send)
        try:
            return self._do_parts(s, a)
        finally:
            self._in_do = False

    def _do_parts(self, s, a):
        for part in re.split(r"\^M", a, flags=re.I):      # '@do go portal^Me^M' = go portal, then e
            if part.strip():
                if HARD_BLOCK.search(part):
                    continue
                md = re.match(r"^\s*disarm\s+trap\s+(\w+)", part, re.I)
                if md:
                    # the party's trap-disarmer: report back when it's done (Dan, 2026-11-01)
                    self.s.bot._disarm_for = {"who": s, "dir": md.group(1).lower(), "t": time.time()}
                self.s.send(part.strip(), from_bot=True)
        return "ok"

    def c_goto(self, s, a):
        if not a:
            return "@goto requires a destination"
        self.s.bot._called_off = None                     # asked for by name: a called-off comeback doesn't block it
        w = self.s.world
        m = re.fullmatch(r"\s*(?:map\s*)?(\d{1,3})\s*(?:/|,|\s|\s*room\s*)\s*(\d{1,5})\s*", a, re.I)
        if m:
            # a map and room number: '@goto 17 1626', '17,1626', 'map 17 room 1626' (Dan, 2026-10-30) — not only 17/1626
            key = (int(m.group(1)), int(m.group(2)))
            r = w.room(key)
            if not r:
                return f"room {key[0]}/{key[1]} isn't on the map"
            if self.s.state.room == key:
                return f"already at {r.name} ({key[0]}/{key[1]})"
            return self._goto_bg(s, key, f"{r.name} ({key[0]}/{key[1]})")
        # the Goto list's names first — your Rooms.md places, path ends, MME's shops and NPCs ('@goto bank of godfrey',
        # '@goto tree house (aldreth)'): the names are what people remember, not the numbers (Dan, 2026-11-01)
        q = re.sub(r"\s+", " ", a.strip().lower())
        named = []
        try:
            named = [(n, tuple(k)) for _g, n, k in self.s.known_rooms()]
        except Exception:
            pass
        named += [(n, tuple(k)) for _g, n, k in (w.places() if hasattr(w, "places") else [])]
        clean = lambda n: re.sub(r"[\s\-+]*\d{1,3}[ /]\d{1,5}\s*$", "", re.sub(r"\s+", " ", (n or "").lower())).strip()
        exact = [(n, k) for n, k in named if clean(n) == q and w.room(k)]
        part = exact or [(n, k) for n, k in named if q in clean(n) and w.room(k)]
        if part:
            names = list(dict.fromkeys(clean(n) for n, _k in part))
            if len(names) > 1 and not exact:
                return f"'{a}' matches {len(names)} places: " + ", ".join(n for n in names[:4]) + \
                    (" …" if len(names) > 4 else "") + " - say which"
            keys = list(dict.fromkeys(k for _n, k in part))
            hits = [w.room(k) for k in keys]
        else:
            hits = w.search_rooms(a, limit=50)
            exact = [r for r in hits if r.name.lower() == a.lower()]
            hits = exact or hits
        if not hits and len(a) >= 3:
            # a monster's name: where it stands / spawns / lairs (Dan, 2026-10-30: '@goto sleazy shopkeeper')
            keys = [k for m in w.search_monsters(a, limit=5) for k, _how in w.monster_rooms(m["num"])]
            hits = [w.room(k) for k in dict.fromkeys(keys) if w.room(k)]
        if not hits:
            return f"no match for '{a}'"
        if len(hits) > 1:
            here = self.s.state.room
            if not here:
                return f"'{a}' matches {len(hits)} rooms - send map/room"
            # nearest match wins, like MegaMUD — one search to all of them (not one per room: that froze it)
            route = w.route(here, frozenset(r.key for r in hits), level=self.s.state.level or None,
                            avoid=self.s.bot.avoid_set())
            if route:
                end = route[-1].to
                hits = [r for r in hits if r.key == end] or hits[:1]
            else:
                # no plain way to any of them (keys, doors on the way): the first one — the Go to fetches keys
                # / bashes doors itself, and says why if it can't
                hits = hits[:1]
        r = hits[0]
        if self.s.state.room == r.key:
            return f"already at {r.name} ({r.key[0]}/{r.key[1]})"
        return self._goto_bg(s, r.key, f"{r.name} ({r.key[0]}/{r.key[1]})")

    def _goto_bg(self, sender, key, where):
        """Plan the Go to on a worker thread (bgplan) so the window doesn't freeze; answer when it's worked out.
        A question on the way (take Negative Power Plane?) goes to whoever sent the command: 'y' or 'n'."""
        from . import bgplan
        b, channel = self.s.bot, self._channel
        after = getattr(self.s, "tk_after", None)
        if getattr(b, "_planning", False):
            return "busy working out another route - try again in a moment"
        if hasattr(self.s, "hands_on"):
            self.s.hands_on(f"@goto from {sender}")  # asked to go: Hands off would leave it standing there

        def done(ok, err):
            if err is not None:
                self.reply(channel, sender, f"error planning the route: {err}")
            elif not ok:
                self.reply(channel, sender, f"can't go: {self.stuck_why() or 'no route from here'}")
            elif getattr(b, "_pending_goto", None) or getattr(b, "_pending_abil", None):
                # it reads your inventory / quest abilities first and plans after: tell them if that plan fails
                self._goto_asker = (channel, sender, time.time())
                self.reply(channel, sender, f"walking to {where}")
            else:
                self.reply(channel, sender, f"walking to {where}")
        ask = self._remote_ask(channel, sender) if after else None
        bgplan.plan(self.s, lambda a: b.goto(key, ask=a), done, ask=ask, after=after, ask_in_thread=True)
        return f"working out the route to {where} - one moment" if after else ""

    ROUTE_ASK_SECS = 90

    def _remote_ask(self, channel, sender):
        """The route question for the one who sent the @command (Dan, 2026-10-30): 'take Negative Power Plane?
        reply y or n'. Runs on the planner's thread and waits for the answer; no answer → No (the safe way)."""
        import threading

        def ask(short, scenic, area, kind="area"):
            if kind == "door":
                # 0.8.201 (Dan): a door nobody in the party can open — try anyway? No is the default
                q = f"{area} - nobody in the party can open it. try anyway? reply y or n"
            elif scenic is None:
                q = f"the only way goes through {area} ({short} rooms). take {area}? reply y or n"
            else:
                q = (f"take {area}? y = through it ({short} rooms), n = the safe way round ({scenic} rooms). "
                     f"reply y or n")
            ev = threading.Event()
            self._route_q = {"sender": sender.lower(), "ev": ev, "v": False, "t": time.time()}
            self.reply(channel, sender, q)
            ev.wait(self.ROUTE_ASK_SECS)
            box, self._route_q = self._route_q, None
            if not ev.is_set():
                self.reply(channel, sender, f"no answer - not going through {area}")
            self.s.log(f"Remote: {sender} said {'yes' if box and box['v'] else 'no'} to going through {area}")
            return bool(box and box["v"])
        return ask

    def _route_answer(self, sender, msg) -> bool:
        """'y' / 'n' (or @y / @n, yes / no) from the one we asked a route question."""
        q = getattr(self, "_route_q", None)
        if not q or sender.lower() != q["sender"]:
            return False
        a = msg.strip().lower().lstrip("@").strip("{}.! ")
        if a not in ("y", "yes", "n", "no"):
            return False
        q["v"] = a.startswith("y")
        q["ev"].set()
        return True

    def c_mpsync(self, s, a):
        """MudPilot-to-MudPilot party sync (see partysync.py)."""
        return self.s.partysync.command(s, a)

    SUMMON_ASK = "summon: where are you? send @summon <map> <room>, e.g. @summon 10 297"

    def c_summon(self, s, a):
        """MudPilot extra: '@summon 10 297' (or 10/297) walks me to that room to meet you; plain
        '@summon' asks where you are (a MudPilot sender answers that by itself)."""
        m = re.search(r"(\d+)\s*[/,\s]\s*(\d+)", a or "")
        if not m:
            return self.SUMMON_ASK
        key = (int(m.group(1)), int(m.group(2)))
        w, b, st = self.s.world, self.s.bot, self.s.state
        r = w.room(key)
        if not r:
            return f"no room {key[0]}/{key[1]} in my map data"
        if st.room == key:
            return f"already here: {r.name} ({key[0]}/{key[1]})"
        if not st.room:
            # in the dark / just logged in: find out where (pro), then go — no "try again" (Buddy, 2026-10-28)
            self._summon_wait = {"by": s, "args": a, "channel": self._channel, "t": time.time()}
            b.locate_now("summoned")
            return "finding out where I am - on my way in a moment"
        if b.walking:
            b.stop(f"Summoned by {s}")            # Rego (or @rego) goes back to the loop afterwards
        if not b.goto(key):
            return f"no route from here to {r.name} ({key[0]}/{key[1]})"
        b.set_mode("auto")
        self._summon = {"by": s, "to": key, "channel": self._channel, "t": time.time()}
        n = len(b.path.steps) if b.path else 0
        self.s.log(f"Summoned by {s} to {r.name} ({key[0]}/{key[1]}) — {n} steps")
        return f"on my way to {r.name} ({key[0]}/{key[1]}), {n} steps"

    def _summon_tick(self):
        sw = getattr(self, "_summon_wait", None)
        if sw:
            if self.s.state.room:
                self._summon_wait = None
                ch, self._channel = getattr(self, "_channel", None), sw["channel"]
                msg = self.c_summon(sw["by"], sw["args"])
                self._channel = ch
                if msg:
                    self.reply(sw["channel"], sw["by"], msg)
            elif time.time() - sw["t"] > 60:
                self._summon_wait = None
                self.reply(sw["channel"], sw["by"], "still not sure where I am - summon me again")
            elif self.s.bot.ready("summon_locate", 16):
                self.s.bot.locate_now("summoned")
        sm = getattr(self, "_summon", None)
        if not sm:
            return
        b, st = self.s.bot, self.s.state
        if st.room == sm["to"] and not b.walking:
            self._summon = None
            r = self.s.world.room(sm["to"])
            self.reply(sm["channel"], sm["by"], f"here: {r.name if r else ''} ({sm['to'][0]}/{sm['to'][1]})")
            if not any(n.lower() == sm["by"].lower() for n in (st.party or {})):
                # there: ask them in (Dan, 2026-11-02: "it should arrive and invite the player")
                self.s.send(f"invite {sm['by']}", from_bot=True)
        elif not b.walking and time.time() - sm["t"] > 5:
            self._summon = None                    # stopped on the way (you took over, a fight, a door)

    def summon_asked(self, sender, msg) -> bool:
        """We telepathed someone @summon and their MudPilot asks where we are: answer with our room."""
        asked = getattr(self, "_summon_sent", {}).get(sender.lower(), 0)
        if time.time() - asked > 120 or not msg.strip("{} ").lower().startswith("summon: where"):
            return False
        here = self.s.state.room
        if here:
            self.s.send(f"/{sender} @summon {here[0]} {here[1]}", from_bot=True)
        return True

    def c_loop(self, s, a):
        if not a:
            return "@loop requires a name"
        b = self.s.bot
        if a.strip().lower() in NAMES:
            return b.peruse.start()
        if a.lower() == "last":
            if not b.last_path:
                return "no loop has run yet this session"
            b.start_path(b.last_path, loop=True)
            return f"looping '{b.last_path.title}'"
        low = a.lower()
        found = [p for p in self.s.paths if low == p.title.lower()] or \
                [p for p in self.s.paths if low in p.title.lower() or low in p.filename.lower()]
        if not found:
            return f"no loop named '{a}'"
        if len(found) > 1:
            return f"'{a}' matches {len(found)}: " + ", ".join(p.title for p in found[:4])
        mp = found[0]
        if mp.resolved and mp.steps[0].room and self.s.state.room and \
                not any(st_.room == self.s.state.room for st_ in mp.steps):
            b.goto(mp.steps[0].room, then=mp)
            return f"walking to the start of '{mp.title}', then looping"
        b.start_path(mp, loop=True)
        return f"looping '{mp.title}'"

    def c_stop(self, s, a):
        b = self.s.bot
        cb = getattr(self.s, "comeback", None)
        if cb is not None:
            cb.away[s.lower()] = time.time()     # (a restart): if they log off now, they come back here — no chase
            if cb.fetch or cb.missing or getattr(cb, "queued", None):
                # (0.8.201, party hunt: stop() only ends the chase for "Stopped by you" — fetching Revolution, his
                #  @stop left the fetch open and 30 s later comeback's _finish restarted the loop by itself)
                chasing = list(dict.fromkeys(([cb.fetch["name"]] if cb.fetch else []) + list(cb.missing)))
                cb.fetch, cb.missing, cb.queued = None, {}, []
                if chasing:
                    self.s.log(f"Not going after {', '.join(chasing)} any more ({s}'s @stop)")
        if b.peruse.stop() and not b.walking:
            return "stopped perusing the books"
        lc = getattr(self.s, "lair_camp", None)
        if lc is not None and lc.on and not b.walking:
            # camping between walks (waiting by a lair, fighting in one): @stop ends it too (0.8.201)
            b.drop_parked()
            lc.stop(f"Stopped by {s} (@stop)")
            return "stopped camping lairs"
        if not b.walking:
            parked = any(getattr(b, n, None) for n in ("_pending_goto", "_pending_abil", "_goto_retry", "_await_inv",
                                                       "_goto_after_who")) or getattr(b, "_planning", False)
            b.drop_parked()                       # a Go to still being worked out / waiting on 'i' never sets off
            if parked:
                return "stopped (the trip hadn't set off yet)"
            if getattr(b, "resume", None):
                # 0.8.185: already stopped — a second @stop wipes what Rego would carry on with (Dan, 2026-11-12:
                # PVEREV kept an old 'Rego carries on to 13/825' on the Pirate Galleon through two restarts)
                b.resume, b.stop_note = None, ""
                self.s.log(f"{s}'s second @stop — Rego cleared")
                return "already @stopped - Rego cleared"
            return "already @stopped"
        b.stop(f"Stopped by {s} (@stop)")
        b.stop_note = f"{s}'s @stop"
        return f"stopped at {self._room_text()}"

    def c_hunt(self, s, a):
        if not a:
            return self.hunt_list()
        if a.strip().lower() in ("off", "on"):
            return self.hunt_switch(a.strip().lower() == "on")
        mon = self.s.bosshunt.named(a)
        if not mon:
            return f"no monster called '{a}'"
        from . import bgplan
        b, channel, after = self.s.bot, self._channel, getattr(self.s, "tk_after", None)
        if getattr(b, "_planning", False):
            return "busy working out another route - try again in a moment"
        bgplan.plan(self.s, lambda _a: self.s.bosshunt.hunt_now(mon),
                    lambda res, err: self.reply(channel, s, f"error planning the hunt: {err}" if err else res),
                    after=after)
        return f"working out the hunt for {mon['name']} - one moment" if after else ""

    def c_camp(self, s, a):
        """0.8.201 (Dan): lair camping from a party member — start / stop / list. Starting is refused on a follower
        (LairCamp.start says why): the leader camps and the party follows."""
        lc = self.s.lair_camp
        w = (a or "").strip().lower()
        if w in ("", "list", "status"):
            return lc.list_lines()
        if w in ("start", "on", "go"):
            return lc.start(by=s)
        if w in ("stop", "off"):
            return lc.stop(f"Stopped by {s} (@camp stop)")
        return "@camp start, @camp stop or @camp list"

    def hunt_switch(self, on: bool):
        """Dan, 2026-11-04: '@hunt off' when you take over leading the party — no more hunting at all: the one
        under way ends where it is (no walk back to the loop), and nothing due starts. '@hunt on' turns it back on."""
        s, cfg, bh = self.s, self.s.settings, self.s.bosshunt
        cfg.boss_hunt_on = cfg.boss_farm_on = on
        cfg.save()
        if on:
            return "boss hunting on"
        s._hunt_resume = None
        a, bh.active = getattr(bh, "active", None), None
        if a:
            s.bot._boss_ok = None
            if s.bot.walking:
                s.bot.stop("Boss hunt off")
            return f"boss hunting off - stopped hunting {a.get('name', 'the boss')} here"
        return "boss hunting off"

    def hunt_list(self):
        """Dan, 2026-11-04: a bare @hunt shows the bosses being hunted — the one it's after now first, then each
        ticked for hunting with where its clock stands (or when it looks again, for one it never caught)."""
        bh, b = self.s.bosshunt, self.s.bosses
        act = getattr(bh, "active", None) or {}
        out = []
        if act.get("name"):
            lairs = act.get("lairs") or 0
            left = len(act.get("sweep") or [])
            out.append(f"hunting {act['name']} now" + (f" - {lairs - left} of {lairs} lairs checked" if lairs else ""))
        now = time.time()
        for num, rec in sorted(b.data.items(), key=lambda kv: (b.status(kv[0])[1] is None, b.status(kv[0])[1] or 0)):
            if not rec.get("hunt") or str(act.get("num")) == str(num):
                continue
            mon = self.s.world.monsters.get(int(num))
            if not mon:
                continue
            txt = b.status(num)[0]
            if rec.get("check_at") and not rec.get("dead_since"):
                left = rec["check_at"] - now
                txt += f" - looking again {'in ' + fmt_dur(left) if left > 0 else 'now'}"
            out.append(f"{mon['name']}: {txt}")
        if not out:
            return "not hunting any bosses (@hunt <name> to go after one)"
        return out[:6]

    def c_flags(self, s, a):
        """Dan, 2026-11-04: ask a character for its quest flags. Answers from the last 'abil' read (kept between
        sessions) and has it read them again, so asking twice gives the fresh ones."""
        b, cfg = self.s.bot, self.s.settings
        rd = getattr(b, "_abil_read", None)
        when = (f"read {fmt_dur(time.time() - rd[1])} ago" if rd and rd[0] == "done" else "from last session")
        b._quest_poke = time.time()                  # read them again a few seconds from now
        held = {str(k): v for k, v in (cfg.known_abils or {}).items() if b.is_quest_flag(k)}
        a = a.strip().lower()
        if not a:
            if not held:
                return "no quest flags known yet - reading them now, ask again in a moment"
            flags = ", ".join(b.flag_text(k, v) for k, v in sorted(held.items(), key=lambda kv: int(kv[0])))
            return f"quest flags ({when}): {flags}"
        w = self.s.world
        names = {**(getattr(w, "abil_names", {}) or {}), **self.s.state.abil_names}
        if a.isdecimal():                            # (0.8.201, bug hunt: not isdigit — '²' then broke int())
            pick = [a]
        else:
            pick = [k for k in held if a in b.flag_name(k).lower()] or                    sorted(str(k) for k, nm in names.items() if a in (nm or "").lower())
        if not pick:
            return f"no quest flag called '{a}'"
        if not cfg.known_abils and not (rd and rd[0] == "done"):
            # never read on this character (new one / fresh install): 'not set' read to the leader as a sure
            # "doesn't have it" (0.8.221, bug hunt). This isn't a flag answer, so the leader counts it as no answer yet
            return "quest flags not read yet - reading them now, ask again in a moment"
        out = []
        for k in pick[:3]:
            v = held.get(k)
            txt = b.flag_text(k, v) if v is not None else b.flag_text(k, "not set")
            hint = w.quest_hint(int(k), None, v if isinstance(v, int) else None).split(" — needs")[0]
            nxt = (f" - {hint}" if hint else (" - done" if isinstance(v, int) else ""))
            out.append((txt + nxt)[:115])               # one telepath line (the tail went out alone as '{= 11}')
        return out

    def c_rego(self, s, a):
        b = self.s.bot
        if b.walking:
            return "already moving"
        leader = getattr(b.x, "_following", None)
        if leader:
            b.resume = None              # following someone: they walk — no trip (or old loop) of our own
            return f"following {leader} — nothing of my own to carry on"
        cb = getattr(self.s, "comeback", None)
        if cb is not None:
            cb.away.pop(s.lower(), None)             # they're back
            still = [n.capitalize() for n in list(cb.away) if cb.stepped_away(n) and n != s.lower()]
            if still:
                # someone else who stopped us for a restart isn't back yet: Revolution's @rego sent Buddy off and
                # left Evolution behind, still logging in (Dan, 2026-11-04). Go when they're following again.
                cb.rego_when_back = (s, time.time())
                self.s.log(f"{s} sent @rego — waiting for {', '.join(still)} (restarting) first")
                return f"waiting for {', '.join(still)} to get back first"
        r = getattr(b, "resume", None)
        if r and (r.get("target") or r.get("path")):
            # what we were doing when stopped — a Go to too (Revolution, 2026-10-30: @rego found 'nothing')
            where = f"{r['target'][0]}/{r['target'][1]}" if r.get("target") else f"'{r['path'].title}'"
            if b.rego():
                return f"carrying on to {where}"
            return f"can't carry on to {where}: {self.stuck_why() or 'no route'}"
        if not b.last_path:
            self.s.log(f"{s} sent @rego — nothing to carry on with")
            return "nothing to resume"
        b.start_path(b.last_path, loop=b.last_loop)
        return f"resuming '{b.last_path.title}'"

    # ------------------------------------------------------------ settings
    def _auto(self, name, a):
        attr = AUTO_FLAGS[name]
        if attr is None:
            return f"@auto-{name}: not available in MudPilot"
        val = a.strip().lower()
        if val in ("on", "off", "1", "0", "true", "false", "yes", "no"):
            setattr(self.cfg, attr, val in ("on", "1", "true", "yes"))
            self.cfg.save()
            self.s.on_settings_changed()
        return f"@auto-{name}: {'on' if getattr(self.cfg, attr) else 'off'}"

    def __getattr__(self, item):
        if item.startswith("c_auto_") and item[7:] in AUTO_FLAGS:
            return lambda s, a, n=item[7:]: self._auto(n, a)
        raise AttributeError(item)

    def c_attack_last(self, s, a):
        """MegaMUD's '@attack-last on|off' (Dan, 2026-10-28: ignored till now): let the party's tougher members
        start the fight and draw the monsters' attention; this character joins in after them."""
        val = (a or "").strip().lower()
        if val in ("on", "off", "1", "0", "true", "false", "yes", "no"):
            self.cfg.attack_last = val in ("on", "1", "true", "yes")
            self.cfg.save()
            self.s.on_settings_changed()
            self.s.log(f"@attack-last {'on' if self.cfg.attack_last else 'off'} (from {s})")
        return f"@attack-last: {'on' if self.cfg.attack_last else 'off'}"

    def c_auto_all(self, s, a):
        val = a.strip().lower()
        if val in ("on", "off"):
            self.s.bot.paused = (val == "off")
            if val == "off":
                self.s.log("All automation paused by @auto-all off")
        return f"@auto-all: {'off' if self.s.bot.paused else 'on'}"

    def c_settings(self, s, a):
        return ", ".join(f"{n} {'on' if getattr(self.cfg, at) else 'off'}" for n, at in AUTO_FLAGS.items() if at) + \
            (" (all paused)" if self.s.bot.paused else "")

    # ---- quick setting changes (MudPilot extra): @nuke 2 · @rest min70 max90 · @medi min30 max80 · @heal 60
    def _pct_args(self, a):
        """'min70 max90' / '70 90' / 'max 85' → (min, max), either may be None."""
        mn = mx = None
        toks = re.findall(r"(min|max)?\s*(\d{1,3})", (a or "").lower())
        for i, (kind, num) in enumerate(toks):
            v = max(0, min(100, int(num)))
            if kind == "max" or (not kind and i == 1):
                mx = v
            else:
                mn = v
        return mn, mx

    def _changed(self, s, what):
        self.s.log(f"{s} changed {what} (remote)")
        self.s.on_settings_changed()
        self.cfg.save()

    def c_nuke(self, s, a):
        m = re.search(r"\d+", a or "")
        if m:
            n = max(1, min(20, int(m.group())))
            self.cfg.multi_min_mobs, self.cfg.use_area_min, self.cfg.auto_nuke = n, True, True
            self._changed(s, f"area spells to {n}+ monsters")
        return f"area spell on {self.cfg.multi_min_mobs}+ monsters" + ("" if self.cfg.use_area_min else " (off)")

    def c_pvp(self, s, a):
        w = (a or "").strip().lower()
        cfg = self.cfg
        if w in ("on", "off"):
            on = w == "on"
            cfg.hangup_on_pvp = not on
            if on:
                cfg.pvp_auto_fight = cfg.defend_party_pvp = True
            self._changed(s, "PvP on: fights back, defends the party, no PvP hang-up" if on
                          else "PvP off: hangs up when the party is attacked by a player")
        low = f"; still hangs up under {cfg.hangup_hp_pct}% HP" if cfg.hangup_low_hp and cfg.hangup_hp_pct else ""
        return ("PvP on — fighting back, defending the party" + low) if not cfg.hangup_on_pvp else \
            "PvP off — hangs up if anyone in the party is attacked by a player"

    def c_rest(self, s, a):
        mn, mx = self._pct_args(a)
        if mn is not None:
            self.cfg.rest_below_hp = mn
        if mx is not None:
            self.cfg.rest_until_hp = mx
        if mn is not None or mx is not None:
            self._changed(s, f"rest to {self.cfg.rest_below_hp}-{self.cfg.rest_until_hp}% HP")
        return f"rest below {self.cfg.rest_below_hp}% HP, up at {self.cfg.rest_until_hp}%"

    def c_medi(self, s, a):
        mn, mx = self._pct_args(a)
        if mn is not None:
            self.cfg.rest_below_ma = mn
        if mx is not None:
            self.cfg.rest_until_ma = mx
        if mn is not None or mx is not None:
            self._changed(s, f"meditate to {self.cfg.rest_below_ma}-{self.cfg.rest_until_ma}% MA")
        return f"meditate below {self.cfg.rest_below_ma}% MA, up at {self.cfg.rest_until_ma}%"

    def c_heal(self, s, a):
        mn, _mx = self._pct_args(a)
        if mn is not None:
            self.cfg.heal_pct = mn
            self._changed(s, f"heal to {mn}% HP")
        return f"heal below {self.cfg.heal_pct}% HP"

    def c_run(self, s, a):
        mn, _mx = self._pct_args(a)
        if mn is not None:
            self.cfg.run_pct = mn
            self._changed(s, f"run to {mn}% HP")
        return f"run below {self.cfg.run_pct}% HP" if self.cfg.run_pct else "never runs"

    def c_reset(self, s, a):
        self.s.state.reset_stats()
        return "session stats reset"

    def c_bless(self, s, a):
        """MudPilot extra: @bless lists rules; @bless <cast> <target> sets a target."""
        rules = self.cfg.buffs or []
        if not a:
            if not rules:
                return "no bless spells set"
            return "; ".join(f"{b.get('cast')} {b.get('op', '>=')} {int(b.get('value', 0)):+d} "
                             f"({self.s.bot.buff_status(b)[1]})" for b in rules)
        m = re.match(r"^(\S+)\s+([+-]?\d+)$", a)
        if not m:
            return "usage: @bless <spell> <target>, e.g. @bless ntap 150"
        name, val = m.group(1).lower(), int(m.group(2))
        for b in rules:
            if b.get("cast", "").lower() == name or (b.get("name") or "").lower() == name:
                b["value"] = val
                self.cfg.save()
                self.s.on_settings_changed()
                return f"{b.get('cast')} target now {val:+d}"
        return f"no bless spell '{name}'"

    # ------------------------------------------------------------ connection
    def c_divert(self, s, a):
        if not a:
            self.cfg.divert_to = ""
            return "No longer diverting telepaths"
        self.cfg.divert_to = a.split()[0]
        return f"Now diverting telepaths to: {self.cfg.divert_to}"

    def _hangup_allowed(self):
        cfg = self.cfg
        all_off = not any(getattr(cfg, f) for f in AUTO_FLAGS.values() if f)
        if all_off and not cfg.allow_hangup_all_off:
            return "Not allowed (all-off mode)"
        if not cfg.afk and not cfg.allow_hangup_not_afk:
            return "Not allowed (not AFK)"
        return None

    def c_hangup(self, s, a):
        why = self._hangup_allowed()
        if why:
            return why
        self.s.log(f"@hangup from {s}")
        self.s.disconnect()
        return None

    def c_relog(self, s, a):
        why = self._hangup_allowed()
        if why:
            return why
        self.s.log(f"@relog from {s}")
        self.s.bot.stop("Relogging")
        self.s.send_exit_cmd()
        self.s.telnet.close()
        self.s.show_down(f"Relogging (@relog from {s})")
        self._relog_at = time.time() + 8
        return None
