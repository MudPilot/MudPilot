"""Messages / Responses (MegaMUD's Game Data tab) — the PvP toolkit.

When a message is seen, send a response. Typical team setup: you broadcast "nuke" and
your AFK buddy's MudPilot casts its biggest area spell; "bs Bob" makes it backstab Bob;
"sneak", "hide", "hold", "track" … Each response says which channels it listens on
(broadcast / gangpath / say / telepath / any game line) and who may trigger it
(party + Friends by default — never just anyone unless you say so).

Patterns: the whole message, case-insensitive; * matches one word and becomes {1}, {2}…
  "nuke"        "bs *"        "attack *"
For game lines (channel "game") the pattern only has to appear in the line.

Responses: commands with ^M between them, plus
  #nuke          cast your strongest area attack spell (no target)
  #attack {1}    attack that player (PvP spells first) or monster
  #hold          stop walking and stay put until @ok
  #hangup        hang up now
Tokens: {who} = who sent it, {1} {2} = the * words, {room} = your map/room.

Track alerts: when your tracking turns up players who aren't friends or party, tell the
team on the channel you pick (and optionally hang up yourself).
"""
from __future__ import annotations

import re
import time

from .remote import CHAT_PATTERNS, HARD_BLOCK

CHANNELS = ("broadcast", "gangpath", "say", "telepath", "game")
DEFAULT_RESPONSES = [
    {"enabled": True, "match": "nuke", "channels": "broadcast,gangpath,telepath", "from": "team", "do": "#nuke"},
    {"enabled": True, "match": "bs *", "channels": "broadcast,gangpath,telepath", "from": "team", "do": "bs {1}"},
    {"enabled": True, "match": "attack *", "channels": "broadcast,gangpath,telepath", "from": "team", "do": "#attack {1}"},
    {"enabled": True, "match": "sneak", "channels": "broadcast,gangpath,telepath", "from": "team", "do": "sn"},
    {"enabled": True, "match": "hide", "channels": "broadcast,gangpath,telepath", "from": "team", "do": "hide"},
    {"enabled": True, "match": "hold", "channels": "broadcast,gangpath,telepath", "from": "team", "do": "#hold"},
    {"enabled": True, "match": "track", "channels": "broadcast,gangpath,telepath", "from": "team", "do": "track"},
]
# Paradigm/MajorMUD tracking: "Revolution went southeast from here."
TRACK_WENT_RE = re.compile(r"^([A-Z][a-z]+) went (north(?:east|west)?|south(?:east|west)?|east|west|up|down|"
                           r"upwards|downwards|\w+) from here\.?$")
TRACK_DEFAULT = (r"tracks? (?:of|left by|belonging to) ([A-Z][a-z]+)|([A-Z][a-z]+)'s tracks|"
                 r"([A-Z][a-z]+) (?:passed|walked|came|headed) (?:through|by|this way|here)")
SAFE_WORD = re.compile(r"^[A-Za-z0-9'-]{1,24}$")


def compile_pattern(pat: str, game=False):
    words = pat.strip().split()
    if not words:
        return None
    parts = [r"(\S+)" if w == "*" else re.escape(w) for w in words]
    body = r"\s+".join(parts)
    return re.compile(body if game else rf"^\s*{body}\s*[.!]?\s*$", re.I)


