"""0.8.55: 'You have a strange feeling that time is running out!' (pyramid level 1 is timed) → no rest, no @wait,
no stopping for small fights; back to normal once out of it."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 47
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
b, g = s.bot, s.state
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g.party = {"Miserable": {"hp": 100, "t": time.time()}, "Revolution": {"hp": 100, "t": time.time()}}
feed("[HP=684/MA=473]:Scorched Cavern, Firepit", "Obvious exits: south, west, up")
feed("[HP=684/MA=473]:u", "You have a strange feeling that time is running out!")
check("timer noticed (before the pyramid room shows)", b.hurrying())
feed("[HP=684/MA=473]:Great Pyramid", "Obvious exits: south, east, down")
check("…still on in the pyramid", b.hurrying())
s.remote.c_wait("Revolution", "")
check("@wait ignored", s.remote.holding() is None)
g.max_hp, g.hp = 684, 500
check("no resting at 73% HP", not b.should_rest([], False) or "Poison" in b.status)
wraith = {"name": "big wraith", "exp": 9000, "attack_data": {}}
check("even a worth-it mob is run past", b._eco_filter([("big wraith", wraith)]) == [])
g.hp = 300
check("…unless HP is low", len(b._eco_filter([("big wraith", wraith)])) == 1)
g.hp = 684
# Dan, 2026-11-04: "nobody is attacking in pyramid … that's true but only for the leader" — followers fight
b.x._following = "Buddy"
check("following: still timed, but fights what's on it", b.hurrying() and b._eco_filter([("big wraith", wraith)]) != [])
b.x._following = None
feed('Revolution says "@held"')
check("a held member still holds the walk (the one thing waited for)", "member down" in b.walk_holds())
feed('Revolution says "@ok"')
check("…released on his @ok", "member down" not in b.walk_holds())
# up to level 2, then level 3
for n, (frm, to) in enumerate([((12, 1920), (12, 1921)), ((12, 2001), (12, 2002))]):
    g.candidates = [frm]
    b._hurry.update(up_from=frm, up_at=time.time(), up_seq=g.view_seq)
    feed("[HP=684/MA=473]:Great Pyramid", "Obvious exits: north, south")
    g.candidates = [to]
    on = b.hurrying()
    check(f"after going up {n + 1}: {'still timed (level 2)' if n == 0 else 'level 3 — normal'}", on == (n == 0))
b._hurry = {"until": time.time() + 600, "area": "great pyramid", "up_from": None, "ups": 0, "seen": True}
feed("[HP=684/MA=473]:Rugged Shoreline", "Obvious exits: north, south")
check("out of the pyramid → normal again", not b.hurrying())
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
