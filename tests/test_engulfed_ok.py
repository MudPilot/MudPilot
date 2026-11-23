import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st); s._no_log_file = True
out = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): out.append(x)
    def close(self): self.connected = False
s.telnet = T()
s.state.party = {"Buddy": {}, "Revolution": {}}
s.bot.x._following = "Revolution"
def line(t):                                  # the order session._line uses
    s.comeback.feed_line(t); s.msgrules.feed_line(t); s.bot.note_line(t)
for start, end in (("You are paralyzed!", "The paralysis wears off."), ("You are engulfed!", "You are freed!")):
    out.clear(); s.bot.x.care._reported.clear(); s.bot.x.ailments.clear()
    line(start); time.sleep(0.1)
    print(f"[{start}] sent={out} reported={s.bot.x.care._reported} ail={list(s.bot.x.ailments)} cond={list(s.msgrules.conditions)}")
    out.clear(); line(end)
    print(f"[{end}] sent={out} reported={s.bot.x.care._reported} ail={list(s.bot.x.ailments)} cond={list(s.msgrules.conditions)}")
# later: a rest @wait then release
x = s.bot.x
x._sent_wait = True; x._wait_to = "Revolution"; out.clear()
x.release_hold("rest")
print("later rest done, @ok sent?", out)
