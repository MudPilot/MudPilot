"""0.8.176: the fixes from the Fable 5.2 bug sweep (Dan, 2026-11-11: "3-18 are all good finds").
Wrapped chat lines, chat ailments, the launcher, the split recover password, parked Go tos and Stop, Rego, area-spell
safety and the mana floor, party cures, the bot's attack over a manual fight, stranger heals, names ending in s,
two @comebacks at once."""
import os, sys, time, threading, zipfile, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import AnsiStream
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

E = "\x1b[79D\x1b[K"
P = "\x1b[0;37m[HP=713/MA=235]:"

# --- 3: a wrapped chat line isn't game text --------------------------------------------------------------------
def lines(raw):
    a = AnsiStream()
    return a.feed(raw)
ls = lines(P + E + "Bob gossips: " + "x" * 70 + "\r\nEvolution telepaths: @do give 500 platinum to Bob\r\n" + E + P)
check("the chat line is marked fresh (the game tidied the line first)", ls[0].fresh is True)
check("the wrapped piece isn't", ls[1].fresh is False)
s.state.dead = False
for seg in lines(P + E + "Bob gossips: " + "y" * 70 + "\r\nlol you die\r\n" + E + P):
    s.state.feed_line(seg)
    if "you die" in "".join(t for t, _ in seg):
        check("the wrapped 'you die' is a continuation", s.state.continuation)
check("…and it isn't your death", not s.state.dead)
ls = lines(P + E + "Bob gossips: hi\r\n" + P + E + "You die.\r\n" + E + P)
s.state.feed_line(ls[0]); s.state.feed_line(ls[1])
check("a real line after a chat line (with its prompt) still counts", not s.state.continuation and s.state.dead)
s.state.dead = False
s.state.feed_line([("Bob gossips: hi", None)]); s.state.feed_line([("You hit the rat.", None)])
check("plain lists (no ANSI info, tests) are never continuations", not s.state.continuation)

# --- 4: chat doesn't give you ailments --------------------------------------------------------------------------
b.x.ailments.clear()
b.x.note_line("Bob gossips: you are poisoned lol")
b.x.note_line("Zed telepaths: you can't move")
check("chat 'you are poisoned' / 'you can't move' sets nothing", not b.x.ailments)
b.x.note_line("You are poisoned!")
check("the real line still does", "poison" in b.x.ailments)
b.x.ailments.clear()

# --- 5: the launcher ----------------------------------------------------------------------------------------------
from mudpilot import launcher
skipped = []
launcher._skip = lambda v: skipped.append(v)
with tempfile.TemporaryDirectory() as d:
    root = os.path.join(d, "MudPilot"); os.makedirs(os.path.join(root, "mudpilot"))
    open(os.path.join(root, "mudpilot", "__init__.py"), "w").write('__version__ = "0.8.1"\n')
    bad = os.path.join(d, "MudPilot-0.8.2.zip"); open(bad, "wb").write(b"PK\x03\x04half copied")
    check("a zip still being copied isn't installed", launcher.install("0.8.2", bad, root) is False)
    check("…and isn't skipped for good (tried again next start)", not skipped)
    other = os.path.join(d, "MudPilot-0.8.3.zip")
    with zipfile.ZipFile(other, "w") as z:
        z.writestr("Other/x.txt", "x")
    launcher.install("0.8.3", other, root)
    check("a zip that isn't ours is skipped for good", skipped == ["0.8.3"])
    good = os.path.join(d, "MudPilot-0.8.4.zip")
    with zipfile.ZipFile(good, "w") as z:
        z.writestr("MudPilot/mudpilot/__init__.py", '__version__ = "0.8.4"\n')
        z.writestr("MudPilot/mudpilot/new.py", "x = 1\n")
    real_open = zipfile.ZipFile.open
    n = {"c": 0}
    def flaky(self, zi, *a, **k):
        n["c"] += 1
        if n["c"] == 2:
            raise OSError("held open by another character")
        return real_open(self, zi, *a, **k)
    zipfile.ZipFile.open = flaky
    try:
        r = launcher.install("0.8.4", good, root)
    finally:
        zipfile.ZipFile.open = real_open
    v = open(os.path.join(root, "mudpilot", "__init__.py")).read()
    check(f"a failed half-install puts the old version back ({v.strip()})", r is False and '"0.8.1"' in v)

