"""Dan, 2026-11-15: Miserable (mage) loops Stonecaps with a stash room. A runed stone cudgel was too heavy for him, so
Revolution picked it up, and it never reached the stash: Revolution has no stash room of his own.
- Game Data → Items: an item can be ticked Auto-stash ('runed stone cudgel: get, stash').
- '/Revolution @stash' in the stash room: Revolution remembers it and hides his Auto-stash items there each pass —
  only those (no coins, no ears).
- Miserable, in his stash room, asks a member to hide Auto-stash items they picked up for him."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.gamestate import RoomView
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

def make(name):
    st = config.Settings(); st.save = lambda: None; st.my_name = name
    s = Session(st); s._no_log_file = True
    sent = []
    s.bot.send = sent.append
    s.bot.x.send = sent.append
    s.state.party = {"Miserable": {"hp": 100, "t": time.time()}, "Revolution": {"hp": 100, "t": time.time()}}
    s.state.in_combat = False
    s.bot.walking = True                 # (0.8.201: the stash room only stashes while looping / walking)
    return s, st, sent

# --- Miserable: his stash room, cudgels ticked Auto-stash, an ear not
s, st, sent = make("Miserable")
b, g, x = s.bot, s.state, s.bot.x
st.stash_room, st.stash_looted, st.stash_coins = "14/6534", False, []
st.item_rules = ["runed stone cudgel: get, stash", "kobold ear: get"]
check(f"Auto-stash rule read ({x.stash_flagged_names()}, {b.item_rule('runed stone cudgel')})",
      x.stash_flagged_names() == ["runed stone cudgel"] and b.item_rule("runed stone cudgel").get("get"))
g.candidates = [(14, 6545)]
b._grab_asked = {((14, 6545), "runed stone cudgel"): {"t0": time.time(), "t": time.time(), "who": {"revolution"}},
                 ((14, 6545), "kobold ear"): {"t0": time.time(), "t": time.time(), "who": {"revolution"}}}
x.note_line("Revolution picks up runed stone cudgel.")
x.note_line("Revolution picks up runed stone cudgel.")
x.note_line("Revolution picks up kobold ear.")                    # asked for, but not Auto-stash
check(f"counted 2 cudgels held for us, no ear ({x.held_for_me})", x.held_for_me == {"Revolution": {"runed stone cudgel": 2}})
g.candidates = [(14, 6534)]
g.view = RoomView("Bristlewood Grove", {"E"}, players=["Revolution"])
x.stash_tick()
check(f"asked Revolution to hide both ({sent})",
      "/Revolution @do hide runed stone cudgel^Mhide runed stone cudgel" in sent)
check("…and only once", x.held_for_me == {})
g.carrying = "runed stone cudgel, kobold ear, 12 gold crowns"
check(f"his own stash: the cudgel, not the ear ({x.to_stash()})", x.to_stash() == [(1, "runed stone cudgel")])

# --- Revolution: no stash room of his own; Dan tells him '@stash' in Miserable's stash room
s, st, sent = make("Revolution")
b, g, x = s.bot, s.state, s.bot.x
st.stash_coins = ["gold crown"]
st.stash_looted = True
st.item_rules = ["runed stone cudgel: get, stash"]
g.candidates = [(14, 6534)]
r = s.remote.c_stash("Miserable", "")
check(f"@stash remembered the room ({st.party_stash_room!r}, reply {r!r})", st.party_stash_room == "14/6534")
g.carrying = "runed stone cudgel, 2 kobold ears, 40 gold crowns"
g.coins = {"gold crown": 40}
x.looted.update({"kobold ear", "runed stone cudgel"})
b._cool.clear() if hasattr(b, "_cool") else None
x.stash_tick()
hides = [c for c in sent if c.startswith("hide")]
check(f"hid the cudgel only — no coins, no ears ({hides})", hides == ["hide runed stone cudgel"])
g.candidates = [(14, 6545)]
sent.clear()
x.stash_tick()
check(f"nothing hidden elsewhere ({sent})", not [c for c in sent if c.startswith("hide")])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
