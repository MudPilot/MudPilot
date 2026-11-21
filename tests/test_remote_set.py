"""@nuke 2, @rest min70 max90, @medi 30 80, @heal 60 from a player allowed to change settings."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
st = config.Settings(); st.save = lambda: None; st.remote_players = {"Revolution": ["query", "settings"]}
st.my_name = "Miserable"
s = Session(st)
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
def say(m):
    s.remote._recent.clear(); sent.clear(); s._line([(f"Revolution telepaths: {m}", Style())])
say("@nuke 2"); check(f"@nuke 2 ({sent})", st.multi_min_mobs == 2 and st.use_area_min)
say("@rest min70 max90"); check(f"@rest min70 max90 ({sent})", st.rest_below_hp == 70 and st.rest_until_hp == 90)
say("@medi 30 80"); check("@medi 30 80", st.rest_below_ma == 30 and st.rest_until_ma == 80)
say("@heal 60"); check("@heal 60", st.heal_pct == 60)
say("@rest max95"); check("@rest max95 only changes the top", st.rest_below_hp == 70 and st.rest_until_hp == 95)
st.remote_players = {"Revolution": ["query"]}
say("@nuke 5"); check("not allowed settings → unchanged", st.multi_min_mobs == 2)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