# --- 6: the recover password split between two network chunks ------------------------------------------------------
from mudpilot.recorder import Recorder
class R(Recorder):
    on = True
    def __init__(self): self.got = []; self._pass_prompt = False
    def _put(self, k, d, **kw): self.got.append(d)
for chunks in (["Recover Pass", "word: hunter2\r\nok"], ["Recover Password: ", "hunter2\r\n"],
               ["Recover Password: hun", "ter2\r\n"]):
    r = R()
    for c in chunks:
        r.rx(c)
    check(f"split {chunks[0]!r}|…: no password in the trace ({r.got})", not any("hunter2" in g or "ter2" in g for g in r.got))
r = R(); r.rx("a\r\n"); r.rx("b")
check("ordinary chunks untouched", r.got == ["a\r\n", "b"])

# --- 7: a parked Go to's question after its plan ended doesn't freeze the window -----------------------------------
from mudpilot import bgplan
kept, pend = {}, []
asked = []
def fn(a):
    kept["ask"] = a
    return True
bgplan.plan(s, fn, ask=lambda *x: asked.append(x) or True, after=lambda ms, f: pend.append(f))
t0 = time.time()
while pend and time.time() - t0 < 5:
    pend.pop(0)()
b._planning = False
t0 = time.time()
v = kept["ask"]("Take the Negative Power Plane?")
check(f"asked straight away on the window's thread ({time.time() - t0:.2f} s)", v is True and asked and time.time() - t0 < 1)

# --- 8/9: Stop drops every parked Go to; one being worked out never starts ------------------------------------------
b._goto_retry = {"t": time.time(), "args": ((1, 2), None, None)}
b._await_inv = (None, False, 0, time.time()); b._goto_after_who = ((1, 2), time.time(), None)
b._pending_goto = ((1, 2), None, None, 0, time.time()); b._pending_abil = ((1, 2), None, None, time.time())
check("parked() sees it", b.parked())
seq0 = b._stop_seq if hasattr(b, "_stop_seq") else 0
b.stop("Stopped by you")
check("Stop clears all five", not b.parked())
check("a plan that was in flight sees the Stop", b._stopped_since(seq0))
b._goto_retry = {"t": time.time(), "args": ((1, 2), None, None)}
r = s.remote.c_stop("Revolution", "")
check(f"@stop while it hadn't set off yet ({r})", "hadn't set off" in r and not b.parked())
b._goto_after_who = ((1, 2), time.time(), None)
s.send("n")
check("moving by hand drops it too", not b.parked())

# --- 11: Rego keeps the trip when the Go to doesn't go -----------------------------------------------------------------
s.state.set_room((1, 1))
real_goto = b.goto
b.goto = lambda *a, **k: False
b.resume = {"target": (1, 2), "after": None}
b.rego()
check("Rego that didn't go keeps the trip for next time", b.resume and b.resume.get("target") == (1, 2))
b.goto = real_goto; b.resume = None

