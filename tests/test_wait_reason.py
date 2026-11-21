"""@wait says why (and the leader shows it); you can let a stuck @wait go with .@ok / @do .@ok / @party .@ok;
a real one is said again a minute on (Dan, 2026-11-02)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

# ---- leader side
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
st.remote_channels = dict(st.remote_channels or {}, telepath=True, say=True)
s = Session(st); s.telnet = T()
r = s.remote
s.state.party = {"Miserable": {"hp": 100, "ma": 100, "t": time.time()},
                 "Revolution": {"hp": 100, "ma": 100, "t": time.time()},
                 "Evolution": {"hp": 80, "ma": 50, "t": time.time()}}
s._line([("Revolution telepaths: @wait (confused)", Style())])
check("hold kept with its reason", r.holding() == "Revolution" and r.hold_why.get("Revolution") == "confused")
check("shown as 'Revolution @wait: confused'", r.hold_text() == "Revolution @wait: confused")
r.holds["Revolution"] = time.time() - 60
s.state.party["Revolution"]["t"] = time.time()
check("confused at full HP is not 'looks ready'", r.holding() == "Revolution")
r.holds["Revolution"] = time.time() - 130
check("2 min with no further @wait: let go", r.holding() is None and "Revolution" not in r.hold_why)
s._line([("Evolution telepaths: @wait", Style())])
check("bare @wait: no reason given, with what par shows", "no reason given, H:80% M:50%" in r.hold_text())
s.send(".@do .@ok")
check("you typing @ok lets every @wait go", not r.holds)
s._line([("Revolution telepaths: @wait (resting)", Style())])
s._line([('Revolution says "@ok"', Style())])
check("@ok said in the room by the waiter releases it", not r.holds)

# ---- follower side: @do .@ok / @party .@ok are allowed (the only @command an @do passes on)
st2 = config.Settings(); st2.save = lambda: None; st2.my_name = "Buddy"
st2.remote_channels = dict(st2.remote_channels or {}, telepath=True, say=True)
f = Session(st2); f.telnet = T()
f.state.party = {"Miserable": {"hp": 100, "ma": 100, "t": time.time()}, "Buddy": {"hp": 100, "ma": 100, "t": time.time()}}
sent.clear()
f._line([('Miserable says "@do .@ok"', Style())])
check("@do .@ok is done", ".@ok" in sent)
sent.clear()
f._line([('Miserable says "@do /Bob @goto town"', Style())])
check("@do with another @command still refused", not any("@goto" in x for x in sent))
sent.clear()
f.bot.x._following = "Miserable"
f._line([('Miserable says "@party .@ok"', Style())])
check("@party .@ok is said, no party move", ".@ok" in sent and not getattr(f, "_rejoin", None))

# follower: reason sent, and said again a minute on
x = f.bot.x
x.leader = lambda: "Miserable"
x.leading = lambda: False
sent.clear()
x.ailments["confused"] = time.time()
x.need_hold("ailment", "confused")
check("follower sends '@wait (confused)'", "/Miserable @wait (confused)" in sent)
sent.clear()
x.need_hold("ailment", "confused")
check("not again straight away", not sent)
x._wait_sent_at = time.time() - 61
x.need_hold("ailment", "confused")
check("said again a minute on", "/Miserable @wait (confused)" in sent)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
