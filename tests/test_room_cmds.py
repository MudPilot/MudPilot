"""MME room commands ('say gazmuldduhaz' opens the Small Pyramid's hidden exit) and ability-gated exits."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
st = config.Settings(); st.save = lambda: None; st.board = "Paradigm"
s = Session(st); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
w, b = s.world, s.bot
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
ex = w.room((12, 1188)).exits["N"]
check(f"Small Pyramid hidden exit opens with 'say gazmuldduhaz' ({ex.action_cmds()})", ex.action_cmds() == ["say gazmuldduhaz"])
s.state.candidates = [(17, 1630)]; s.state.level = 47
s.state.carrying = "nothing"; s.state.inv_seq = 1
b.held_items = lambda: set()
started = b.goto((12, 1239))
check(f"ability unknown → asks the game first ({sent})", started and "abil 134" in sent)
for line in ("granted: Quest(134)                 0010",):
    s._line([(line, Style())])
check(f"abil 134 read ({s.state.abil_value(134, 'total')})", s.state.abil_value(134, "total") and s.state.abil_value(134, "total")[0] == 10)
b._pending_abil = (b._pending_abil[0], None, None, time.time() - 5)
b.walking = False
paths = []
b.start_path = lambda mp, loop=None, checked=False: paths.append(mp) or True
b.tick()
check(f"…then routes through the gates ({len(paths[0].steps) if paths else None} steps)", paths and len(paths[0].steps) > 100)
pre = [stp for stp in paths[0].steps if stp.pre] if paths else []
check(f"…saying the word at the pyramid ({[p_.pre for p_ in pre][:3]})", any("say gazmuldduhaz" in p_.pre for p_ in pre))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