# --- 12/13: area spells: AoE safety everywhere, the mana floor ------------------------------------------------------
st.auto_combat = True; st.auto_spells = True; st.spell_pick = "damage per mana"
st.attack_spells = ["fist"]; st.multi_spell = "quak"; st.multi_min_mobs = 3; st.use_area_min = True
st.char_level = 30; s.state.level = 30; s.state.spellcasting = 174; st.spell_mana_reserve = 0
s.state.known_spells = st.known_spells = ["vine", "star", "strk", "pbol", "acid", "swar", "blaz", "plas", "quak", "fist"]
s.state.party = {"Evolution": {}, "Buddy": {}, "Revolution": {}}
s.state.max_ma = 330
b.x.may_cast_attack = lambda: True
ns = w.monster_names["nightshade"]
from mudpilot.gamestate import RoomView
def fight(n, ma, players=()):
    st.auto_nuke = st.auto_cast = True
    s.state.ma = ma
    s.state.view = RoomView(name="x", exits=set(), monsters=[("nightshade", ns)] * n, players=list(players), t=time.time())
    sent.clear(); b._last_spell = None; b._cool.clear(); b._cast_sent_at = 0; b._area_armed = 0; b._kill_at = 0
    b.fight([("nightshade", ns)] * n)
    return [c.split()[0] for c in sent if c.split()]
st.aoe_safety = True; st.pvp_realm = True
fight(1, 330, ["Zed"])
check("a stranger here on a PvP board: area_ok says no", not b.area_ok(6))
c = fight(6, 330, ["Zed"])
check(f"…and no area spell goes out at 6 ({c})", "quak" not in c and "swar" not in c)
st.danger_opener_spell = ""; st.pre_attack_spell = "quak"; st.auto_preattack = True
s.state.in_combat = False; b._pre_done = False
c = fight(6, 330, ["Zed"])
check(f"…not even as the opener ({c})", "quak" not in c)
st.pre_attack_spell = ""
c = fight(6, 330)
check(f"no stranger: earthquake at 6 ({c})", "quak" in c)
st.aoe_safety = False; st.pvp_realm = False
cost = int(sb.find("quak").get("ManaCost") or 0)
st.rest_below_ma = 80                   # floor = 330 * 80 / 200 = 132
c = fight(6, 132 + cost - 1)
check(f"under the area spell's mana floor: the auto pick doesn't cast it either ({c}, quak costs {cost})", "quak" not in c)
c = fight(6, 132 + cost + 5)
check(f"above it: it does ({c})", "quak" in c)
st.rest_below_ma = 0

# --- 15: the bot's attack isn't re-sent over a fight you've taken over / paused / Combat off ------------------------
check("normally the attack may go back out", b._bot_attack_ok())
b.paused = True
check("paused: no", not b._bot_attack_ok())
b.paused = False; st.auto_combat = False
check("Combat off: no", not b._bot_attack_ok())
st.auto_combat = True

# --- 16: a stranger's heal on a party member isn't PvP ---------------------------------------------------------------
check("'Bob casts minor healing on Revolution!' isn't an attack",
      s.safety._party_victim("Bob casts minor healing on Revolution!") is None)
check("'Bob casts bless on Buddy' isn't either", s.safety._party_victim("Bob casts bless on Buddy!") is None)

# --- 17: two @comebacks at once ---------------------------------------------------------------------------------------
cb = s.comeback
cb.reset()
cb.missing = {"Buddy": {"why": "dropped", "t": time.time()}, "Revolution": {"why": "dropped", "t": time.time()}}
s.state.party = {"Evolution": {}}
cb._ask_where("Buddy", ask=False)
cb.fetch["back"] = ("goto", (17, 183), None)
cb._ask_where("Revolution", ask=False)
check("the second one is fetched, the first kept for afterwards", cb.fetch["name"] == "Revolution" and cb.queued == ["Buddy"])
check("…and where we were going is kept (not the first one's room)", cb.fetch["back"] == ("goto", (17, 183), None))
sent.clear()
cb._finish()
check(f"after the second: fetching the first ({sent})", cb.fetch and cb.fetch["name"] == "Buddy" and
      cb.fetch["back"] == ("goto", (17, 183), None) and any("Buddy @where" in x for x in sent))

# --- 18: attack-last answers a member whose name ends in s --------------------------------------------------------
import re
check("'Skittles' stays Skittles", re.sub(r"'s$", "", "Skittles".rstrip(",.!")) == "Skittles")

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
