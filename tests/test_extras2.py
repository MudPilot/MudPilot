"""Sounds, scheduler, tracking, leaderboard, 8-ball, quests."""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
config.DATA_DIR = tempfile.mkdtemp()
from mudpilot.session import Session
from mudpilot.ansi import Style
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
# tracking
s.tracker.start("Deacon")
check("trac sent", sent[-1] == "trac Deacon")
feed("Deacon went northeast from here.")
s.tracker.tick()
check(f"follows the trail ({sent[-1]})", sent[-1] == "ne")
feed("Your tracking skills fail you this time.", "Your tracking skills fail you this time.", "Your tracking skills fail you this time.")
check("lost the trail → stops", s.tracker.target is None)
# leaderboard
feed("Top Heroes of the Realm By Experience", "-----------------------------------",
     "  1. Angruin Stat         Mage      Phat Mackerel   1,234,567,890",
     "  2. Deacon               Priest    House of Rage     987,654,321", "")
check(f"leaderboard rows read ({list(s.leaderboard.samples)})", set(s.leaderboard.samples) == {"Angruin", "Deacon"})
s.leaderboard.samples["Deacon"].insert(0, [time.time() - 3600, 987_000_000])
r = dict((n, rate) for n, _e, rate in s.leaderboard.rates())
check(f"exp/hr worked out ({r['Deacon']:.0f})", 600_000 < r["Deacon"] < 700_000)
# 8-ball
st.eightball_on = True; sent.clear()
feed("Darkstar gossips: (8) will I get the drop?")
check(f"8-ball answers on gossip ({sent})", sent and sent[0].startswith("gos Mystic(8) says: "))
sent.clear(); feed("Bob gossips: (8) again?")
check("…with a cooldown", not sent)
# scheduler
st.schedules = [{"every": 0.0001, "action": "command", "arg": "stat", "on": True}]
s.scheduler.tick(); s.scheduler._fired[0] -= 10; sent.clear(); s.scheduler.tick()
check(f"scheduled command runs ({sent})", "stat" in sent)
# quests
s.quests.note_sent("? questlist")
feed("QUEST LIST", "LEVEL 10", "Tarl's Quest - Thief, Bard and Gypsy - Reward 50k exp and 30 platinum.")
s.quests._line_at -= 5; s.quests.tick()
check(f"quest page kept ({list(s.quests.pages)})", "? questlist" in s.quests.pages)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
