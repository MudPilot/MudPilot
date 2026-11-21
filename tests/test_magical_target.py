"""Dan, 2026-10-30, the prismatic dragon's arena (Paradigm): Evolution (druid, level 20) cast vine strike and
stonestrike at the serpents and never touched the dragon — it's 'Magical 2' (MME ability 28): only single-target
spells of level 20+ hurt it, or any area spell; his blaze (level 20) would have. And MudPilot killed every serpent
before the dragon. Now: the biggest threat (most exp) first, and a spell that can hit it."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []


class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass


s.telnet = Tel(); s._entered = True
w, b, sb = s.world, s.bot, s.spellbook
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


drag = w.monster_names["prismatic dragon"]
serp = w.monster_names["green dragon serpent"]
vine, strk, blaz, swar = (sb.find(x) for x in ("vine", "strk", "blaz", "swar"))
check("the dragon is Magical 2", int(drag["abils"].get(28) or 0) == 2)
check("vine strike (level 1) can't hurt it", not sb.can_hit(drag, vine) and sb.useless(drag, vine))
check("stonestrike (level 8) can't either", not sb.can_hit(drag, strk))
check("blaze (level 20) can", sb.can_hit(drag, blaz))
check("swarm (level 12) can't: spell immunity 15 covers area spells too (2026-11-14)", not sb.can_hit(drag, swar))
check("vine is fine on a serpent", sb.can_hit(serp, vine))
mobs = [("green dragon serpent", serp), ("enormous prismatic dragon", drag), ("blue dragon serpent", serp)]
order = b.x.leader_target(list(mobs))
check(f"biggest threat first ({order[0][0]})", order[0][1] is drag)
st.target_biggest = False
check("…room order when switched off", b.x.leader_target(list(mobs))[0][1] is serp)
st.target_biggest = True
# Evolution's set-up: vine strike scripted, nothing automatic
st.auto_spells = False; st.auto_nuke = True; st.auto_combat = True
st.attack_spells = ["vine"]
st.char_level = 20; s.state.level = 20
s.state.known_spells = st.known_spells = ["vine", "star", "chao", "strk", "swar", "blaz"]
s.state.max_ma = s.state.ma = 500
b.x.may_cast_attack = lambda: True
sent.clear(); b._last_spell = None; b._cool.clear(); b._cast_sent_at = 0
b.fight([("enormous prismatic dragon", drag)])
casts = [c.split()[0] for c in sent if c.split()]
check(f"scripted vine can't hurt it → casts one that can ({sent})",
      casts and casts[0] in ("blaz", "swar") and "vine" not in casts)
sent.clear(); b._last_spell = None; b._cool.clear(); b._cast_sent_at = 0
b.fight([("green dragon serpent", serp)])
check(f"…and still vine on a serpent ({sent})", any(c.split()[0] == "vine" for c in sent if c.split()))
# Dan, 2026-11-01: Evolution vs the blood skeletons (Magical 3), mana nearly gone: cast the one that hits anyway
bs = w.monster_names["blood skeleton"]
st.known_spells = s.state.known_spells = ["vine", "strk", "swar"]
s.state.ma = 5
sent.clear(); b._last_spell = None; b._cool.clear(); b._cast_sent_at = 0
b.fight([("blood skeleton", bs)])
check(f"blood skeleton alone: nothing hurts it (spell immunity 20), no wasted cast ({sent})",
      not any(c.split()[0] == "swar" for c in sent if c.split()))
s.state.party = {"Evolution": {}, "Buddy": {}, "Revolution": {}}
from mudpilot.gamestate import RoomView      # (0.8.176: the AoE safety needs to know who's here — just the party)
s.state.view = RoomView("Tomb", set(), [("blood skeleton", bs)], [], ["Buddy", "Revolution"], time.time())
sent.clear(); b._last_spell = None; b._cool.clear(); b._cast_sent_at = 0
b.fight([("blood skeleton", bs)])
check(f"…in a party: swarm anyway, to be in the fight for the exp ({sent})", any(c.split()[0] == "swar" for c in sent if c.split()))
# your 0-mana swarm survives the game's spell list naming its real cost
from mudpilot.spells import apply_mana_overrides
apply_mana_overrides(w, {str(swar["Number"]): 0})
got = sb.resolve("swar", "swarm", int(swar["ReqLevel"]), int(swar["_mme_mana"]))
check(f"0-mana swarm still matches the game's 'swarm' line ({got and got['ManaCost']})", got is swar and got["ManaCost"] == 0)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
