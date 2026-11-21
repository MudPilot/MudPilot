"""0.8.201 item charges: wands count down and die, per-day items refill at cleanup, unlimited items never count,
an item that's out isn't used again (itemcharges.py)."""
import os, sys, time, shutil, tempfile
_tmp = tempfile.mkdtemp()
os.environ["MUDPILOT_DATA_DIR"] = os.path.join(_tmp, "data")      # never the real data folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.itemcharges import ItemCharges, last_cleanup, PROBE_SECS
db = os.path.join(_tmp, "world.db")
shutil.copy2(os.path.join(config.BUNDLED_DIR, "Paradigm.db"), db)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.board = "Paradigm"
st.auto_combat = False; st.auto_rest = False; st.auto_bless = False; st.auto_spells = False
s = Session(st, world_path=db); s._no_log_file = True
sent, logs = [], []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
s.log = lambda m, *a, **k: logs.append(m)
path = os.path.join(_tmp, "charges.json")
ic = s.itemcharges = ItemCharges(s, path=path)
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
def settle():
    if ic.pending:
        ic.pending["t"] -= 10
    ic.tick()

check("default on, no cleanup time", config.Settings().item_charges_on and config.Settings().cleanup_time == "")
check("crozier is unlimited (not counted)", ic.meta("emerald-tipped crozier") is None)
check(f"teak wand: 10 charges, finite ({ic.meta('teak wand')})", ic.meta("teak wand") == (10, False))
check(f"skull wand: 3 a day ({ic.meta('skull wand')})", ic.meta("skull wand") == (3, True))
check("a one-shot scroll isn't tracked", ic.meta("scroll of stoneskin") is None)
check("unknown item isn't tracked", ic.meta("glowing frobnicator") is None)

s.state.carrying = "teak wand, skull wand, emerald-tipped crozier (Weapon Hand), torch"
check("'use teak wand orc' names the teak wand", ic.match_item("teak wand orc") == "teak wand")
check("'use teak orc' too", ic.match_item("teak orc") == "teak wand")
check("'use crozier' → not a charged item", ic.match_item("emerald-tipped crozier") is None)

# ---- counting
s.send("use teak wand orc", from_bot=True)
check("use goes out and waits", sent[-1] == "use teak wand orc" and ic.pending)
settle()
check(f"counted: 9 left ({ic.left('teak wand')})", ic.left("teak wand") == 9)
s.send("use teak wand orc", from_bot=True)
s.itemcharges.feed_line("You don't have that equipped!")
settle()
check(f"turned away → no charge spent ({ic.left('teak wand')})", ic.left("teak wand") == 9)
s.send("use teak wand", from_bot=True)
s.send("use teak wand", from_bot=True)          # back to back: the first is counted when the second goes
settle()
check(f"two more → 7 ({ic.left('teak wand')})", ic.left("teak wand") == 7)
s.send("look teak wand")
ic.feed_line("Uses remaining: 2")
check(f"the game's count wins ({ic.left('teak wand')})", ic.left("teak wand") == 2)
logs.clear()
s.send("use teak wand", from_bot=True); settle()
check(f"1 left, said ({logs})", ic.left("teak wand") == 1 and any("1/10 left" in l for l in logs))
s.send("use teak wand", from_bot=True)
ic.feed_line("Nothing happens.")
check(f"'Nothing happens.' right after → out ({ic.left('teak wand')})", ic.is_out("teak wand"))

# ---- out: automatic uses held, yours go out
sent.clear(); logs.clear()
s.send("use teak wand orc", from_bot=True)
s.send("use teak wand orc", from_bot=True)
check(f"automatic use held ({sent})", not sent)
check(f"said once ({logs})", sum("Not using the teak wand" in l for l in logs) == 1)
s.send("use teak wand orc")
check("typed by you → goes out", sent == ["use teak wand orc"])
ic.pending = None
# one probe every half hour
ic._probe["teak wand"] = time.time() - PROBE_SECS - 1
ic._book()["teak wand"]["out"] = time.time() - PROBE_SECS - 1
sent.clear()
s.send("use teak wand", from_bot=True)
check(f"half an hour on → one try ({sent})", sent == ["use teak wand"])
s.send("use teak wand", from_bot=True)
check("…then held again", sent == ["use teak wand"])
ic.pending = None
ic.feed_line("The teak wand crumbles to dust!")
check("crumbled → forgotten", "teak wand" not in ic._book())

# ---- per day: refills at cleanup
ic._set("skull wand", 0)
check("skull wand out", ic.is_out("skull wand"))
st.cleanup_time = ""
ic._book()["skull wand"]["out"] = time.time() - 25 * 3600
ic._book()["skull wand"]["t"] = time.time() - 25 * 3600
check(f"no cleanup time: 24 h later it's back ({ic.left('skull wand')})", ic.left("skull wand") == 3)
ic._set("skull wand", 0)
now = time.time()
lt = time.localtime(now - 60)
st.cleanup_time = f"{lt.tm_hour:02d}:{lt.tm_min:02d}"
check("last cleanup a minute ago", abs(last_cleanup(now, st.cleanup_time) - (now - 60)) < 61)
ic._book()["skull wand"]["t"] = now - 3600
check(f"cleanup passed since it ran out → refilled ({ic.left('skull wand')})", ic.left("skull wand") == 3)
ic._set("skull wand", 0)
check("ran out after the cleanup → stays out", ic.is_out("skull wand"))
st.cleanup_time = ""

# ---- unlimited: never counted, never held
sent.clear()
for _ in range(5):
    s.send("use emerald-tipped crozier", from_bot=True)
settle()
check("crozier never counted", "emerald-tipped crozier" not in ic._book())
check(f"crozier never held ({len(sent)})", len(sent) == 5)

# ---- kept between runs, per character; summary
ic2 = ItemCharges(s, path=path)
check(f"saved ({ic2._book()})", ic2._book().get("skull wand", {}).get("left") == 0)
s.state.carrying = "skull wand, pine wand"
sm = ic.summary()
check(f"summary ({sm})", "skull wand 0/3 today" in sm and any("pine wand (10 charges" in x for x in sm))
logs.clear(); s.state.inv_seq += 1; ic.tick()
check(f"summary logged on an inventory read ({logs})", any(l.startswith("Charged items you carry") for l in logs))
st.item_charges_on = False
sent.clear()
s.send("use skull wand", from_bot=True)
check("switched off → nothing held", sent == ["use skull wand"])

shutil.rmtree(_tmp, ignore_errors=True)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
