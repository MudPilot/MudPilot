"""Dan, 2026-11-01: a party member who can do traps disarms them for the leader. Their MudPilot tells the leader its
Traps skill (party sync); at a trapped exit the leader '@do disarm trap <dir>'s the best one standing there, and the
disarmer says how it went."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.megamud_files import Step
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


def make(name):
    st = config.Settings(); st.save = lambda: None; st.my_name = name
    s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
    s.telnet.sock = object()
    sent = []
    s.send = lambda c, from_bot=False: sent.append(c)
    return s, sent


# the disarmer's side: Traps read from 'st', shared
thief, tsent = make("Sneaky")
thief.state._scan_status_lines("Strength:  60     Agility: 90          Traps:          85")
check(f"Traps read from 'st' ({thief.state.traps})", thief.state.traps == 85)
thief.state.level, thief.state.max_hp = 30, 300
info = thief.partysync.my_info()
check(f"…and shares it with the party ({info})", "traps=85" in info)

# the leader's side
lead, lsent = make("Miserable")
g, b, w = lead.state, lead.bot, lead.world
trap_room = next(k for k, r in w.rooms.items() for e in r.exits.values() if e.kind == "trap")
d = next(dd for dd, e in w.room(trap_room).exits.items() if e.kind == "trap")
ex = w.room(trap_room).exits[d]
g.candidates = [trap_room]
g.party = {"Miserable": {}, "Sneaky": {}}
g.view = RoomView("x", {d}, [], [], ["Sneaky"], time.time())
lead.partysync.peers = {"Sneaky": {"t": time.time()}}
lead.partysync.command("Sneaky", "me " + info)
lead.partysync.members = lambda: ["Miserable", "Sneaky"]
b.x.leading = lambda: True
step = Step(d, 0, d, [], trap_room, ex.to)
lsent.clear()
waiting = b._disarm_gate(step, trap_room)
from mudpilot.automation import DIR_WORDS
word = DIR_WORDS.get(d, d).lower()
check(f"leader at a trap asks the disarmer ({lsent})", waiting and lsent == [f"/Sneaky @do disarm trap {word}"])
check("…and waits for the word", b._disarm_gate(step, trap_room))
# the disarmer gets it, does it, reports
tsent.clear()
thief.remote.c_do("Miserable", f"disarm trap {word}")
thief.bot._disarm_line("You successfully disarmed the trap.")
check(f"disarmer reports success ({tsent})", f"/Miserable {{trap {word} disarmed}}" in tsent)
b._disarm_line(f"Sneaky telepaths: {{trap {word} disarmed}}")
check("leader hears it and walks on", not b._disarm_gate(step, trap_room))
# nobody better at it: the leader's own setting decides, as before
b._disarm = None
g.view = RoomView("x", {d}, [], [], [], time.time())
lsent.clear()
check("no disarmer here and disarm traps off: walks on", not b._disarm_gate(step, trap_room) and not lsent)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
