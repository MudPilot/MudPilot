"""0.8.31: low-HP hang-up once, re-invite the party, spell efficiency, one move at a time."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style

def make(**kw):
    st = config.Settings(); st.save = lambda: None
    for k, v in kw.items(): setattr(st, k, v)
    s = Session(st)
    s._no_log_file = True
    sent, closed = [], []
    class FakeTel:
        connected = True
        events = __import__("queue").Queue()
        def send_line(self, x): sent.append(x)
        def close(self): closed.append(1); self.connected = False
    s.telnet = FakeTel(); s._want_connected = True; s._entered = True
    feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
    return s, sent, closed, feed

ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)

# 1. low HP hangs up once; back in still low → no second hang-up; recovers → re-armed
s, sent, closed, feed = make(hangup_low_hp=True, hangup_hp_pct=25, relog_instead_of_hang=True)
s.settings.my_name = "Dan"
s.state.party = {"Dan": {}, "Revolution": {}}
s.bot.x._own_party = True
s.state.hp, s.state.max_hp = 500, 1000
s.state.last_prompt = time.time() + 1           # an HP prompt has come in since connecting (0.8.139 waits for one)
s.safety.tick()
check("no hang-up at 50%", not closed)
s.state.hp = 200
s.safety.tick()
check("hang-up at 20%", len(closed) == 1)
check("party remembered", s._reinvite == ["Revolution"])
# back in, still at 20%
s.telnet.connected = False
s.safety.tick()
s.telnet.connected = True
s._back_in()
s.safety.tick(); s.safety.tick()
check("no second hang-up when coming back in low", len(closed) == 1)
s.state.hp = 190
s.safety.tick()
check("small further drop: still no hang-up", len(closed) == 1)
# re-invite fires after the settle delay
s._reinvite_at = time.time() - 1
s._reinvite_tick()
check("re-invites Revolution", "invite Revolution" in sent)
s.state.hp = 300
s.safety.tick()
check("re-armed once over the line", s.safety._hp_armed)
s.state.hp = 100
s.safety.tick()
check("hangs up again after re-arming", len(closed) == 2)
# falling hard while disarmed still hangs up
s.telnet.connected = False; s.safety.tick(); s.telnet.connected = True
s.state.hp = 200; s.safety.tick()
s.state.hp = 50; s.safety.tick()
check("still-falling HP hangs up even while disarmed", len(closed) == 3)

# 2. following someone else: nothing to re-invite
s, sent, closed, feed = make()
s.settings.my_name = "Dan"
s.state.party = {"Dan": {}, "Revolution": {}}
s.bot.x._own_party = False; s.bot.x._following = "Revolution"
s.remember_party()
check("follower doesn't re-invite the leader", s._reinvite == [])

# 3. spell efficiency
s, sent, closed, feed = make()
s.settings.my_name = "Dan"
s.state.party = {"Dan": {}, "Revolution": {}}
t = s.spelltune
for _ in range(6):
    t.record("cave bear", 4.0, 0.95, 40)
check("starts trial on a weaker spell when doing all the damage", t.level("cave bear") == 1)
for _ in range(6):
    t.record("cave bear", 4.3, 0.9, 20)
check("keeps the weaker spell: nearly as fast, half the mana", t.level("cave bear") == 1
      and t.mons["cave bear"]["trial"] is None)
for _ in range(6):
    t.record("cave bear", 4.4, 0.9, 20)
check("tries weaker again", t.level("cave bear") == 2)
for _ in range(6):
    t.record("cave bear", 9.0, 0.8, 10)
check("too slow → back to the stronger one", t.level("cave bear") == 1)
check("…and that weaker one is locked", t.mons["cave bear"]["locked"].get((t.me(), 2), 0) > time.time())
for _ in range(6):
    t.record("orc", 6.0, 0.5, 40)
check("party pulling its weight: stays on the hardest spell", t.level("orc") == 0)
s.state.party = {"Dan": {}}
check("party change resets to the hardest spell", t.level("cave bear") == 0)
s.settings.spell_efficiency = False
check("switch off → always hardest", t.level("cave bear") == 0)

# damage-share parsing
s, sent, closed, feed = make()
s.state.party = {"Dan": {}, "Revolution": {}}
s.bot._last_spell = 7; s.bot._cast_target = "Cave Bear"
feed("Your magma blast hits the cave bear for 80 damage!", "Revolution slashes the cave bear for 20 damage!",
     "The cave bear claws you for 15 damage!")
f = s.spelltune._fight
check("share parsed (mine 80, party 20, monster hit ignored)", f and f["dmg"] == {s.spelltune.me(): 80, "revolution": 20})

# 4. dial back picks the next weaker spell from the ladder (with mana costs: since 0.8.150-ish it only steps down
#    when the weaker spell really kills for less mana)
s, sent, closed, feed = make()
calls = []
def fake_pick(excl=()):
    ladder = [({"Number": 1, "Name": "MAGM", "ManaCost": 30}, 100, 1, "single", ""), ({"Number": 2, "Name": "DFIR", "ManaCost": 10}, 60, 1, "single", ""),
              ({"Number": 3, "Name": "FBOL", "ManaCost": 5}, 30, 1, "single", "")]
    return next((x for x in ladder if x[0]["Number"] not in excl), None)
s.spelltune.mons["cave bear"] = {"lv": {s.spelltune.me(): 1}, "trial": None, "base": None, "recs": [], "locked": {},
                                 "n": {}, "snap": {}}
s.spelltune._party_key = tuple()
got = s.bot._dial_back(fake_pick(), {"name": "Cave Bear"}, None, "damage", fake_pick)
check("level 1 → dfir instead of magm", got[0]["Name"] == "DFIR")
got = s.bot._dial_back(fake_pick(), {"name": "Cave Bear", "boss": 1}, None, "damage", fake_pick)
check("boss → hardest", got[0]["Name"] == "MAGM")
got = s.bot._dial_back(fake_pick(), {"name": "Cave Bear"}, "a boss", "damage", fake_pick)
check("dangerous → hardest", got[0]["Name"] == "MAGM")

# 5. one move at a time: no new move until the room answers (or the step timeout)
s, sent, closed, feed = make()
b = s.bot
b._expect_move(); b._step_sent_at = time.time()
check("waiting for the room", b._awaiting_move(time.time()))
s.state.view_seq += 1
check("room answered → free to move", not b._awaiting_move(time.time()))
b._expect_move(); b._step_sent_at = time.time() - 30
check("gives up waiting after the step timeout", not b._awaiting_move(time.time()))
b._expect_move(); b._step_sent_at = time.time(); s.state.move_failed += 1
check("'can't go that way' → free to move", not b._awaiting_move(time.time()))

# 6. PvP on the party
def pvp_setup(**kw):
    s, sent, closed, feed = make(**kw)
    s.settings.my_name = "Dan"; s.settings.pvp_realm = True
    s.state.party = {"Dan": {}, "Revolution": {}}
    s.state.hp, s.state.max_hp = 900, 1000
    return s, sent, closed, feed
s, sent, closed, feed = pvp_setup()
feed("Bob backstabs Revolution for 400 damage!")
check("party attacked: not hung up on the same line (waits a moment)", not closed and s.safety._pvp_hang)
check("…but the hang-up lands before the next round", s.safety._pvp_hang["hard"] - time.time() <= 4.0)
s.safety._pvp_hang["at"] = time.time() - 0.01; s.safety.tick()
check("party attacked by a player → hangs up", closed)
s, sent, closed, feed = pvp_setup()
feed("Bob backstabs Revolution for 400 damage!", "Revolution falls to the ground, dead.")
check("party member killed → grabs his stuff first", "get all" in sent and not closed)
ph = s.safety._pvp_hang
check("…and still hangs up before the next round", ph and ph["at"] <= ph["hard"])
ph["at"] = time.time() - 0.01; s.safety.tick()
check("…then hangs up", closed)
s, sent, closed, feed = pvp_setup()
feed("Bob swings at you with his longsword!")
check("attacked myself → hangs up at once", closed)
s, sent, closed, feed = pvp_setup()
feed("The orc slashes Revolution for 20 damage!")
check("a monster hitting the party isn't PvP", not closed and not s.safety._pvp_hang)
s, sent, closed, feed = pvp_setup()
s.remote_players = None
r = s.remote.c_pvp("Revolution", "on")
check("@pvp on turns PvP hang-up off, defend + fight back on", not s.settings.hangup_on_pvp and s.settings.defend_party_pvp
      and s.settings.pvp_auto_fight and "on" in r)
feed("Bob backstabs Revolution for 400 damage!")
check("@pvp on: no hang-up when the party is attacked", not closed and not s.safety._pvp_hang)
s.state.last_prompt = time.time() + 1           # (an HP prompt since connecting)
s.safety.tick(); s.state.hp = 100; s.safety.tick()
check("@pvp on: still hangs up under the HP line", closed)
s.remote.c_pvp("Revolution", "off")
check("@pvp off turns the hang-up back on", s.settings.hangup_on_pvp)

# floor: never down to a toy spell
s, sent, closed, feed = make()
def toy_pick(excl=()):
    ladder = [({"Number": 1, "Name": "MAGM", "ManaCost": 30}, 500, 1, "single", ""), ({"Number": 2, "Name": "DFIR", "ManaCost": 10}, 290, 1, "single", ""),
              ({"Number": 3, "Name": "MMIS", "ManaCost": 2}, 20, 1, "single", "")]
    return next((x for x in ladder if x[0]["Number"] not in excl), None)
s.spelltune.mons["nightshade"] = {"lv": {s.spelltune.me(): 2}, "trial": None, "base": None, "recs": [], "locked": {},
                                  "n": {}, "snap": {}}
s.spelltune._party_key = tuple()
got = s.bot._dial_back(toy_pick(), {"name": "small nightshade"}, None, "damage", toy_pick)
check(f"never steps down to magic missile ({got[0]['Name']})", got[0]["Name"] == "DFIR")

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
