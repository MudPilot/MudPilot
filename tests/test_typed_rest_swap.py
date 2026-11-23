"""0.8.224.2: a rest you type yourself (walking around by hand) gets the pre-rest gear swap too, then sits back down;
the post-rest commands go out when it's topped up (Dan, 2026-11-22: the faded shawl stayed on)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
st.auto_rest = True; st.rest_below_hp = 50; st.rest_until_hp = 90; st.auto_regen_gear = False
st.rest_swap_on = True; st.pre_rest_cmd = "eq runed cape^Mremove platinum ring"; st.post_rest_cmd = "eq shawl^Meq platinum ring"
s = Session(st); s._no_log_file = True
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()
sent = []
s.bot.send = lambda c: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
b, g = s.bot, s.state
g.max_hp, g.hp, g.max_ma, g.ma = 738, 520, 98, 98          # 70%: over the rest line, so only a typed rest sits down
g.in_combat = False
g.resting = True                                            # Dan typed 'rest'
sent.clear(); r = b.should_rest([], False)
check(f"typed rest: pre-rest swap, then back down ({sent})",
      r and sent[:2] == ["eq runed cape", "remove platinum ring"] and sent[-1] == "rest")
sent.clear(); b.should_rest([], False)
check(f"…not swapped again on the next tick ({sent})", not any(c.startswith(("eq ", "remove")) for c in sent))
g.hp = 700                                                  # 95%: topped
sent.clear(); b.should_rest([], False)
check(f"topped: post-rest swap back ({sent})", sent[:2] == ["eq shawl", "eq platinum ring"])
st.rest_swap_on = False
g.hp, g.resting = 520, True
b._cool.pop("typed_rest_swap", None)
sent.clear(); b.should_rest([], False)
check(f"no swap set: a typed rest is left alone ({sent})", not sent)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
