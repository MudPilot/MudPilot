"""Party comeback: leader waits for a dropped member, asks @where, walks there, re-invites, back to the loop."""
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
    title = "Rotting Glade loop"; steps = []; is_loop = True; resolved = True
b.path, b.loop, b.walking = P(), True, True
b.x._own_party = True
s.state.party = {"Miserable": {}, "Revolution": {}}
here = next(iter(s.world.rooms)); s.state.candidates = [here]
calls = []
b.goto = lambda room, then=None, ask=None: calls.append(("goto", room)) or True
b.start_path = lambda mp, loop=None, checked=False: calls.append(("loop", mp.title)) or True
feed("Revolution just disconnected!!!")
check("dropped → loop holds", c.holding() == "Revolution")
feed("Revolution just entered the Realm.")
check(f"back in → asked @where ({sent})", "/Revolution @where" in sent)
target = list(s.world.rooms)[10]
feed(f"Revolution telepaths: {{Somewhere - map {target[0]} room {target[1]}; exits: north}}")
check(f"walks to the room they gave ({calls})", calls and calls[-1] == ("goto", target))
s.state.candidates = [target]; b.walking = False
c.tick()
check(f"arrived → invites ({sent[-1]})", sent[-1] == "invite Revolution")
c.fetch["t"] -= 30; c.tick()
check(f"then back to the loop ({calls[-1]})", calls[-1] == ("loop", "Rotting Glade loop") and c.fetch is None and not c.missing)
# timeout
feed("Revolution just disconnected!!!")
c.missing["Revolution"]["t"] -= 400
check("didn't come back in time → carries on", c.holding() is None)
# follower asks the leader to come back
s2 = Session(st); s2._no_log_file = True; s2.telnet = Tel(); s2._entered = True; sent.clear()
s2.bot.x._own_party = False; s2.bot.x._following = "Dan"; s2.bot.x._followed = "Dan"
s2.state.party = {}
s2.state.candidates = [here]
s2._line([("You are no longer following Dan.", Style())])
check(f"follower whose party broke asks @comeback ({sent})", f"/Dan @comeback {here[0]}/{here[1]}" in sent)
sent.clear(); s2.comeback.note_sent("leave")
s2._line([("You are no longer following Dan.", Style())])
check("left on purpose → no @comeback", not sent)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
