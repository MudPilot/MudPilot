"""0.8.179: a character walking its own loop doesn't drop it to join whoever invites it (Evolution joined Buddy at
17/183 after the 2026-11-11 restart; Buddy runs no loop, so the PVE party stood still). It invites them instead.
Two characters both walking loops: the name that sorts first leads, so they don't hunt apart."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import MPath
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

def make(name):
    st = config.Settings(); st.save = lambda: None; st.my_name = name
    s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
    sent = []
    s.send = lambda c, **k: sent.append(c)
    s.log = lambda m, *a, **k: None
    st.remote_players = {"Buddy": ["query", "move"], "Aaron": ["query"], "Zed": ["query"]}
    for who in ("Buddy", "Aaron", "Zed"):
        s.players.get(who.lower())["join_if_invited"] = True
    return s, sent

def walk(s, loop=True):
    s.bot.path = MPath(name="Rotting Glade", author="", start_hash="a", end_hash="a")
    s.bot.walking, s.bot.loop = True, loop

s, sent = make("Evolution")
walk(s)
s.bot.note_line("Buddy has invited you to follow him.")
check(f"walking my loop: doesn't join, invites them once ({sent})",
      not any(c.startswith("join") for c in sent) and sent.count("invite Buddy") == 1)
check("…and the loop keeps going", s.bot.walking)

s, sent = make("Evolution")
walk(s, loop=False)
s.bot.note_line("Buddy has invited you to follow him.")
check(f"on a one-off Go to: joins as before ({sent})", "join Buddy" in sent)

s, sent = make("Evolution")
s.bot.note_line("Buddy has invited you to follow him.")
check(f"standing still: joins as before ({sent})", "join Buddy" in sent)

s, sent = make("Evolution")
walk(s)
s.remote.c_join("Buddy", "")
check(f"an explicit @join is still obeyed ({sent})", "join Buddy" in sent)

# both walking loops: Evolution vs Zed (Evolution sorts first, so it leads)
s, sent = make("Evolution")
walk(s)
s.bot.note_line("Zed has invited you to follow him.")
sent.clear(); time.sleep(0.6)
s.bot.note_line("Zed has invited you to follow him.")          # Zed kept its loop and invited back
check(f"both on loops, I sort first: I invite again, don't join ({sent})",
      "invite Zed" in sent and not any(c.startswith("join") for c in sent))
s, sent = make("Evolution")
walk(s)
s.bot.note_line("Aaron has invited you to follow him.")
sent.clear(); time.sleep(0.6)
s.bot.note_line("Aaron has invited you to follow him.")
check(f"both on loops, they sort first: I join them ({sent})", "join Aaron" in sent)

s, sent = make("Evolution")
walk(s)
s.bot.x._followed = "Buddy"
s.bot.note_line("Buddy has invited you to follow him.")
check(f"my own leader inviting me back: joins ({sent})", "join Buddy" in sent and "invite Buddy" not in sent)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