class Responses:
    def __init__(self, session):
        self.s = session
        self._recent: dict = {}         # (index, sender) -> time (flood guard)
        self._tracked_at: dict = {}     # name -> time we last alerted
        self._pending: dict = {}        # name -> [directions] waiting to be announced
        self._pending_at = 0.0

    @property
    def cfg(self):
        return self.s.settings

    def rules(self):
        if self.cfg.responses is None:
            self.cfg.responses = [dict(r) for r in DEFAULT_RESPONSES]
        return self.cfg.responses

    def team(self) -> set:
        names = {n.lower() for n in self.s.state.party}
        names |= {k for k, p in self.s.players.data.items() if p.get("relationship") == "Friend"}
        names |= {n.lower() for n in (self.cfg.remote_players or {})}
        names |= {n.lower() for n in (self.cfg.pvp_friends or [])}
        return names

    def _sender_ok(self, rule, sender) -> bool:
        if sender is None:
            return True                           # a game line, not a person
        frm = (rule.get("from") or "team").strip().lower()
        if frm == "anyone":
            return True
        if frm == "team":
            return sender.lower() in self.team()
        return sender.lower() in {x.strip().lower() for x in frm.split(",") if x.strip()}

    # ------------------------------------------------------------ inbound
    def feed_line(self, text: str):
        t = text.strip()
        if not t or not self.cfg.responses_on:
            return
        self._track(t)
        msg, channel, sender = t, "game", None
        for ch, rx in CHAT_PATTERNS:
            m = rx.match(t)
            if m:
                channel, sender, msg = ch, m.group(1), m.group(2).strip()
                break
        if sender and self.cfg.my_name and sender.lower() == self.cfg.my_name.lower():
            return
        if HARD_BLOCK.search(msg):
            return
        for i, r in enumerate(self.rules()):
            if not r.get("enabled", True):
                continue
            chans = {c.strip().lower() for c in (r.get("channels") or "any").split(",")}
            if "any" not in chans and channel not in chans:
                continue
            rx = compile_pattern(r.get("match", ""), game=(channel == "game"))
            if not rx:
                continue
            m = rx.search(msg) if channel == "game" else rx.match(msg)
            if not m or not self._sender_ok(r, sender):
                continue
            words = [g for g in m.groups()]
            if any(not SAFE_WORD.match(w or "") for w in words):
                continue                          # never pass odd text through to the game
            key = (i, sender)
            if time.time() - self._recent.get(key, 0) < 1.5:
                continue
            self._recent[key] = time.time()
            self.run(r.get("do", ""), sender, words)
            return

    def run(self, do: str, sender, words):
        st = self.s.state
        room = f"{st.room[0]}/{st.room[1]}" if st.room else "?"
        text = do.replace("{who}", sender or "").replace("{room}", room)
        for n, w in enumerate(words, start=1):
            text = text.replace("{%d}" % n, w)
        self.s.log(f"Response{f' to {sender}' if sender else ''}: {text}")
        for part in text.replace("^m", "^M").split("^M"):
            part = part.strip()
            if not part:
                continue
            low = part.lower()
            if low == "#nuke":
                self.nuke()
            elif low.startswith("#attack"):
                name = part.split(None, 1)[1].strip() if len(part.split()) > 1 else ""
                if name:
                    self.attack(name)
            elif low == "#hold":
                self.s.bot.stop("Holding (response)")
                if sender:
                    self.s.remote.holds[sender] = time.time()
            elif low == "#hangup":
                self.s.safety.hangup(f"response to {sender or 'a message'}")
            else:
                self.s.send(part, from_bot=True)

    def nuke(self):
        """Strongest area attack spell you can cast right now (no target)."""
        from .spells import spell_kind, calc
        st, cfg, book = self.s.state, self.cfg, self.s.spellbook
        why = self.s.bot.aoe_blocked()
        if why:
            self.s.log(f"Nuke: not casting an area spell — {why}")   # the AoE safety holds for #nuke too
            return
        lvl = cfg.char_level or st.level
        best = None
        for sp in self.s.spell_candidates():
            if spell_kind(sp) in (None, "single") or sp["Number"] in book.refused:
                continue
            if st.max_ma and st.ma < int(sp.get("ManaCost") or 0):
                continue
            dmg = calc(sp, lvl, None, self.s.bot.spellcasting(), cfg.spell_dmg_bonus).round_dmg
            if best is None or dmg > best[0]:
                best = (dmg, sp)
        short = (best[1].get("Short") if best else "") or cfg.multi_spell
        if short:
            self.s.send(cfg.cast_cmd.format(short=short, target="").strip(), from_bot=True)
        else:
            self.s.log("Nuke: no area spell known")

    def attack(self, name):
        st = self.s.state
        nm = name.strip().capitalize()
        players = {p.split()[0].strip(".,").lower() for p in (st.view.players if st.view else [])}
        if nm.lower() in players or (self.s.safety.is_player(nm) and nm.lower() not in
                                     {m[0].lower() for m in (st.view.monsters if st.view else [])}):
            self.s.bot.x.start_pvp(nm, "told to")
        else:
            self.s.send(self.cfg.attack_cmd.format(target=name), from_bot=True)

    # ------------------------------------------------------------ tracking
    def _track(self, t):
        """Collect tracking lines for a moment (one 'track' prints a line per trail), then alert once."""
        cfg = self.cfg
        if not cfg.track_alert:
            return
        found = []                                  # (name, direction or None)
        m = TRACK_WENT_RE.match(t.strip())
        if m:
            found.append((m.group(1), m.group(2)))
        else:
            try:
                rx = re.compile(cfg.track_pattern or TRACK_DEFAULT)
            except re.error:
                rx = re.compile(TRACK_DEFAULT)
            for mm in rx.finditer(t):
                nm = next((g for g in mm.groups() if g), None) if mm.groups() else None
                if nm:
                    found.append((nm, None))
        if not found:
            return
        team = self.team() | {(cfg.my_name or "").lower()}
        now = time.time()
        for nm, d in found:
            if nm.lower() in team or not self.s.safety.is_player(nm):
                continue
            if now - self._tracked_at.get(nm.lower(), 0) < 60 and nm not in self._pending:
                continue
            dirs = self._pending.setdefault(nm, [])
            if d and d not in dirs:
                dirs.append(d)
            self._pending_at = self._pending_at or now

    def tick(self):
        if self._pending and time.time() - self._pending_at >= 1.5:
            pend, self._pending, self._pending_at = self._pending, {}, 0.0
            self._alert(pend)

    def _alert(self, pend: dict):
        cfg, st = self.cfg, self.s.state
        now = time.time()
        for n in pend:
            self._tracked_at[n.lower()] = now
            self.s.players._seen(n, online_only=True)
        names = ", ".join(f"{n} ({'/'.join(d)})" if d else n for n, d in pend.items())
        room = f"{st.room[0]}/{st.room[1]}" if st.room else "?"
        rname = self.s.world.room(st.room).name if st.room and self.s.world.room(st.room) else ""
        msg = (cfg.track_alert_msg or "Tracks: {names} near {room}").replace("{names}", names) \
            .replace("{room}", room).replace("{roomname}", rname)
        via = (cfg.track_alert_channel or "broadcast").lower()
        cmd = {"broadcast": f"br {msg}", "gangpath": f"bg {msg}", "say": f"say {msg}"}.get(via)
        if via == "party":
            for p in st.party:
                if p.lower() != (cfg.my_name or "").lower():
                    self.s.send(f"/{p} {msg}", from_bot=True)
        elif cmd:
            self.s.send(cmd, from_bot=True)
        self.s.log(f"Tracked {names} — told the team ({via})")
        self.s.on_alert(f"Tracks: {names}")
        self.s.notify.send("track", f"Tracks: {names} near {rname or room}")
        if cfg.track_hangup:
            self.s.safety.hangup(f"tracked {', '.join(pend)}")
