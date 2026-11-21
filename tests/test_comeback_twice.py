"""Dan, 2026-11-15: Miserable answered Revolution's broken party (@where → walking to him) and Revolution's own
'@comeback 14/6559' came in a moment later. The second fetch took the Go to as where to carry on afterwards: the
Stonecaps loop was forgotten and Miserable stood in Bristlewood Grove from 02:25 till morning."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
b, c = s.bot, s.comeback
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
class P:
    title = "Stonecaps loop"; steps = []; is_loop = True; resolved = True
loop = P()
b.path, b.loop, b.walking = loop, True, True
b.x._own_party = True
s.state.party = {"Miserable": {}, "Revolution": {}}
rooms = list(s.world.rooms)
here, target = rooms[0], rooms[10]
s.state.candidates = [here]
calls = []
class G:
    title = "Go to"; steps = []; is_loop = False; resolved = True
def goto(room, then=None, ask=None):
    calls.append(("goto", room))
    g = G(); g.title = f"Go to {room[0]}/{room[1]}"
    b.path, b.loop, b.walking, b._goto_target = g, False, True, room
    return True
b.goto = goto
b.start_path = lambda mp, loop=None, checked=False: calls.append(("loop", mp.title)) or True

c._ask_where("Revolution")                               # the party broke: asked @where
feed(f"Revolution telepaths: {{Bristlewood Grove - map {target[0]} room {target[1]}; exits: north}}")
check(f"walking to Revolution ({calls})", calls and calls[-1] == ("goto", target))
check("…the loop kept for afterwards", c.fetch and c.fetch.get("back") == (loop, True))

s.remote.c_comeback("Revolution", f"{target[0]}/{target[1]}")   # his own @comeback, a second later
check(f"his @comeback doesn't replace the loop with the Go to ({c.fetch.get('back')})",
      c.fetch and c.fetch.get("back") == (loop, True))

s.state.candidates = [target]; b.walking = False
s.state.party = {"Miserable": {}, "Revolution": {}}
calls.clear()
c.fetch["phase"] = "invited"; c.fetch["t"] = time.time()
c.tick()
check(f"he's back → back to the Stonecaps loop ({calls})", ("loop", "Stonecaps loop") in calls)
check("…not another Go to", not any(x[0] == "goto" for x in calls))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
