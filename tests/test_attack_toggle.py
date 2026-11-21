"""Evolution, 2026-11-01: re-sending the attack spell toggles '*Combat Off*' / '*Combat Engaged*'; taking that Combat Off
for the end of the fight sent the spell again (5 'swar's for one bat). And after a kill, no cast off the stale monster
list into an empty room ('Your spell has no effect in this room!')."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st)
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()
s.bot.send = lambda c: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
b = s.bot
b._cast_target, b._area_armed = "vampire bat", time.time()
b._last_spell_at = time.time()                 # we just sent our attack
b.note_line("*Combat Off*")
check("a Combat Off right after our own send is the toggle — the fight goes on", b._cast_target == "vampire bat")
b._last_spell_at = time.time() - 5
b.note_line("*Combat Off*")
check("a Combat Off on its own ends the fight as before", b._cast_target is None)
# after a kill: the monster list is stale until the room shows again
s.state.view = RoomView("Overgrown Forest Trail", {"S"}, [], [("vampire bat", {"name": "vampire bat"})], [],
                        time.time() - 1)
b.note_line("You gain 866 experience.")
sent.clear()
b.fight([("vampire bat", {"name": "vampire bat"})])
check(f"just killed: no cast off the old room list ({sent})", not sent)
# our own party walking in behind us is nothing new: no extra look before the next step (it held every step ~0.33 s)
g = s.state
g.party = {"Evolution": {}, "Buddy": {}, "Revolution": {}}
g.need_refresh = False
g.feed_line([("Buddy walks into the room from the north.", __import__("mudpilot.ansi", fromlist=["Style"]).Style())])
check("a party member walking in: no extra look", not g.need_refresh)
g.feed_line([("A small blood skeleton walks into the room from the west!", __import__("mudpilot.ansi", fromlist=["Style"]).Style())])
check("a monster walking in still gets a look", g.need_refresh)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
