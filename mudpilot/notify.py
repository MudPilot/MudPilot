"""Phone alerts through ntfy (https://ntfy.sh, or your own ntfy server).

Install the ntfy app, subscribe to a topic name only you know (your "phrase"), and put the
same topic in Settings → Phone alerts. MudPilot posts a short message when (each can be ticked):
  hang-up · attacked by a player · died · tracks of a stranger · stopped · line dropped / back in ·
  leader gone · stuck · boss due back · morning summary

The topic is a secret (anyone who knows it can read your alerts), so it is kept in
Windows Credential Manager like your password, not in the settings file. Messages say what
happened and your character's name — never your password, room contents or chat.
Sends run in the background and never hold up the game; at most one alert per kind every 30 s.
"""
from __future__ import annotations

import threading
import time
import urllib.request

KINDS = {"hangup": "Hang-ups", "pvp": "Attacked by a player", "death": "Died",
         "track": "Tracks of a stranger", "stop": "Stopped (boss room, lost, needs an item)",
         "drop": "Line dropped / back in", "leader": "Leader gone / left behind", "stuck": "Stuck (watchdog)", "boss": "Boss due back",
         "quest": "A teammate's quest flag went up",
         "upgrade": "Gear upgrade seen (floor, loot or shop)",
         }
SECRET_USER = "ntfy-topic"
GAP = 30


def get_topic() -> str:
    from .config import get_password
    return get_password(SECRET_USER) or ""


def set_topic(topic: str) -> bool:
    from .config import set_password
    return set_password(SECRET_USER, (topic or "").strip() or None)


class Notifier:
    def __init__(self, session):
        self.s = session
        self._last: dict = {}
        self.last_result = ""

    def send(self, kind: str, msg: str, force=False):
        cfg = self.s.settings
        try:
            self.s.sounds.play(kind)
        except Exception:
            pass
        # (chat keyword alerts have their own switch, Settings → Phone alerts → Chat keywords: chatalerts.py)
        if not force and (not cfg.ntfy_on or (kind not in (cfg.ntfy_kinds or []) and kind != "chat")):
            return False
        topic = get_topic()
        if not topic:
            return False
        now = time.time()
        if not force and now - self._last.get(kind, 0) < GAP:
            return False
        self._last[kind] = now
        server = (cfg.ntfy_server or "https://ntfy.sh").rstrip("/")
        if not server.startswith("https://") and not server.startswith("http://localhost"):
            self.last_result = "ntfy server must be https://"
            return False
        who = cfg.my_name or "MudPilot"
        title = f"{who}: {KINDS.get(kind) or {'summary': 'Morning summary', 'test': 'Test', 'control': 'Reply', 'tune': 'Auto-tune', 'chat': 'Chat keyword'}.get(kind, kind)}"
        url = f"{server}/{urllib.request.quote(topic, safe='')}"
        prio = "urgent" if kind in ("pvp", "death") else "high" if kind == "hangup" else "default"

        def post():
            try:
                req = urllib.request.Request(url, data=msg[:300].encode("utf-8"), method="POST",
                                             headers={"Title": title.encode("ascii", "replace").decode(),
                                                      "Priority": prio, "Tags": "crossed_swords,mudpilot"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    self.last_result = f"sent ({r.status})"
            except Exception as ex:                    # no network, bad server … never bothers the game
                self.last_result = f"failed: {ex}"
        threading.Thread(target=post, daemon=True).start()
        return True


# ---------------------------------------------------------------- phone control
CONTROL_HELP = "Send: status · stop · hang up"
CONTROL_GAP = 5          # seconds between commands (flood guard)


class PhoneControl:
    """Listens on your ntfy topic for 'status', 'stop' or 'hang up' typed in the ntfy app.

    Off unless you tick it (Settings → Phone alerts). Only those three words do anything — nothing
    from the phone can walk, cast, say or type in the game. MudPilot's own alerts (tagged
    'mudpilot') are ignored, and so is anything sent before it started listening."""

    def __init__(self, session):
        self.s = session
        self._thread = None
        self._want = False
        self._last_cmd = 0.0
        self.state = "off"

    def tick(self):
        cfg = self.s.settings
        want = bool(cfg.ntfy_on and cfg.ntfy_control and get_topic())
        if want and not (self._thread and self._thread.is_alive()):
            self._want = True
            self._thread = threading.Thread(target=self._listen, daemon=True)
            self._thread.start()
        elif not want:
            self._want = False
            self.state = "off"

    def _listen(self):
        import json
        since = str(int(time.time()))
        backoff = 5
        while self._want:
            topic = get_topic()
            server = (self.s.settings.ntfy_server or "https://ntfy.sh").rstrip("/")
            if not topic or not server.startswith(("https://", "http://localhost")):
                self.state = "no topic / server"
                time.sleep(10)
                continue
            url = f"{server}/{urllib.request.quote(topic, safe='')}/json?since={since}"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "MudPilot"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    self.state = "listening"
                    backoff = 5
                    for raw in r:
                        if not self._want:
                            return
                        try:
                            ev = json.loads(raw.decode("utf-8", "replace"))
                        except ValueError:
                            continue
                        if ev.get("event") != "message":
                            continue
                        since = ev.get("id") or since
                        if "mudpilot" in (ev.get("tags") or []):
                            continue                      # one of our own alerts
                        text = (ev.get("message") or "").strip()
                        self.s._bg.put(lambda t=text: self.handle(t))
            except Exception as ex:
                self.state = f"reconnecting ({ex.__class__.__name__})"
                time.sleep(backoff)
                backoff = min(backoff * 2, 120)

    def handle(self, text: str):
        """Runs on the main thread."""
        s = self.s
        now = time.time()
        cmd = " ".join(text.lower().split())
        if now - self._last_cmd < CONTROL_GAP:
            return
        self._last_cmd = now
        reply = lambda m: s.notify.send("control", m, force=True)
        if cmd in ("status", "s", "?"):
            s.log("Phone: status asked")
            reply(self.status_text())
        elif cmd in ("stop", "stop bot"):
            s.log("Phone: stop")
            s.bot.stop("Stopped by you (phone)")
            reply("Stopped. " + self.status_text())
        elif cmd in ("hang up", "hangup", "hang-up", "hang"):
            s.log("Phone: hang up")
            if s.telnet.connected:
                s.safety.hangup("from your phone", manual=True)
                reply("Hung up. It stays offline until you reconnect.")
            else:
                reply("Not connected.")
        elif cmd in ("help", "commands"):
            reply(CONTROL_HELP)
        else:
            reply(f"Didn't understand '{text[:40]}'. {CONTROL_HELP}")

    def status_text(self) -> str:
        s = self.s
        st, b = s.state, s.bot
        r = s.world.room(st.room) if st.room else None
        lines = [("Connected" if s.telnet.connected else "NOT connected") + f" — {b.status}",
                 f"HP {st.hp}/{st.max_hp}  MA {st.ma}/{st.max_ma}" + (f"  at {r.name}" if r else ""),
                 f"Exp/hr {s.stats.exp_rate() / 1000:,.0f}k (last 30 min {s.stats.exp_rate(1800) / 1000:,.0f}k), "
                 f"{st.exp_gained:,} exp this session"]
        if b.walking and b.path:
            lines.append(f"{'Looping' if b.loop else 'Walking'} {b.path.title}" + (f", lap {b.laps}" if b.loop else ""))
        return "\n".join(lines)
