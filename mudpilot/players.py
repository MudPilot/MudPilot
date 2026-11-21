"""Player database, like MegaMUD's Game Data > Players.

Per board (data/boards/<board>/players.json). Learns each player's class, race and
what they were last seen wearing by looking at them — but only once per
settings.look_player_hours (default 24 h). Players in shadow form show nothing; we
still count the look, so MudPilot doesn't keep staring at them all day the way
MegaMUD does. Tick "Don't look" for anyone you never want looked at.
"""
from __future__ import annotations

import json
import os
import re
import time

from . import config

RELATIONSHIPS = ("Unknown", "Friend", "Enemy", "Neutral")
ITEM_RE = re.compile(r"^\s*(.+?)\s+\(([A-Za-z?][\w ?/-]{0,14})\)\s*$")
HEADER_RE = re.compile(r"^\s*\[\s*([A-Z][a-z]+)(?:\s+([A-Z][\w'-]*))?\s*\]\s*(?:\((.+?)\))?\s*$")   # [ Name Surname ](Gang)
NOT_HERE_RE = re.compile(r"(no one here by that name|you don't see|you do not see|isn't here|not here|"
                         r"there is no \w+ here|you cannot see)", re.I)
ENTER_RE = re.compile(r"^([A-Z][a-z]+) just entered the Realm", re.I)
LEFT_RE = re.compile(r"^([A-Z][a-z]+) just (?:left the Realm|disconnected|hung up)", re.I)
INVITE_RE = re.compile(r"^([A-Z][a-z]+) (?:has )?invit(?:es|ed) you to (?:join|be part of|a party|their|his|her|"
                       r"follow\s+(?:him|her|them))", re.I)
TALK_RE = re.compile(r"^([A-Z][a-z]+) (?:gossips|auctions|says|yells|telepaths|gangpaths|broadcasts):?", re.I)
BROADCAST_RE = re.compile(r"^Broadcast from ([A-Z][a-z]+)")
# who list:  "   FIEND Arlionnica            -  High Priestess of Prestige Worldwide"
WHO_HEAD_RE = re.compile(r"^\s*Current Adventurers\s*$")
WHO_RE = re.compile(r"^(.{8}) ([A-Z][\w'-]*(?: [\w'-]+)?)\s+([-x])  (\S.*?)\s*$")
ALIGNMENTS = {"", "good", "villain", "fiend", "criminal", "outlaw", "saint", "lawful", "seedy", "neutral", "evil"}
OF_TITLES = ("master of the way", "mistress of the way", "sword of justice", "whisper of death")
PLACES_KEEP = 10
PLACE_GAP = 10 * 60           # standing with someone doesn't count again until 10 min later
RETRY_SECS = 10 * 60          # a look that failed (they'd left) isn't retried sooner than this
LOOK_GAP = 4.0                # never more than one player look every few seconds
CAPTURE_SECS = 3.0


def players_file(board: str) -> str:
    return os.path.join(config.board_dir(board), "players.json")


