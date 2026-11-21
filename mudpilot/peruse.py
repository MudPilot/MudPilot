"""Peruse books — Golden Spire, Secret Library (12/2248). Dan, 2026-11-04.

MME's room commands there: 'peruse blue book' raises quest flag 134 from 5 to 6 (always works); then
'peruse red book' wants 134 = 6, takes ~10 s each time (adddelay 10) and is an intellect roll — usually
several goes — and on a pass gives 134 = 7 and the pharaoh story. So: walk there ('turn stand' in the
Library, 12/2247, opens the door on the way), blue once, red until the story comes, then say so in the room — someone sent off AFK with
'@loop peruse books' can see it's done.
"""
from __future__ import annotations

import re
import time

ROOM = (12, 2248)
ROOMS = {ROOM}
FLAG = "134"
RED_EVERY = 15            # the red book's adddelay is 10 s: one go at a time (sooner when the failure comes)
MAX_TRIES = 100
DONE_SAY = "Books have been properly perused!"
DONE_RE = re.compile(r"may god have mercy on their souls|summoned a nether\s*beast", re.I)
# a failed roll (Dan's paste): go again as soon as it comes
FAIL_RE = re.compile(r"despite countless minutes of painstaking translation", re.I)
# the book won't open for you at all: quest flag 134 isn't where the red book wants it
NOSENSE_RE = re.compile(r"flip through the book, but can make no sense of the writing", re.I)
NAMES = ("peruse books", "peruse book", "peruse")


class Peruse:
    def __init__(self, bot):
        self.bot = bot
        self.active = None       # {"step": go / blue / red, "tries", "sent", "t"}

    def _flag(self):
        try:
            return int((self.bot.cfg.known_abils or {}).get(FLAG))
        except (TypeError, ValueError):
            return None

    def start(self) -> str:
        b = self.bot
        if (self._flag() or 0) >= 7:
            return "books already perused (quest flag 134 = 7)"
        self.active = {"step": "go", "tries": 0, "sent": 0.0, "t": time.time()}
        if b.st.room in ROOMS:
            return "perusing the books"
        if not b.goto(ROOM):
            self.active = None
            return "can't get to the Golden Spire Secret Library" + (f": {b.no_route_msg}" if b.no_route_msg else "")
        return "walking to the Golden Spire Secret Library to peruse the books"

    def stop(self) -> bool:
        was, self.active = self.active, None
        return bool(was)

    def tick(self) -> bool:
        a, b = self.active, self.bot
        if not a or b.walking:
            return False
        st, now = b.st, time.time()
        if st.room not in ROOMS:
            if now - a["t"] > 10:                      # the walk ended somewhere else
                b.log("Peruse books: didn't get to the Golden Spire Secret Library — stopped")
                self.active = None
            return False
        if st.in_combat or st.resting or st.pending:
            return False
        if a["step"] == "go":
            b.log("Peruse books: in the Golden Spire Secret Library — the blue book, then the red one until it takes")
            b.send("peruse blue book")
            a.update(step="red", sent=now)
            return True
        if now - a["sent"] < (3 if a["tries"] == 0 else RED_EVERY):
            return True
        if a["tries"] >= MAX_TRIES:
            b.log(f"Peruse books: the red book didn't take in {MAX_TRIES} goes — stopped")
            self.active = None
            return False
        a["tries"] += 1
        a["sent"] = now
        b.send("peruse red book")
        return True

    def note_line(self, text: str):
        a, b = self.active, self.bot
        if not a or a["step"] != "red":
            return
        if FAIL_RE.search(text):
            a["sent"] = time.time() - RED_EVERY         # failed roll: straight back at it
            a["nosense"] = 0
            return
        if NOSENSE_RE.search(text):
            a["nosense"] = a.get("nosense", 0) + 1
            if a["nosense"] >= 3:
                b.log("Peruse books: the red book makes no sense to you 3 times running — quest flag 134 isn't "
                      "at 6 (blue book not done?) — stopped")
                self.active = None
            return
        if DONE_RE.search(text):
            b.log(f"Peruse books: done after {self.active['tries']} goes at the red book")
            self.active = None
            b._quest_poke = time.time()                # read the quest flags again (134 = 7)
            b.send(f".{DONE_SAY}")                     # Dan: just ".", which works with talk set slow too
