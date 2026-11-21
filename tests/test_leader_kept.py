"""0.8.212 (Dan, 2026-11-19): the PvP party broke; Miserable (follower, no loop of its own) must not invite
Revolution, its leader — and Revolution, leading its loop, must not join Miserable on Miserable's @join."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
def mk(name):
    st = config.Settings(); st.save = lambda: None; st.my_name = name
    s = Session(st); sent = []
    class T:
        connected = True
        events = __import__("queue").Queue()
        def send_line(self, x): sent.append(x)
        def close(self): pass
    s.telnet = T()
    return s, sent
m, ms = mk("Miserable")
x = m.bot.x
x._following, x._followed, x._followed_t = None, "Revolution", time.time() - 30   # the party just broke
m.send("invite Revolution", from_bot=True)
check(f"follower doesn't auto-invite its leader after the party broke ({ms})", not any("invite" in c for c in ms))
m.send("invite Bob", from_bot=True)
check("…others still get invited", any(c.startswith("invite Bob") for c in ms))
ms.clear(); x._followed_t = time.time() - 4000; m._party_sent = {}
m.send("invite Revolution", from_bot=True)
check("…an hour later it may", any(c.startswith("invite Revolution") for c in ms))
ms.clear(); x._followed_t = time.time() - 30
m.remote._asked_invite = True
m.send("invite Revolution", from_bot=True)
check("…and a member's own @invite still goes", any(c.startswith("invite Revolution") for c in ms))
m.remote._asked_invite = False
r, rs = mk("Revolution")
r.bot.walking, r.bot.loop = True, True
r.remote._invited_back = {"miserable": time.time() - 2}
r.remote.c_join("Miserable", "")
check(f"leader on its loop, just invited them back: their @join doesn't pull it over ({rs})", "join Miserable" not in rs)
r.remote._invited_back = {}
r.remote.c_join("Miserable", "")
check("…an @join out of the blue is still obeyed", "join Miserable" in rs)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
