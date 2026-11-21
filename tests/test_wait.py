"""@wait without @ok doesn't strand the leader; stale room after Combat Off isn't acted on; leader rank learned."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st)
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T()
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
r = s.remote
r.holds["Revolution"] = time.time() - 60
s.state.party = {"Miserable": {"hp": 100, "ma": 100, "t": time.time()},
                 "Revolution": {"hp": 100, "ma": 94, "t": time.time()}}
check("topped-up waiter with no @ok is let go", r.holding() is None)
r.holds["Revolution"] = time.time() - 60
s.state.party["Revolution"] = {"hp": 50, "ma": 20, "t": time.time()}
check("still hurt → keep waiting", r.holding() == "Revolution")
r.holds["Revolution"] = time.time() - 400
check("5 minutes → let go", r.holding() is None)
# @ok behind a chain of resting prompts (0.8.67 live: missed every time, held 45-67 s instead of 4 s)
r.holds["Revolution"] = time.time()
s._line([("[HP=542/MA=463]: (Resting) [HP=537/MA=463]: (Resting) Revolution telepaths: @ok", Style())])
check("@ok after '(Resting)' prompts releases the hold", "Revolution" not in r.holds)
r.holds["Revolution"] = time.time()
s._line([("[HP=659/MA=373]: (Meditating) Revolution telepaths: @ok", Style())])
check("@ok after a '(Meditating)' prompt releases the hold", "Revolution" not in r.holds)
# stale room
s.state.view = RoomView("Trail", {"S"}, monsters=[("nightshade", {"num": 1, "name": "nightshade", "exp": 9, "align": 2})])
s.state.feed_line([("*Combat Off*", Style())])
check("Combat Off clears the dead mob from the view", s.state.view.monsters == [])
# leader rank
s.bot.x.note_line("You may not leave your current rank in your own party.")
check("learns it's our party (no more rank tries)", s.bot.x._rank_tries == 99 and s.bot.x.leading())
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
