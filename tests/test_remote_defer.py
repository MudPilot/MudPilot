"""Dan, 2026-10-28: an @ that needs 'i' or 'st' to answer should read it and then answer, not tell you to type it.
@have / @wealth / @enc read 'i'; @lives reads 'st'; @level reads 'exp' (test_remote covers that one)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                        "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
r = s.remote; r._channel = "telepath"; g = s.state
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

# @have: no inventory → type i, then answer (never "type i first")
out = r.c_have("Miserable", "log raft")
check(f"@have types i, no punt ({out!r})", out is None and sent == ["i"])
g.carrying = "25 runic coins, log raft, rope and grapple"; g.inv_new = True
s.tick_defer = None
sent.clear(); g.inv_new = False; r.inv_answer()
check(f"@have answers from the read ({sent})", any("log raft" in c and "yes" in c for c in sent))

# @wealth
sent.clear(); out = r.c_wealth("Miserable", "")
check(f"@wealth types i ({out!r})", out is None and sent == ["i"])
g.wealth = 30449700; sent.clear(); r.inv_answer()
check(f"@wealth answers ({sent})", any("30,449,700" in c for c in sent))

# @enc
sent.clear(); out = r.c_enc("Miserable", "")
check(f"@enc types i ({out!r})", out is None and sent == ["i"])
g.enc = (1877, 3840, "Medium", 48); sent.clear(); r.inv_answer()
check(f"@enc answers ({sent})", any("1877/3840" in c for c in sent))

# @lives: no stat → type st, then answer
sent.clear(); out = r.c_lives("Miserable", "")
check(f"@lives types st ({out!r})", out is None and sent == ["st"])
g.lives = 9; sent.clear(); r.stat_answer()
check(f"@lives answers ({sent})", any("9 lives" in c for c in sent))

# known values answer straight away (no extra read)
sent.clear()
check(f"@wealth known → direct ({r.c_wealth('Miserable','')})", "30,449,700" in r.c_wealth("Miserable", "") and not sent)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
