"""0.8.177: @inventory answers with all of it — no '...(more)' — one game line every 2 s (Dan, 2026-11-11: "when i ask
them to see their inventory i'd like to see all of it… with a 2 second delay between them")."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append((time.time(), x))
    def close(self): pass
s.telnet = Tel(); s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
r = s.remote
items = ["earrings", "white gold ring", "iron keyring", "folds of worship", "mine pass", "stone signet",
         "inscribed stone tablet", "crimson-bound parchment", "scorpion tail", "titanium fork", "spider silk",
         "6 severed head of Goru-Nezar", "eye of the beholder", "sash of the mystic"] + \
        [f"thing number {i} with a long name" for i in range(30)]
s.state.carrying = ", ".join(items) + "."
s.state.keys = "dragon key, iron key"
s.state.wealth = 12800000
s.state.enc = (1909, 4536, "Medium", 42)
lines = r._inv_lines()
txt = " ".join(lines)
check(f"no '(more)' ({len(lines)} lines)", "(more)" not in txt)
check("every item is in it", all(i in txt for i in items))
check("keys, wealth and encumbrance too", "dragon key" in txt and "12,800,000" in txt and "1909/4536" in txt)
sent.clear()
r.reply_all("telepath", "Miserable", lines)
r._paced_tick()
check(f"the first line goes straight away ({len(sent)})", len(sent) == 1)
r._paced_tick()
check("the next one waits", len(sent) == 1)
t0 = time.time()
while r._paced and time.time() - t0 < 120:
    r._paced_tick()
    time.sleep(0.05)
gaps = [b[0] - a[0] for a, b in zip(sent, sent[1:])]
check(f"all of it went out ({len(sent)} game lines)", not r._paced and len(sent) >= len(lines))
check(f"about 2 s between them (min {min(gaps):.2f} s)", gaps and min(gaps) >= 1.9)
check("each fits the game's 127-character line", all(len(x) <= 127 for _t, x in sent))
got = " ".join(x for _t, x in sent)
check("nothing lost in the split", all(i in got for i in items))
check("all telepaths to the one who asked", all(x.startswith("/Miserable {") for _t, x in sent))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
