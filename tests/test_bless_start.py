"""Revolution, 2026-10-30: nity (serenity) recast every 15 s. Its start line had been learned as "Dark Corridor" (the
room name), so 'st' — "You feel calm and serene. (228s)" — never showed it up. The Messages file's start line fixes a
learned one, and a room name is never learned."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
st.buffs = [{"name": "nity", "op": ">=", "value": 0, "enabled": True, "cast": "nity", "every": 0,
             "off_msg": "The feeling of serenity fades away.", "off_msg_learned": True,
             "on_msg": "Dark Corridor", "on_msg_learned": True},
            {"name": "aura", "op": ">=", "value": 0, "enabled": True, "cast": "aura", "every": 0,
             "on_msg": "You feel safe from evil!", "on_msg_learned": True}]
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
b, g, x = s.bot, s.state, s.bot.x
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


x.fix_bless_messages()
nity = st.buffs[0]
check(f"nity's start line from the Messages file ({nity.get('on_msg')!r})", nity.get("on_msg") == "You feel calm and serene.")
check("aura's (already right) is left alone", st.buffs[1]["on_msg"] == "You feel safe from evil!")

# learning: the room name after a cast is not a start line
nity["on_msg"] = ""
g.view = RoomView("Dark Corridor", {"N"}, [], [], [], time.time())
for _ in range(2):
    x.note_cast_buff("nity")
    x._last_cast_buff = ("nity", time.time(), True)
    x.note_line("Dark Corridor")
check(f"a room name isn't learned ({nity.get('on_msg')!r})", not nity.get("on_msg"))
for _ in range(2):
    x._last_cast_buff = ("nity", time.time(), True)
    x.note_line("You feel calm and serene.")
check(f"…the real line is ({nity.get('on_msg')!r})", nity.get("on_msg") == "You feel calm and serene.")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
