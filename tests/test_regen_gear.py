"""Auto regen gear (Dan's level 55 mage, 2026-10-28): resting puts on the sparkling pendant, white gold ring and
runed cape from the pack (the faded shawl's −100 HP regen comes off), meditating the rainbow stone; the fighting
set goes back on after. Plus: a held keypad key sends one move, not thirty."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 55
st.auto_regen_gear = True; st.rest_until_hp = 90; st.rest_until_ma = 65
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g.carrying = ("25 runic coins, 415 gold crowns, golden headdress (Head), onyx earrings (Ears), phoenix feather (Neck), "
              "faded shawl (Back), shining metallic robes (Torso), ivory bracelet (Wrist), platinum ring (Finger), "
              "tarnished band (Finger), vortex staff (Weapon Hand), severed head of Goru-Nezar (Worn), magical quartz "
              "rod, sparkling pendant, white gold ring, 2 grey potion, rainbow stone, runed cape")
g.max_hp, g.hp, g.max_ma, g.ma = 830, 450, 519, 500
b._swap = None
b._begin_swap("rest")
check(f"rest (HP short): regen gear on ({sent})",
      "eq sparkling pendant" in sent and "eq white gold ring" in sent and "remove platinum ring" in sent
      and "eq runed cape" in sent)
check("…never the weapon or the worn quest head", not any("staff" in c or "head of" in c for c in sent))
sent.clear()
b.end_swap("done")
check(f"getting up: fighting set back ({sent})",
      "eq phoenix feather" in sent and "eq faded shawl" in sent and "eq platinum ring" in sent and "i" in sent)
sent.clear()
b._swap = None
g.hp, g.ma = 400, 40                         # HP and mana both low: a rest still goes for HP regen
b._swap = None; sent.clear(); b._begin_swap("rest")
check(f"rest with mana at 8% too: still the HP set, shawl off ({sent})", "eq runed cape" in sent)
b.end_swap(); sent.clear(); b._swap = None
g.hp, g.ma = 820, 200
b._begin_swap("med")
check(f"meditate: mana regen ({sent})", sent == ["eq rainbow stone"])
sent.clear(); b.end_swap()
check(f"…and back ({sent})", "eq phoenix feather" in sent)
# a gear change we didn't plan (post-rest line, you typing 'eq'): don't plan from the old inventory
b.note_line("You are now wearing faded shawl.")
sent.clear(); b._swap = None; b._begin_swap("rest")
check(f"stale inventory after a gear change → no swap from old data ({sent})", not any(c.startswith("eq") for c in sent))
# …the 'i' sent after the swap back clears it (it never did: 9 rests of ~310 s in the shawl, 2026-10-28)
b.note_line("You are carrying 25 runic coins, faded shawl (Back)")
check("inventory listing clears the stale flag", not b._inv_stale)
b.note_line("You are now wearing faded shawl.")
b.note_line("You are carrying too much to pick that up.")
check("…'you are carrying too much' doesn't", b._inv_stale)
b._inv_stale = False
st.auto_regen_gear = False
sent.clear(); b._swap = None; b._begin_swap("rest")
check("off: nothing swapped", not sent)
# keypad: one move per press (a held key's auto-repeat is ignored until it's let go)
from types import SimpleNamespace as NS
from mudpilot.app import App
moves = []
root = object()
widget = NS(winfo_toplevel=lambda: root)
fake = NS(root=root, entry=NS(get=lambda: ""), s=NS(settings=NS(keypad_macros=True), macros={"Keypad 4": "w^M"}),
          run_macro=lambda t: moves.append(t))
ev = NS(widget=widget, keysym="KP_4", keycode=100, state=0)
for _ in range(30):
    App._macro_key(fake, ev)
check(f"held keypad 4: one 'w' ({len(moves)})", len(moves) == 1)
App._key_up(fake, ev)
App._macro_key(fake, ev)
check("let go and press again: another", len(moves) == 2)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
