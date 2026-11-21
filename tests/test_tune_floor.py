"""Revolution, 2026-10-30 (purple worms, 'let MudPilot decide'): spell efficiency stepped him down one spell at a time
— soul rip, soulstrike, divine fury, god's wrath, holy force, godstrike — each step judged only against the one
before, so the slowdowns added up. Now: never more than MAX_STEPS below the strongest, and a step is kept only if
kills stay within 15% of the strongest spell's, not just the last one's."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
import mudpilot.spelltune as SPT
from mudpilot.session import Session

st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"; st.spell_efficiency = True
s = Session(st); s._no_log_file = True
t = s.spelltune
t.note_ladder("purple worm", 8)                     # eight spells on his ladder
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


def window(secs, mana):
    for _ in range(SPT.WINDOW):
        t.record("purple worm", secs, 1.0, mana)     # he does all the damage


m = lambda: t.mons["purple worm"]
window(5.0, 100)                                   # strongest spell: 5 s a kill
check("tries one step down", m()["lv"].get(t.me()) == 1)
window(5.6, 80)                                    # a little slower, cheaper: kept
check("keeps it (5.6 s vs 5.0 s)", m()["lv"].get(t.me()) == 1 and m()["trial"] is None)
window(5.6, 80)
check("tries a second step", m()["lv"].get(t.me()) == 2)
window(7.0, 64)                                    # fine against the last step (5.6 s), 40% over the strongest (5.0 s)
check(f"refused: too slow against the strongest spell (lv {m()['lv'].get(t.me())})", m()["lv"].get(t.me()) == 1)
# a fast party: every step 'no slower' — still never more than MAX_STEPS down
t.mons.clear()
for i in range(12):
    window(5.0, 100 * 0.8 ** i)                    # no slower, cheaper every time
check(f"never more than {SPT.MAX_STEPS} below the strongest (lv {m()['lv'].get(t.me())})",
      m()["lv"].get(t.me(), 0) <= SPT.MAX_STEPS)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