class PlayerDB:
    def __init__(self, session):
        self.s = session
        self.data: dict = {}
        self._who = None
        self._capture = None      # {"key", "t", "items", "race", "class", "got"}
        self._last_look = 0.0
        self._queue: list = []
        self._dirty = False
        self._saved_at = 0.0
        self.on_change = lambda: None
        self.load()

    # ------------------------------------------------------------ storage
    @property
    def path(self):
        return players_file(self.s.settings.board)

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.data = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            self.data = {}
        days = int(getattr(self.s.settings, "delete_players_days", 0) or 0)
        if days > 0:
            cut = time.time() - days * 86400
            for k, p in list(self.data.items()):
                if p.get("relationship", "Unknown") == "Unknown" and not p.get("dont_look") and not p.get("alert_enter") \
                        and max(p.get("last_seen") or 0, p.get("last_online") or 0) and \
                        max(p.get("last_seen") or 0, p.get("last_online") or 0) < cut:
                    del self.data[k]

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        config._write_safely(self.path, json.dumps(self.data, indent=1))   # (flushed: a power cut can't empty it)
        self._dirty = False
        self._saved_at = time.time()

    def get(self, name: str, create=True) -> dict | None:
        key = name.strip().lower()
        if not key:
            return None
        p = self.data.get(key)
        if p is None and create:
            p = self.data[key] = {"name": name.strip().capitalize(), "surname": "", "relationship": "Unknown",
                                  "class": "", "race": "", "gang": "", "level": 0, "last_seen": 0, "last_online": 0,
                                  "last_looked": 0, "look_tried": 0, "wearing": [], "dont_look": False,
                                  "alert_enter": False, "notes": ""}
            self._dirty = True
        return p

    def remove(self, name):
        self.data.pop(name.lower(), None)
        self._dirty = True

    def relationship(self, name) -> str:
        p = self.data.get(name.lower())
        return p.get("relationship", "Unknown") if p else "Unknown"

    # ------------------------------------------------------------ learning
    def _seen(self, name, online_only=False):
        if not name or name.lower() == (self.s.settings.my_name or "").lower():
            return None
        p = self.get(name)
        now = time.time()
        if not online_only:
            if p.get("alert_enter") and now - p.get("last_seen", 0) > 300:
                self.s.on_alert(f"{p['name']} is here")
                self.s.notify.send("track", f"{p['name']} is here")
            p["last_seen"] = now
        p["last_online"] = now
        self._dirty = True
        return p

    def _place(self, p, state, v):
        """Last 10 different places we've seen them, with how often: Bank of Godfrey ×4."""
        r = self.s.world.room(state.room) if state.room else None
        place = (r.name if r else v.name or "").strip()
        if not place:
            return
        now = time.time()
        if p.get("_place") == place and now - p.get("_place_at", 0) < PLACE_GAP:
            p["_place_at"] = now
            return
        p["_place"], p["_place_at"] = place, now
        pl = [x for x in (p.get("places") or []) if x[0] != place]
        old = next((x for x in (p.get("places") or []) if x[0] == place), None)
        pl.insert(0, [place, (old[1] if old else 0) + 1, now,
                      f"{state.room[0]}/{state.room[1]}" if state.room else ""])
        p["places"] = pl[:PLACES_KEEP]

    def on_room(self, state):
        v = state.view
        if not v:
            return
        here_now = {w.split()[0].strip(".,").lower() for w in v.players if w.split()}
        before, self._here_before = getattr(self, "_here_before", (None, set())), (state.room, here_now)
        for who in v.players:
            nm = who.split()[0].strip(".,")
            new = nm.lower() not in self.data
            p = self._seen(nm)
            if p:
                self._place(p, state, v)
            # (once, as they come into the room or we come into theirs — Dan, 2026-10-30: Revolution kept inviting)
            arrived = before[0] != state.room or nm.lower() not in before[1]
            if p and p.get("invite_if_seen") and nm not in self.s.state.party and arrived and \
                    time.time() - p.get("_invited", 0) > 60 and nm.lower() != self.s.my_leader().lower():
                # (never my own leader: I join them — 0.8.212)
                p["_invited"] = time.time()
                self.s.send(f"invite {p['name']}", from_bot=True)     # session.send adds the @join
                self.s.log(f"Inviting {p['name']} (Game Data: invite if seen)")
            if p and new and self.s.settings.greet_players and (self.s.settings.greet_cmd or "").strip():
                self.s.send(self.s.settings.greet_cmd.replace("{name}", p["name"]), from_bot=True)
            if p:
                self._maybe_queue(p)

    def on_party(self, party: dict):
        for given, info in (party or {}).items():
            p = self._seen(given, online_only=True)
            if p and info.get("class"):
                p["class"] = info["class"]

    def _maybe_queue(self, p):
        cfg = self.s.settings
        if not cfg.learn_players or p.get("dont_look"):
            return
        now = time.time()
        if now - float(p.get("last_looked") or 0) < float(cfg.look_player_hours or 24) * 3600:
            return
        if now - float(p.get("look_tried") or 0) < RETRY_SECS:
            return
        if p["name"] not in self._queue:
            self._queue.append(p["name"])

    # ------------------------------------------------------------ who
    def _who_line(self, raw: str) -> bool:
        """True while we're inside a who list (the line was used or is part of it)."""
        if WHO_HEAD_RE.match(raw):
            self._who = {"t": time.time(), "rows": []}
            return True
        w = getattr(self, "_who", None)
        if not w:
            return False
        if time.time() - w["t"] > 5:
            self._who_finish()
            return False
        t = raw.strip()
        if not t or set(t) == {"="} or re.match(r"^\[[A-Z][a-z]+'s \w+ updated\]$", t):
            w["t"] = time.time()
            return True
        m = WHO_RE.match(raw.rstrip())
        if m and m.group(1).strip().lower() in ALIGNMENTS:
            w["t"] = time.time()
            title = re.sub(r"\s+[VS]\s*$", "", m.group(4))         # trailing status flag isn't part of the gang
            w["rows"].append((m.group(1).strip(), m.group(2), m.group(3), title))
            return True
        self._who_finish()
        return False

    @staticmethod
    def _gang_options(title: str) -> list:
        """Every 'X of <gang>' split of a who title, longest gang first. Titles that have "of" in
        them ("Master of the Way", "Sword of Justice") are never split inside the title."""
        low = title.lower()
        if low in OF_TITLES:
            return []
        inside = []
        for t in OF_TITLES:
            for m in re.finditer(rf"(?<![\w]){re.escape(t)}(?![\w])", low):
                inside.append((m.start(), m.end()))
        return [title[m.end():] for m in re.finditer(r" of ", title)
                if not any(a <= m.start() < b for a, b in inside)]

    def _who_finish(self):
        w, self._who = getattr(self, "_who", None), None
        if not w or not w["rows"]:
            return
        known = {(p.get("gang") or "").lower() for p in self.data.values() if p.get("gang")}
        count = {}
        for *_x, title in w["rows"]:
            for g in self._gang_options(title):
                count[g.lower()] = count.get(g.lower(), 0) + 1
        now, added = time.time(), 0
        for align, name, flag, title in w["rows"]:
            first, _, sur = name.partition(" ")
            if first.lower() == (self.s.settings.my_name or "").lower():
                # your own line: your alignment, for exit gates like "Alignment: Saint to Seedy" (Dan, 2026-11-01:
                # Buddy, Good, was told "no route" by one — MudPilot had never learned his alignment)
                mine = (align.capitalize() if align != "FIEND" else align) if align else "Neutral"   # (blank = Neutral)
                me = self.get(first)
                if me.get("alignment") != mine:
                    # kept on your own record, so the next start knows it before any Go to (Miserable PVE,
                    # 2026-11-06: forgotten on every restart — an alignment-gated Go to re-learned it each time)
                    me["alignment"] = mine
                    self._dirty = True
                if mine and getattr(self.s.state, "alignment", "") != mine:
                    self.s.state.alignment = mine
                    self.s.log(f"Your alignment: {mine} (from who)")
                    try:
                        self.s.route_char()
                        self.s.world.forget_routes()
                    except Exception:
                        pass
                    again = getattr(self.s.bot, "_goto_after_who", None)
                    self.s.bot._goto_after_who = None
                    if again and time.time() - again[1] < 60:
                        self.s.log("Trying that Go to again now that MudPilot knows your alignment")
                        self.s.bot.replan(again[0], then=again[2] if len(again) > 2 else None, retry=False)
                continue
            if first.lower() not in self.data:
                added += 1
            p = self.get(first)
            if sur:
                p["surname"] = sur
            opts = self._gang_options(title)
            # a gang name that shows up on other lines (or one we learned from a look) beats a title with "of" in it;
            # ties go to the longer name ("Order of the Bogan", not "the Bogan")
            gang = max(opts, key=lambda g: (g.lower() in known, count.get(g.lower(), 0), len(g)), default="")
            if gang and any(g.lower() in known for g in opts) and gang.lower() not in known:
                gang = next(g for g in opts if g.lower() in known)
            p["gang"] = gang
            p["title"] = title[:len(title) - len(gang) - 4].strip() if gang else title
            p["alignment"] = align.capitalize() if align and align != "FIEND" else align
            p["who_flag"] = flag              # x = gossip & auction off (can't see them)
            p["last_online"] = p["last_who"] = now
        self._dirty = True
        self.s.log(f"who: {len(w['rows'])} online, {added} new to Game Data → Players")
        self.on_change()

    def feed_line(self, text: str):
        if self._who_line(text):
            return
        t = text.strip()
        if not t:
            return
        for rx in (ENTER_RE, TALK_RE, BROADCAST_RE):
            m = rx.match(t)
            if m:
                p = self._seen(m.group(1), online_only=True)
                if p and rx is ENTER_RE and p.get("alert_enter"):
                    self.s.on_alert(f"{p['name']} entered the Realm")
                    self.s.notify.send("track", f"{p['name']} entered the Realm")
                if p and rx is ENTER_RE and p.get("auto_track"):
                    self._track_wanted = (p["name"], time.time())
                break
        m = INVITE_RE.match(t)
        if m:
            p = self.data.get(m.group(1).lower())
            rj = getattr(self.s, "_rejoin", None)
            if rj and rj["leader"].lower() == m.group(1).lower():
                self.s.send(f"join {m.group(1)}", from_bot=True)    # asked for it after a restart (session)
                self.s.log(f"{m.group(1)} invited me back — joining")
            elif p and p.get("join_if_invited") and self.s.remote.keep_my_loop(p["name"]):
                pass                    # 0.8.179: walking my own loop — invited them to follow me instead
            elif p and p.get("join_if_invited"):
                self.s.send(f"join {p['name']}", from_bot=True)
                self.s.log(f"Joining {p['name']}'s party (Game Data: join if invited)")
        cap = self._capture
        if not cap:
            return
        if time.time() - cap["t"] > CAPTURE_SECS:
            self._finish()
            return
        if NOT_HERE_RE.search(t) and not cap["got"]:
            p = self.get(cap["key"])
            p["last_looked"] = cap["prev"]      # didn't really see them; try again later
            self._capture = None
            return
        m = HEADER_RE.match(t)
        if m and m.group(1).lower() == cap["key"]:
            cap["got"] = True
            p = self.get(cap["key"])
            if m.group(2):
                p["surname"] = m.group(2)
            p["gang"] = (m.group(3) or "").strip()
            return
        m = ITEM_RE.match(t)
        if m and not t.lower().startswith(("also here", "obvious exits", "you notice")):
            cap["items"].append([m.group(1).strip(), m.group(2).strip()])
            cap["got"] = True
            return
        w = self.s.world
        if not cap["race"]:
            for nm in sorted((r.get("Name", "") for r in (w.races or {}).values()), key=len, reverse=True):
                if nm and re.search(rf"(?<![\w-]){re.escape(nm)}(?![\w-])", t, re.I):
                    cap["race"] = nm
                    cap["got"] = True
                    break
        if not cap["class"]:
            for nm in sorted((c.get("Name", "") for c in (w.classes or {}).values()), key=len, reverse=True):
                if nm and re.search(rf"(?<![\w-]){re.escape(nm)}(?![\w-])", t, re.I):
                    cap["class"] = nm
                    cap["got"] = True
                    break

    def _finish(self):
        cap, self._capture = self._capture, None
        if not cap:
            return
        p = self.get(cap["key"])
        if cap["items"]:
            p["wearing"] = cap["items"]          # shadow form shows nothing: keep what we knew
        if cap["race"]:
            p["race"] = cap["race"]
        if cap["class"]:
            p["class"] = cap["class"]
        self._dirty = True
        self.on_change()

    def look_now(self, name):
        p = self.get(name)
        now = time.time()
        if self._capture:
            self._finish()
        self._capture = {"key": p["name"].lower(), "t": now, "items": [], "race": "", "class": "",
                         "got": False, "prev": p.get("last_looked", 0)}
        p["last_looked"] = now
        p["look_tried"] = now
        self._last_look = now
        self._dirty = True
        self.s.send(f"look {p['name']}", from_bot=True)

    def tick(self):
        now = time.time()
        if self._who and now - self._who["t"] > 1.0:
            self._who_finish()
        if self._capture and now - self._capture["t"] > CAPTURE_SECS:
            self._finish()
        st = self.s.state
        if st.party and now - getattr(self, "_party_at", 0) > 30:
            self._party_at = now
            self.on_party(st.party)
        if self._queue and self.s.telnet.connected and not self._capture and now - self._last_look > LOOK_GAP \
                and not st.in_combat and not any(e[0] == "move" for e in st.pending):
            name = self._queue.pop(0)
            here = st.view and any(w.split()[0].strip(".,").lower() == name.lower() for w in st.view.players)
            if here:
                self.look_now(name)
        tw = getattr(self, "_track_wanted", None)
        if tw and now - tw[1] > 300:
            self._track_wanted = None
        elif tw and self.s.telnet.connected and not st.in_combat and not self.s.bot.walking \
                and not self.s.tracker.target and now - tw[1] > 5 and not st.resting \
                and not getattr(self.s.bot.x, "_following", None) and not self.s.remote.holding() \
                and not getattr(self.s.bot, "loop", None) and not self.s.bot.status.startswith(("Resting", "Meditating")) and \
                now - self.__dict__.setdefault("_tracked_at", {}).get(tw[0].lower(), 0) > 600:
            # pMUD's Auto-Track: a flagged player came on and you're idle — go find them
            self._track_wanted = None
            self._tracked_at[tw[0].lower()] = now
            self.s.log(f"Auto-track: {tw[0]} came on — tracking")
            self.s.tracker.start(tw[0])
        if self._dirty and now - self._saved_at > 20:
            try:
                self.save()
            except OSError:
                self._dirty = False

    def rows(self):
        return sorted(self.data.values(), key=lambda p: p["name"].lower())
