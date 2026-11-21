"""Chat capture: pulls conversation out of the game text for the Chat tab, and logs
it to data/chat/YYYY-MM-DD.log (local only)."""
from __future__ import annotations

import os
import re
import time

from . import config

CHAT_DIR = os.path.join(config.DATA_DIR, "chat")

PATTERNS = [
    ("gossip", re.compile(r"^(\w+) gossips: (.+)$")),
    ("auction", re.compile(r"^(\w+) auctions: (.+)$")),
    ("telepath", re.compile(r"^(\w+) telepaths: (.+)$")),
    ("telepath-out", re.compile(r"^--- Telepath sent to (\w+) ---$", re.I)),
    ("gangpath", re.compile(r"^(\w+) gangpaths: (.+)$")),
    ("broadcast", re.compile(r"^Broadcast from (\w+) \"(.+)\"$")),
    ("say", re.compile(r"^(\w+) says(?: \(to ([^)]+)\))? \"(.+)\"$")),
    ("say-out", re.compile(r"^You say \"(.+)\"$")),
    ("realm", re.compile(r"^(\w+) just (entered the Realm|left the Realm|disconnected|hung up|logged off)[.!]*$", re.I)),
    ("yell", re.compile(r"^(?:(\w+) yells|From (\w+) \(Yelling\):) \"(.+)\"$")),
]

# socials ("You spit.", "Revolution grins at you.") — 64 MajorMUD actions, each with how the game words it
# for you, someone else, and at a target (from pMUD's Chatter)
def _load_actions():
    import json
    out = []
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bundled", "actions.json"),
                  encoding="utf-8") as f:
            rows = json.load(f)
    except (OSError, ValueError):
        return out
    for row in rows:
        for field in ("no_target", "other_no_target", "target_other", "you_as_target", "target_to_target"):
            tmpl = (row.get(field) or "").strip()
            if not tmpl:
                continue
            rx, pos = "", 0
            for m in re.finditer(r"\{(source|target)\}", tmpl):
                rx += re.escape(tmpl[pos:m.start()]) + (r"(?P<%s>[A-Z][A-Za-z'-]+)" % m.group(1))
                pos = m.end()
            rx += re.escape(tmpl[pos:])
            out.append((row.get("action") or "", re.compile("^" + rx + "$")))
    return out


ACTIONS = _load_actions()
# what to type to speak on each channel
SEND = {
    "Say": "say {msg}",
    "Gossip": "gos {msg}",
    "Telepath": "/{to} {msg}",
    "Gangpath": "bg {msg}",
    "Broadcast": "br {msg}",
    "Auction": "auc {msg}",
}


