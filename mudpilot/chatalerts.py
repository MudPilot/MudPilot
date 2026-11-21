"""Chat keyword alerts (0.8.201, off unless ticked: Settings → Phone alerts → Chat keywords).

A gossip / auction / telepath / gangpath / broadcast / say / yell line with one of your words in it
(whole word, any case; a phrase works too) is logged highlighted, and — if phone alerts (ntfy) are set
up — sent to the phone. Your own lines, the party's @/{ } bot chatter and lines put back after a
restart never count. A spammy channel can't flood the phone: one phone alert a minute at most, and
the same word from the same player only once every 10 minutes (the log still shows every hit).
The phone alert says who, which channel and which word — not the message itself (alerts never carry chat).
"""
from __future__ import annotations

import re
import time

CHANNELS = ("gossip", "auction", "telepath", "gangpath", "broadcast", "say", "yell")
PHONE_GAP = 60           # seconds between any two chat phone alerts
REPEAT_GAP = 600         # the same word from the same player
LOG_MARK = "★ Chat keyword"


def find_word(words, text: str) -> str | None:
    for w in words or ():
        w = (w or "").strip()
        if w and re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", text or "", re.I):
            return w
    return None


class ChatAlerts:
    def __init__(self, session):
        self.s = session
        self._phone_last = 0.0
        self._seen: dict = {}            # (word, who) -> last phone alert time
        self.hits = 0

    def on_chat(self, e):
        """ChatLog listener: e = (time, channel, who, text). Never raises (a raising listener is dropped)."""
        try:
            self._check(e)
        except Exception:
            pass

    def _check(self, e):
        cfg = self.s.settings
        if not getattr(cfg, "chat_alerts_on", False):
            return
        _t, ch, who, msg = e
        if ch not in CHANNELS:
            return
        name = (who or "").split(" (")[0].strip()
        me = (getattr(cfg, "my_name", "") or "").strip().lower()
        if not name or name.startswith("You") or (me and name.lower() == me):
            return                                        # your own lines
        from .chat import ChatLog
        if ChatLog._bot_text(msg):
            return                                        # @ok / {answers}: MudPilots talking
        word = find_word(getattr(cfg, "chat_alert_words", None), msg)
        if not word:
            return
        self.hits += 1
        self.s.log(f"{LOG_MARK} '{word}' — {name} ({ch}): {msg}")
        now = time.time()
        key = (word.lower(), name.lower())
        if now - self._phone_last < PHONE_GAP or now - self._seen.get(key, 0) < REPEAT_GAP:
            return
        notify = getattr(self.s, "notify", None)
        if notify is not None and notify.send("chat", f"{name} said '{word}' on {ch}"):
            self._phone_last = now
            self._seen[key] = now
