"""0.8.39: the pMUD sweep's tier 1 + 2 fixes and features."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView, ABIL_ROW_RE
from mudpilot.megamud_files import Step, MPath

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.pvp_realm = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
b, w, g = s.bot, s.world, s.state
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)

# --- menu idle: no reconnect while you're in the editor / browsing menus yourself
s._entered = False; s._left_at = time.time() - 100; s._connected_at = time.time() - 100; s._last_data_at = time.time() - 100
st.auto_reconnect = True; st.auto_enter_realm = True
s._quiet_line_tick()
check("in train stats 100 s: no reconnect", s.telnet.connected)
s._left_at = 0; s._user_sent_at = time.time() - 10
s._quiet_line_tick()
check("browsing the menus yourself: no reconnect", s.telnet.connected)
s._entered = True; s._left_at = 0

# --- abil table names with digits / punctuation
check("Conquest1(208) parses", ABIL_ROW_RE.match("Conquest1(208) 1"))
check("Damage(-MR)(17) parses", ABIL_ROW_RE.match("Damage(-MR)(17) 5"))

# --- spell learning keeps going after round 1
sp = next(v for v in w.spells.values() if (v.get("Short") or "").lower() == "dfir")
mon = w.monster_names["sandworm"]
sb = s.spellbook
sb.note_cast(mon, sp)
sb.feed_line("Your dragonfire burns the sandworm for 120 damage!")
sb._round_seen = 0
sb.feed_line("Your dragonfire burns the sandworm for 130 damage!")
sb._round_seen = 0
sb.feed_line("Your dragonfire burns the sandworm for 110 damage!")
check("rounds 2 and 3 of a repeating spell are learned too", len(sb.observed.get((mon["num"], sp["Number"]), [])) == 3)
sb.feed_line("*Combat Off*")
check("…and it stops at Combat Off", getattr(sb, "_active", None) is None)

# --- flux: a missing abil reply isn't 'not active'
bf = {"name": "flux", "cast": "flux", "ability": "145", "source": "spells", "op": ">=", "value": 100,
      "check_cmd": "abil 145", "enabled": True}
b._rule_checked[b._check_key(bf)] = time.time() - 5
g.abil_seen_at = time.time() - 60
need, why = b.buff_status(bf)
check("no reply to 'abil 145' yet → don't recast flux", not need)
g.abil_seen_at = time.time()
g.abil_rows[("worn", 145)] = (120, time.time())
need, why = b.buff_status(bf)
check("reply came back without a spells line → recast", need)

# --- one spell a round for heals too
b._last_spell_at = time.time()
check("heal waits for the next round", not b.slot_free())
b._last_spell_at = 0

# --- PvP: 'moves to attack you' — but not your partner's area spell
g.party = {"Miserable": {"hp": 100, "t": time.time()}, "Revolution": {"hp": 100, "t": time.time()}}
hung = []
s.safety.pvp_hangup = lambda why, victim=None: hung.append(why)
st.hangup_on_pvp = True
s.safety.feed_line("Revolution moves to attack everyone in the room!")
check("partner's area attack isn't PvP", not hung)
s.safety.feed_line("Vexx moves to attack you!")
check("'Vexx moves to attack you!' is PvP (before any damage)", hung)

# --- someone else healed Revolution: wait for a fresh par
b.note_line("Deacon casts cure critical wounds on Revolution!")
check("another healer's heal noted", time.time() - b._pheal_at.get("revolution", 0) < 2)

# --- death clears what you carried
g.carrying = "broadsword, rope and grapple"
b._death_at = 0; b.on_death()
check("death forgets your inventory", g.carrying == "")

# --- spell immunity
sc = w.monster_names["scarecrow"]
from mudpilot.spells import spell_blocked
low = next(v for v in w.spells.values() if int(v.get("ReqLevel") or 0) == 1 and (v.get("Short") or "") == "mmis") \
    if any((v.get("Short") or "") == "mmis" for v in w.spells.values()) else None
if low:
    check("Scarecrow (spell-immune below 20) ignores magic missile", spell_blocked(low, sc))

# --- stunned: hold everything
s.bot.x.ailments["stunned"] = time.time()
check("stunned", s.bot.x.stunned())
s.bot.x.note_line("You are no longer stunned.")
check("…and not any more", not s.bot.x.stunned())

# --- aid a partner who drops
sent.clear()
s.bot.x.note_line("Revolution drops to the ground!")
check("'aid Revolution' when he drops", "aid Revolution" in sent)

# --- party wait: mana too, and no stop-start
st.party_wait_pct, st.party_wait_until_pct, st.party_wait_ma_pct, st.party_wait_ma_until = 65, 90, 20, 60
b.walking = True; st.party_leader = "Miserable"
g.party["Revolution"].update(hp=100, ma=15, t=time.time())
check("waits for a partner at 15% mana", b.x.wait_for_party())
g.party["Revolution"].update(ma=40, t=time.time())
check("…still waiting at 40% (until 60%)", b.x.wait_for_party())
g.party["Revolution"].update(ma=70, t=time.time())
check("…goes at 70%", not b.x.wait_for_party())

# --- failed exits are routed round
a, z = (12, 335), (12, 1075)
r1 = w.route(a, z, level=47)
w.fail_edge(r1[0].to if False else a, r1[0].dir)
r2 = w.route(a, z, level=47)
check("a failed exit is routed round", r2 is None or r2[0].dir != r1[0].dir or r2[0].to != r1[0].to)
w.failed_edges.clear()

# --- search waits for the answer
g.view = RoomView("Hidden Glade", {"S"}, [], [], [], time.time())
sent.clear()
b._search_wait = None
waiting = b._search_gate(["search north"], "N", (1, 1))
check("search goes out first, the move waits", waiting and sent == ["search north"])
b._search_line("You found an exit to the north!")
check("found it → move", not b._search_gate(["search north"], "N", (1, 1)))

# --- look-alike rooms: the exit back to where we were decides
twins = w.by_name.get("rocky trail", [])[:6]
prev = [twins[0]]
back = [c for c in twins[1:] if any(ex.to == twins[0] for ex in w.rooms[c].exits.values())]
g.view = RoomView("Rocky Trail", set(), [], [], [], time.time())
if back:
    check("twin with the exit back to the last room wins", g._narrow(twins[1:], prev) == back)

# --- lair refill delay from MME
lb = s.loopbuilder
lair = next(k for k, r in w.rooms.items() if r.lair and r.delay >= 5)
check("MME lair delay read (5 min → 270 s refill)", lb.mme_refill(lair) == max(30, w.rooms[lair].delay * 60 - 30))


# --- bring the party through a command exit
sent.clear()
b.walking = True
st.party_leader = "Miserable"; st.party_teleport_bring = True
stp = Step("", 0, "dive sinkhole", [], (12, 1075), (12, 2224))
st.party_say_cmds = []
b._bring_party(stp, "dive sinkhole")
check("followers follow typed exits: no '@party' by default (it sent Revolution back out)",
      not any("@party" in x for x in sent))
st.party_say_cmds = ["dive sinkhole"]
b._bring_party(stp, "dive sinkhole")
check("…but one they didn't follow before gets '@party dive sinkhole' first", any(x.endswith("@party dive sinkhole") for x in sent))
g.candidates = [(12, 2224)]
g.view = RoomView(w.rooms[(12, 2224)].name, set(), [], [], [], time.time())
check("…then waits for Revolution on the far side", b._waiting_for_party_through(time.time()))
g.view = RoomView(w.rooms[(12, 2224)].name, set(), [], [], ["Revolution"], time.time())
check("…and carries on once he's there", not b._waiting_for_party_through(time.time()))

# --- weapon can't hurt it
b._melee_target = "ghost"
b.note_line("Your weapon has no effect against this monster.")
check("'weapon has no effect' remembered", "ghost" in b._melee_immune)

# --- woke up after sleep
s.telnet.connected = True
closed = []
s._on_closed = lambda why: closed.append(why)
s._last_poll = time.time() - 600
s.poll()
check("10 min gap (PC slept) → reconnect fresh", closed and "sleep" in closed[0])
s.telnet.connected = True

# --- light ahead, learned
st.auto_light, st.light_cmd = True, "lght"
b._too_dark = -200
dark = next(k for k, r in w.rooms.items() if r.light <= -250)
sent.clear(); b._lit_at = 0; b._cool["light"] = 0; g.in_combat = False
b._light_ahead(Step("", 0, "N", [], (1, 1), dark))
check("lights up before walking into a room as dark as one you couldn't see in", sent == ["lght"])

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
