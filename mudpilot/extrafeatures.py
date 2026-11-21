"""Smaller pMUD-inspired extras: sounds, scheduled actions, tracking with `trac`, the XP leaderboard,
the Magic 8-Ball, and quest lists.

* Sounds (Settings → Phone alerts → Sounds): a sound for hang-ups, deaths, PvP, drops, boss timers,
  telepaths, level-ups and low HP. A .wav file per event, or the Windows ding.
* Scheduled actions (Window → Scheduled actions): log on / log off / relog / go to a room / start a
  loop / send a command, at a time each day or every N minutes. Skipped (and logged) when they make
  no sense right then — e.g. "log on" while already in the game.
* Tracking (Window → Track a player): `trac <name>`, follow "<Name> went <dir> from here." one step
  at a time, re-track after each step; stops when they're in the room, the trail is lost twice, or
  after the step limit. Hostile monsters in the way: the fight comes first, then the tracking.
* XP leaderboard (Window → XP leaderboard): sends `top 200` every hour when nothing's happening, keeps
  48 h of samples and shows everyone's exp/hr.
* Magic 8-Ball (off by default): someone gossips "(8) will I get the drop?" and MudPilot answers on
  gossip; "(8) mob <name>" / "(8) item <name>" look things up in MME. Cooldowns so it never spams.
* Quests (Window → Quests): reads `? questlist`, `? questlist2`, `? questlist3` and `? questflags`
  pages, keeps them, and shows them with the ones for your level and class picked out.
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time

from . import config
from .worlddb import norm_dir, DIR_WORDS


# ---------------------------------------------------------------- sounds
SOUND_EVENTS = {"hangup": "Hung up", "death": "Died", "pvp": "PvP", "drop": "Line dropped",
                "track": "Boss timer / boss hunt", "telepath": "Telepath to me", "level": "Level up",
                "lowhp": "HP under the heal line", "stop": "Stopped"}


class Sounds:
    def __init__(self, session):
        self.s = session
        self._last = {}

    def play(self, event):
        cfg = self.s.settings
        if not cfg.sounds_on or event not in (cfg.sound_events or {}):
            return
        now = time.time()
        if now - self._last.get(event, 0) < 3:
            return
        self._last[event] = now
        path = (cfg.sound_events or {}).get(event) or ""
        try:
            if sys.platform.startswith("win"):
                import winsound
                if path and os.path.exists(path):
                    winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                else:
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            else:
                # Linux: the first sound player there is (PulseAudio / PipeWire / ALSA), else the window's bell
                import shutil
                import subprocess
                player = next((shutil.which(x) for x in ("paplay", "pw-play", "aplay") if shutil.which(x)), None)
                if path and os.path.exists(path) and player:
                    subprocess.Popen([player, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    self.s.on_bell()
        except Exception:
            pass

    def feed_line(self, text):
        t = text.strip()
        me = (self.s.settings.my_name or "").lower()
        if re.match(r"^\w+ telepaths: (?!@|\{)", t) and not t.lower().startswith(me):
            self.play("telepath")
        elif re.search(r"you are now level|you have gained a level", t, re.I):
            self.play("level")
        st, cfg = self.s.state, self.s.settings
        if st.max_hp and st.hp is not None and 0 < st.hp_pct() < cfg.heal_pct:
            self.play("lowhp")


# ---------------------------------------------------------------- scheduler
ACTIONS = ("log on", "log off", "relog", "go to", "loop", "command")


class Scheduler:
    def __init__(self, session):
        self.s = session
        self._fired: dict = {}     # index → last fire (day key or time)

    def tick(self):
        cfg = self.s.settings
        items = cfg.schedules or []
        if not items:
            return
        now = time.time()
        lt = time.localtime(now)
        for i, it in enumerate(items):
            if not it.get("on", True):
                continue
            key = None
            if it.get("at"):
                m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", it["at"])
                if not m or (lt.tm_hour, lt.tm_min) != (int(m.group(1)), int(m.group(2))):
                    continue
                key = time.strftime("%Y%m%d%H%M", lt)
                if self._fired.get(i) == key:
                    continue
            elif it.get("every"):
                last = self._fired.get(i, 0) or now
                if i not in self._fired:
                    self._fired[i] = now
                    continue
                if now - last < float(it["every"]) * 60:
                    continue
                key = now
            else:
                continue
            self._fired[i] = key
            self.run(it)

    def run(self, it):
        s, b = self.s, self.s.bot
        act, arg = it.get("action", ""), (it.get("arg") or "").strip()
        why = None
        if act == "log on":
            if s.telnet.connected:
                why = "already connected"
            else:
                s._want_connected = True
                s.connect()
        elif act == "log off":
            if not s.telnet.connected:
                why = "not connected"
            else:
                b.stop("Scheduled log off")
                s.disconnect()
        elif act == "relog":
            if not s.telnet.connected:
                why = "not connected"
            else:
                s.relog() if hasattr(s, "relog") else s.disconnect()
        elif act in ("go to", "loop", "command") and not (s.telnet.connected and s._entered):
            why = "not in the game"
        elif act == "go to":
            m = re.match(r"^(\d+)\s*/\s*(\d+)$", arg)
            if not m or not b.goto((int(m.group(1)), int(m.group(2)))):
                why = "no route"
        elif act == "loop":
            mp = next((p for p in s.paths if p.is_loop and arg.lower() in p.title.lower()), None)
            if not mp or not b.start_path(mp, loop=True):
                why = "loop not found"
        elif act == "command":
            if arg:
                b.send_macro(arg)
        s.log(f"Scheduled: {act} {arg}".strip() + (f" — skipped ({why})" if why else ""))


# ---------------------------------------------------------------- tracking
TRACK_RE = re.compile(r"^\s*(?P<name>[A-Z][A-Za-z'-]+)\s+went\s+(?P<dir>north|south|east|west|northeast|northwest|"
                      r"southeast|southwest|up|down|[nsewud]|ne|nw|se|sw)\s+from\s+here\.\s*$", re.I)
TRACK_FAIL_RE = re.compile(r"^\s*Your tracking skills fail you this time\.|^\s*You (?:can't|cannot) find any tracks|"
                           r"^\s*You don't see any tracks", re.I)


class Tracker:
    def __init__(self, session):
        self.s = session
        self.target = None
        self.steps = 0
        self.fails = 0
        self._sent = 0.0
        self._dir = None

    def start(self, name):
        self.target, self.steps, self.fails, self._dir = name.strip().capitalize(), 0, 0, None
        self.s.log(f"Tracking {self.target}")
        self._ask()

    def stop(self, why="stopped"):
        if self.target:
            self.s.log(f"Tracking {self.target}: {why}")
            self.s.notify.send("track", f"Tracking {self.target}: {why}")
        self.target = None

    def _ask(self):
        self._sent = time.time()
        self.s.send(f"{self.s.settings.track_cmd or 'trac'} {self.target}", from_bot=True)

    def feed_line(self, text):
        if not self.target:
            return
        t = text.strip()
        m = TRACK_RE.match(t)
        if m and m.group("name").lower() == self.target.lower():
            self._dir = norm_dir(m.group("dir"))
            self.fails = 0
        elif TRACK_FAIL_RE.match(t):
            self.fails += 1
            if self.fails >= int(self.s.settings.track_max_fails or 3):
                self.stop("lost the trail")
            else:
                self._sent = 0                  # try again next tick

    def tick(self):
        if not self.target:
            return
        s, st = self.s, self.s.state
        if st.in_combat or st.pending:
            return
        v = st.view
        if v and any(p.split()[0].strip(".,*").lower() == self.target.lower() for p in (v.players or []) if p.split()):
            return self.stop("found them here")
        if self._dir:
            d, self._dir = self._dir, None
            self.steps += 1
            if self.steps > int(s.settings.track_max_steps or 40):
                return self.stop("too many steps")
            s.send(d.lower(), from_bot=True)
            self._sent = time.time() + 1.5      # ask again once we've arrived
            return
        if time.time() - self._sent > 4:
            self._ask()


# ---------------------------------------------------------------- XP leaderboard
TOP_HEAD_RE = re.compile(r"^\s*Top Heroes of the Realm By Experience\s*$", re.I)
TOP_ROW_RE = re.compile(r"^\s*(\d+)\.\s+(.+?)\s{2,}(\S.*?)\s+([\d,]{3,})\s*$")


class Leaderboard:
    def __init__(self, session):
        self.s = session
        self.samples: dict = {}      # name → [[t, exp], …]
        self._reading = False
        self._last_ask = 0.0
        self.load()

    @property
    def file(self):
        return os.path.join(config.DATA_DIR, "leaderboard.json")

    def load(self):
        try:
            with open(self.file, encoding="utf-8") as f:
                self.samples = json.load(f)
        except (OSError, ValueError):
            self.samples = {}

    def save(self):
        os.makedirs(config.DATA_DIR, exist_ok=True)
        cut = time.time() - 48 * 3600
        self.samples = {n: [x for x in v if x[0] >= cut] for n, v in self.samples.items()}
        self.samples = {n: v for n, v in self.samples.items() if v}
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(self.samples, f)

    def feed_line(self, text):
        t = text.rstrip()
        if TOP_HEAD_RE.match(t):
            self._reading, self._rows = True, 0
            return
        if not self._reading:
            return
        if t.strip().startswith("[HP=") or (not t.strip() and self._rows):
            self._reading = False
            self.save()
            return
        m = TOP_ROW_RE.match(t)
        if m:
            name = m.group(2).split()[0]
            exp = int(m.group(4).replace(",", ""))
            self.samples.setdefault(name, []).append([round(time.time()), exp])
            self._rows += 1

    def tick(self):
        s, cfg = self.s, self.s.settings
        if not cfg.leaderboard_on or not s.telnet.connected or not s._entered:
            return
        st = s.state
        if st.in_combat or s.bot.walking and st.pending:
            return
        if time.time() - self._last_ask >= float(cfg.leaderboard_mins or 60) * 60:
            self._last_ask = time.time()
            s.send("top 200", from_bot=True)

    def rates(self) -> list:
        """[(name, exp now, exp/hr over the samples)] fastest first."""
        out = []
        for n, v in self.samples.items():
            if len(v) < 2:
                out.append((n, v[-1][1], 0.0))
                continue
            (t0, e0), (t1, e1) = v[0], v[-1]
            hrs = max((t1 - t0) / 3600, 1e-6)
            out.append((n, e1, (e1 - e0) / hrs))
        out.sort(key=lambda x: -x[2])
        return out


# ---------------------------------------------------------------- Magic 8-Ball
EIGHT_RE = re.compile(r"^(\w+) gossips: \(8\)\s*(.*)$")
ANSWERS = {
    "yes": ["It is certain.", "Without a doubt.", "Yes — definitely.", "You may rely on it.", "Signs point to yes."],
    "maybe": ["Reply hazy, try again.", "Ask again later.", "Better not tell you now.", "Cannot predict now."],
    "no": ["Don't count on it.", "My reply is no.", "Outlook not so good.", "Very doubtful."],
}


class EightBall:
    def __init__(self, session):
        self.s = session
        self._last = 0.0
        self._by: dict = {}

    def feed_line(self, text):
        cfg = self.s.settings
        if not cfg.eightball_on:
            return
        m = EIGHT_RE.match(text.strip())
        if not m:
            return
        who, q = m.group(1), m.group(2).strip()
        now = time.time()
        if now - self._last < 4 or now - self._by.get(who.lower(), 0) < 12:
            return
        self._last = self._by[who.lower()] = now
        ans = self.answer(q)
        self.s.send(f"gos Mystic(8) says: {ans}"[:127], from_bot=True)

    def answer(self, q):
        w = self.s.world
        mm = re.match(r"^(?:mob|monster)\s+(.+)$", q, re.I)
        if mm:
            mon = w.identify_monster(mm.group(1).strip())
            if not mon:
                return f"I know no {mm.group(1).strip()}."
            return (f"{mon['name']}: {int(mon.get('exp') or 0):,} exp, {mon.get('hp', '?')} HP, AC/DR "
                    f"{mon.get('ac', '?')}/{mon.get('dr', '?')}" + (f", regen {mon['regen_h']}h" if mon.get('regen_h') else ""))
        mi = re.match(r"^item\s+(.+)$", q, re.I)
        if mi:
            n = mi.group(1).strip().lower()
            for src in (getattr(w, "gear", None) or {}, getattr(w, "items", None) or {}):
                for g in src.values():
                    if (g or {}).get("name", "").lower() == n:
                        from . import gearcalc as G
                        where = "; ".join(t for t, _r in G.sources(w, g, 2))
                        return f"{g['name']}: {where}"
            return f"I know no {mi.group(1).strip()}."
        kind = random.choice(["yes", "yes", "maybe", "no"])
        return random.choice(ANSWERS[kind])


# ---------------------------------------------------------------- quest lists
QUEST_CMDS = ("? questlist", "? questlist2", "? questlist3", "? questflags", "? questflags2", "? questflags3")


class Quests:
    """Keeps the board's quest pages (they're plain help text) and shows the ones that fit you."""
    def __init__(self, session):
        self.s = session
        self.pages: dict = {}
        self._cur = None
        self._buf = []
        self.load()

    @property
    def file(self):
        return os.path.join(config.board_dir(self.s.settings.board), "quests.json")

    def load(self):
        try:
            with open(self.file, encoding="utf-8") as f:
                self.pages = json.load(f)
        except (OSError, ValueError):
            self.pages = {}

    def save(self):
        os.makedirs(os.path.dirname(self.file), exist_ok=True)
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(self.pages, f, indent=1)

    def note_sent(self, cmd):
        c = (cmd or "").strip().lower()
        if c in QUEST_CMDS:
            self._finish()
            self._cur, self._buf = c, []

    def feed_line(self, text):
        if not self._cur:
            return
        t = text.rstrip()
        if t.strip().startswith("[HP="):
            if self._buf:
                self._finish()
            return
        self._buf.append(t)
        self._line_at = time.time()
        if len(self._buf) > 400:
            self._finish()

    def _finish(self):
        if self._cur and any(x.strip() for x in self._buf):
            self.pages[self._cur] = {"t": time.time(), "lines": self._buf}
            self.save()
            self.s.log(f"Quests: read {self._cur} ({len(self._buf)} lines)")
        self._cur, self._buf = None, []

    def fetch_all(self):
        self._queue = list(QUEST_CMDS)

    def tick(self):
        if self._cur and self._buf and time.time() - getattr(self, "_line_at", 0) > 1.5:
            self._finish()                       # the page has stopped coming
        q = getattr(self, "_queue", None)
        if not q or self._cur or not self.s.telnet.connected:
            return
        self.s.send(q.pop(0), from_bot=True)

    def for_me(self, line: str) -> bool:
        """Picked out: mentions your class, or a level band you're in."""
        st, cfg = self.s.state, self.s.settings
        cls = (st.char_class or cfg.char_class or "").lower()
        if cls and cls in line.lower():
            return True
        return False
