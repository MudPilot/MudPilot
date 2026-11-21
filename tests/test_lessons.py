"""Lessons from pMUD's year of testing: refused moves, the party-follow banner, sneak banners,
quiet-line checks, and a clean slate after death."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style

def make():
    st = config.Settings(); st.save = lambda: None
    s = Session(st); s._no_log_file = True
    sent, closed = [], []
    class Tel:
        connected = True
        events = __import__("queue").Queue()
        def send_line(self, x): sent.append(x)
        def close(self): closed.append(1); self.connected = False
    s.telnet = Tel(); s._entered = True; s._want_connected = True
    return s, sent, closed

ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)

s, sent, closed = make()
w, st = s.world, s.state
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
# a room with a normal exit
k = next(k for k, r in w.rooms.items() if any(e.kind == "normal" for e in r.exits.values()) and w.is_room_name(r.name)
         and len(w.by_name.get(r.name.lower(), [])) == 1)
r = w.room(k)
d, ex = next((d, e) for d, e in r.exits.items() if e.kind == "normal")
st.candidates = [k]
st.note_command(d.lower())
feed("A strange power holds you back!")
check("'A strange power holds you back' = the move didn't happen", not st.pending and st.room == k)

# follower: the leader moved us
dest = w.room(ex.to)
st.candidates = [k]
from mudpilot.worlddb import DIR_WORDS
feed(f"-- Following your Party leader {DIR_WORDS[d]} --")
check("follow banner queues the move", st.pending and st.pending[-1][1] == d)
feed(dest.name, "Obvious exits: " + ", ".join(DIR_WORDS[x] for x in dest.exits if dest.exits[x].kind == "normal") or "none")
check(f"…and the next room shown is placed one step that way ({st.room} vs {ex.to})", st.room == ex.to)

# sneak: a compass move that arrives without 'Sneaking...' means sneak was lost
st.candidates = [k]; st.sneaking = True
st.note_command(d.lower())
feed(dest.name, "Obvious exits: " + ", ".join(DIR_WORDS[x] for x in dest.exits if dest.exits[x].kind == "normal"))
check("no 'Sneaking...' banner → not sneaking any more", not st.sneaking)
st.candidates = [k]; st.sneaking = True
st.note_command(d.lower())
feed("Sneaking...", dest.name, "Obvious exits: " + ", ".join(DIR_WORDS[x] for x in dest.exits if dest.exits[x].kind == "normal"))
check("banner seen → still sneaking", st.sneaking)
feed("Attempting to sneak...", "You don't think you're sneaking.")
check("'You don't think you're sneaking' → not sneaking", not st.sneaking)

# quiet line
s, sent, closed = make()
s.settings.auto_reconnect = True
s._connected_at = time.time() - 300; s._last_data_at = time.time() - 70
s._quiet_line_tick()
check("quiet for a minute → bare Enter sent", sent == [""])
s._probe_at = time.time() - 25
s._quiet_line_tick()
check("no answer in 20 s → line dropped to reconnect", closed)
s, sent, closed = make()
s.settings.auto_reconnect = True
s._entered = False; s._connected_at = time.time() - 60; s._last_data_at = time.time() - 50
s._quiet_line_tick()
check("stuck at the menu 45 s → reconnect", closed)

# death wipes the old plan
s, sent, closed = make()
b = s.bot
b.after_goto = "x"; b.detour = ["x"]; s._reinvite = ["Revolution"]
b.on_death()
check("death clears queued goto, detour and re-invite", b.after_goto is None and b.detour is None and not s._reinvite)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
