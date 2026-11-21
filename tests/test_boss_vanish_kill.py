"""Dan, 2026-11-04: 'mp says i saw crimson mist alive 3 hours ago, doesn't show its been killed'. The party killed it
twice (3/588 and 3/601), but its death line ('The crimson mist suddenly solidifies and vanishes in a shower of
blood!') took it off the room list before 'You gain 100000 experience.', so the boss tracker never tied the exp to it
and the hunt swept on. The exp is credited to the monster its death line named: count that one."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.send = lambda c, from_bot=False: None
s.bosses.save = lambda: None
s.bosses.data = {"309": {"name": "crimson mist", "kills": [], "manual": True}}     # added on the Bosses tab
logs = []
s.log = lambda m, *a, **k: logs.append(m)
def feed(*lines):
    for ln in lines:
        for segs in s.ansi.feed(ln + "\r\n"):
            s._line(segs)
        s.state.feed_partial(s.ansi.partial_text())
feed("[HP=285/MA=249]:", "Destroyed Mage Shop", "Also here: Revolution, Buddy, crimson mist, fat lamia.",
     "Obvious exits: north", "[HP=285/MA=249]:")
check("the mist is in the room (the hand-added #309)", [b["num"] for b in s.bosses.bosses_in_view()] == [309])
feed("Buddy hacks crimson mist for 60 damage!",
     "The crimson mist suddenly solidifies and vanishes in a shower of blood!",
     "You gain 100000 experience.", "*Combat Off*", "[HP=285/MA=249]:",
     "Destroyed Mage Shop", "Also here: Revolution, Buddy, fat lamia.", "Obvious exits: north", "[HP=285/MA=249]:")
r = s.bosses.data["309"]
check(f"its kill is recorded ({[l for l in logs if 'Boss' in l]})", r.get("last_kill") and len(r.get("kills", [])) == 1)
check("dead since then (the hunt sees it's killed)", r.get("dead_since"))
# a plain monster's death doesn't count as a boss kill
logs.clear()
feed("The fat lamia wails loudly, and falls dead!", "You gain 241 experience.", "[HP=285/MA=249]:",
     "Destroyed Mage Shop", "Also here: Revolution, Buddy.", "Obvious exits: north", "[HP=285/MA=249]:")
check(f"the lamia isn't a boss kill ({logs})", not [l for l in logs if "Boss killed" in l]
      and len(s.bosses.data["309"]["kills"]) == 1 and "303" not in s.bosses.data)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