class ChatLog:
    def __init__(self, settings=None):
        self.settings = settings
        self.entries: list = []      # (time, channel, who, text)
        self.listeners: list = []
        self._pending_tp: list = []  # our outgoing telepath text, matched to the server's ack

    LINE_RE = re.compile(r"^(\d\d):(\d\d):(\d\d) \[([\w-]+)\] (.*?): (.*)$")

    @staticmethod
    def _bot_text(msg) -> bool:
        m = (msg or "").strip().strip('"').lstrip(".")
        return m.startswith(("@", "{")) or bool(re.match(r"^\(to you\)\s*[\"']?\{", m))

    def load_recent(self, hours: float = 12, max_lines: int = 300, folder: str | None = None) -> int:
        """0.8.198 (Dan, 2026-11-15): after an update the chat box started empty, halfway through a gossip
        conversation. Put the last few hours from data/chat back in, with a 'restarted' line under them.
        Only the lines go back in: they aren't written to the log a second time."""
        folder = folder or CHAT_DIR
        now = time.time()
        rows = []
        for back in (1, 0):                                     # yesterday's file, then today's
            day = time.localtime(now - back * 86400)
            path = os.path.join(folder, time.strftime("%Y-%m-%d", day) + ".log")
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()[-20000:]
            except OSError:
                continue
            for ln in lines:
                m = self.LINE_RE.match(ln.rstrip("\r\n"))
                if not m or self._bot_text(m.group(6)):
                    continue                            # (the party's @ok/@held chatter: not what you missed)
                t = time.mktime((day.tm_year, day.tm_mon, day.tm_mday, int(m.group(1)), int(m.group(2)),
                                 int(m.group(3)), 0, 0, -1))
                if now - hours * 3600 <= t <= now + 60:
                    rows.append((t, m.group(4), m.group(5), m.group(6)))
        rows = rows[-max_lines:]
        if rows:
            self.entries[:0] = rows + [(rows[-1][0], "restart", "", "— MudPilot restarted: the lines above are "
                                        "from before —")]
        return len(rows)

    room_name = staticmethod(lambda key: "")      # set by the session (room names from the map data)

    def note_sent(self, cmd: str, from_bot: bool = False):
        ms = re.match(r"^\s*(?:\.|'|say\s+|gs\s+|bg\s+|gangpath\s+)\s*(@\S.*)$", cmd or "", re.I)
        if ms and not from_bot:
            # '.@level' — asking the room / party (Dan, 2026-11-01: those answers scrolled away too): anyone may answer
            self._asked = [a for a in getattr(self, "_asked", []) if time.time() - a[1] < 60] + [("*", time.time())]
        m = re.match(r"^\s*(?:/|tele(?:path)?\s+)(\w+)\s+(.+)$", cmd, re.I)
        if m and not from_bot and m.group(2).lstrip().startswith("@"):
            # you typed '/revo @where' yourself: show it, and their {answer}, even with bot traffic hidden
            self._asked = [a for a in getattr(self, "_asked", []) if time.time() - a[1] < 60] + \
                [(m.group(1).lower(), time.time())]
            self._pending_tp.append((m.group(1), m.group(2), time.time()))
            self._pending_tp = self._pending_tp[-10:]
        elif m and not m.group(2).lstrip().startswith(("@", "{")):
            self._pending_tp.append((m.group(1), m.group(2), time.time()))
            self._pending_tp = self._pending_tp[-10:]

    def you_asked(self, e) -> bool:
        """A bot answer (or your @command) that you typed for — show it whatever the filter says."""
        return e in getattr(self, "asked_entries", ())

    LOCATION_RE = re.compile(r"^Location:\s+(\d+)\s*,\s*(\d+)\s*$")

    def feed(self, text: str):
        t = text.strip()
        m = self.LOCATION_RE.match(t)           # 'pro' on Paradigm: show the room number where it won't scroll away
        if m:
            key = (int(m.group(1)), int(m.group(2)))
            name = ""
            try:
                r = self.room_name(key)
                name = f" — {r}" if r else ""
            except Exception:
                pass
            self._add("location", "", f"map {key[0]} room {key[1]}{name}")
            return True
        if t and len(t) < 160 and not re.search(r"\bfor \d+ damage\b", t):
            for act, rx in ACTIONS:
                m = rx.match(t)
                if m:
                    gd = m.groupdict()
                    self._add("action", gd.get("source") or "You", t)
                    return True
        for ch, rx in PATTERNS:
            m = rx.match(t)
            if not m:
                continue
            g = m.groups()
            if ch == "telepath-out":
                to = g[0]
                # MajorMUD takes short names ("/phrix" reaches Phrixas), so match on the start of the name;
                # failing that, the last telepath you sent in the past few seconds
                hit = next((p for p in reversed(self._pending_tp) if to.lower().startswith(p[0].lower())), None)
                if hit is None and self._pending_tp and time.time() - self._pending_tp[-1][2] < 8:
                    hit = self._pending_tp[-1]
                if not hit:
                    return True              # the bot's own @-telepath (party sync, @join…): nothing to show
                self._pending_tp.remove(hit)
                self._add("telepath", f"You → {to}", hit[1])
            elif ch == "say":
                self._add("say", g[0] + (f" (to {g[1]})" if g[1] else ""), g[2])
            elif ch == "say-out":
                self._add("say", "You", g[0])
            elif ch == "realm":
                self._add("realm", g[0], g[1])
            elif ch == "yell":
                self._add("yell", g[0] or g[1], g[2])
            else:
                self._add(ch, g[0], g[1])
            return True
        return False

    def _add(self, ch, who, msg):
        e = (time.time(), ch, who, msg)
        asked = getattr(self, "_asked", [])
        body = (msg or "").lstrip().strip('"').lstrip(".")
        if ch in ("telepath", "say", "gossip", "gangpath", "broadcast") and asked and body.startswith(("{", "@")):
            nm = (who or "").lower().replace("you → ", "").split(" (")[0]
            fresh = [a for a in asked if time.time() - a[1] < 60]
            hit = next((a for a in fresh if a[0] != "*" and (nm.startswith(a[0]) or a[0].startswith(nm))), None) or \
                next((a for a in fresh if a[0] == "*"), None)       # (asked them by name first, then the room)
            if hit and hit[0] == "*":
                mine = who == "You" and body.startswith("@")                  # your question itself
                answer = body.startswith("{") and not body.lower().startswith("{mpsync") and "(to you)" in (who or "")
                if not (mine or answer):
                    hit = None                        # a room question: only the {answers} said to you
            if hit and (ch == "telepath" or hit[0] == "*"):
                self.asked_entries = (list(getattr(self, "asked_entries", [])) + [e])[-200:]
                if body.startswith("{") and hit[0] != "*":
                    asked.remove(hit)                 # one answer per question (a room question: everyone answers)
        self.entries.append(e)
        keep = int(getattr(self.settings, "chat_keep_lines", 0) or 2000)
        self.entries = self.entries[-max(50, min(keep, 5000)):]
        if self.settings is not None and not getattr(self.settings, "log_chat", True):
            pass
        else:
            self._write(ch, who, msg)
        for cb in list(self.listeners):
            try:
                cb(e)
            except Exception:
                self.listeners.remove(cb)   # a closed window

    def _write(self, ch, who, msg):
        try:
            os.makedirs(CHAT_DIR, exist_ok=True)
            day = time.strftime("%Y-%m-%d")
            with open(os.path.join(CHAT_DIR, day + ".log"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} [{ch}] {who}: {msg}\n")
        except OSError:
            pass
