"""MegaMUD Messages rules: parse, conditions, holds, wear-off, death-line review."""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
config.DATA_DIR = tempfile.mkdtemp()
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot import messagerules as MR
st = config.Settings(); st.save = lambda: None
s = Session(st); s._no_log_file = True
sent, closed = [], []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): closed.append(1); self.connected = False
s.telnet = Tel(); s._entered = True
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
m = s.msgrules
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
check(f"bundled MegaMUD messages loaded ({len(m.rules)} entries, {len(m.active)} that do something)",
      len(m.rules) > 800 and len(m.active) > 200)
feed("Your legs are entangled by a bola!")
check("bola → held", "held" in m.conditions and "held" in s.bot.x.ailments)
check("held → no walking", m.holding_walk())
m.conditions.pop("held", None); s.bot.x.ailments.pop("held", None)
wk = next((r for r in m.rules if r["name"].lower() == "weakness"), None)
if wk and wk.get("start"):
    m._fired.clear()
    feed(wk["start"].replace("{target}", "you"))
    check(f"'weakness' (the shipped file says can't move) doesn't stop the walk ({m.holding_walk()})",
          not m.holding_walk() and "held" not in s.bot.x.ailments)
    feed("You are held!")
    check("…unless the game then says you really can't move", "held" in s.bot.x.ailments or "held" not in m.conditions)
feed("You are blind")
check("blind → MudPilot's blind ailment", "blind" in s.bot.x.ailments)
feed("You can see again!")
check("'You can see again!' clears blind", "blind" not in m.conditions and "blind" not in s.bot.x.ailments)
feed("You have 2 lives left.")
check("the shipped file's personal hang-up rule doesn't hang you up", not closed)
# your own rule
own = MR.parse("desert damage:0000:5:drink water\nYou suffer in the desert heat...\n\nmy hang:0000:6:\nThe sky turns red\n")
m.rules = own; m.compile()
feed("You suffer in the desert heat...")
check(f"your rule's response goes out ({sent})", "drink water" in sent and time.time() < s.bot._no_rest_until)
feed("The sky turns red!")
check("your hang-up rule hangs up", closed)
check("template with wildcards", MR.to_regex("Acid sears {target} for {dmg} damage!", False).match("Acid sears orc for 12 damage!"))
# death line capture
s.telnet = Tel(); s.bot._cast_target = "glowing slime"
feed("The glowing slime bubbles and pops into a puddle of goo, dissolves!", "You gain 300 experience.")
check(f"unknown death line goes to review ({m.review})", m.review and "glowing slime" in m.review[-1]["line"])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
