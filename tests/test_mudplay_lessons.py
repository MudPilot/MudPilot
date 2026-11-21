"""0.8.200: MajorMUD facts from another client's bug history (MudPlay's CHANGELOG / GAME_MECHANICS), checked against
ours and fixed before players hit them."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.ansi import AnsiStream, plain
from mudpilot.gamestate import PARTY_ROW_RE, PROMPT_RE, MOVE_FAIL_RE, GATE_REFUSE_RE
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

# 1. Kai classes in 'par'
m = PARTY_ROW_RE.match("  Phrixas Zen      (Mystic)   [K: 40%] [H: 88%]  - Frontrank")
check(f"a Mystic with kai is a party member ({m and m.groups()})", m and m.group(1) == "Phrixas" and m.group(4) == "88")
m = PARTY_ROW_RE.match("  Miserable Par   (Mage)   [M: 69%] [H: 96%]M - Frontrank")
check("a mage row still reads its mana", m and m.group(3) == "69")

# 2. Stock's backspace inside direction words
a = AnsiStream()
lines = a.feed("Obvious exits: nQ\x08orth, sZ\x08outh\r\n")
txt = " ".join(plain(l) for l in lines)
check(f"backspaces applied: {txt!r}", "north, south" in txt and "nQ" not in txt)

# 5. a resting class with no mana
m = PROMPT_RE.match("[HP=91 (Resting) ]:")
check(f"'[HP=91 (Resting) ]:' read ({m and m.group(1)})", m and m.group(1) == "91" and (m.group("rin") or "").startswith("(Rest"))

# 4. refusals
for t in ("You are too heavy to move", "You can't seem to move anywhere!", "You are flat on your back!",
          "There is a closed door in that direction!", "The portal is shut!", "You may not go through this exit!"):
    check(f"move refusal: {t}", MOVE_FAIL_RE.search(t))
check("a toll short of money is a gate", GATE_REFUSE_RE.search("You do not have enough to cover the toll."))

st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st); s._no_log_file = True
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True
b, g = s.bot, s.state
b.send = lambda c, late_ok=False: sent.append(c)
alerts = []
s.on_alert = alerts.append

# 6. martial arts
b._melee_target = "iron golem"
b.note_line("Your fists have no effect against this monster!")
check("fists 'no effect' → won't punch it", "iron golem" in getattr(b, "_melee_immune", set()))

# 3. 'Your command had no effect.' after an attack isn't the path's
class P: title = "Loop"
b.walking, b.path = True, P()
b._step_sent_at = time.time()
b._macro_at = 0
called = []
b.locate_now = lambda why: called.append(why) or True
b._drop_bad_learned = lambda: None
b._last_cmd = ("a kobold", True)
b.note_line("Your command had no effect.")
check(f"after an attack: not 'wrong room' ({called})", not called)
b._last_cmd = ("go hole", False)
b.note_line("Your command had no effect.")
check(f"after the path's 'go hole': checks where we are ({called})", called)

# 4. the same gate twice → stop with the game's reason
stopped = []
b.stop = lambda why="": stopped.append(why)
s.notify.send = lambda *a, **k: None
g.candidates = [(3, 100)]
for _ in range(2):
    g.pending.append(("move", "n", [(3, 100)]))
    g.feed_text = None
    g._move_failed("Your current alignment prevents you from entering this exit.")
    b.note_line("Your current alignment prevents you from entering this exit.")
check(f"alignment gate twice: stopped, saying why ({stopped})", stopped and "alignment" in stopped[0])

# 7. too sick to rest: no rest spam
b.note_line("You are too sick to rest!")
check("too sick: rest held off", time.time() < getattr(b, "_sick_rest_until", 0))
g.ma, g.max_ma = 300, 450
b.note_line("Meditation will not help at this time.")
check(f"meditation won't help: mana counts as full ({g.max_ma})", g.max_ma == 300)

# 8. telepath not delivered → sent again once
s._last_tp = ("/Revolution @ok", time.time())
b.note_line("--- Telepath Not Sent ---")
check("telepath queued to resend", getattr(b, "_tp_resend", None) and b._tp_resend[0] == "/Revolution @ok")

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
