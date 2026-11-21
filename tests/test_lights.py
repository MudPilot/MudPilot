"""0.8.200 auto-light with carried lights (lights.py, from the MudPlay review): which rooms need light (MME Light +
worn Illumination, see at −150), which light to ready (the weakest strong enough), 'use' + a bare Enter, 'rem' where
it's light enough, relight on the burn-out lines, a stale belief on the dark line, and buying at the end of a lap
(with back-off after a failed buy). Off by default."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.gamestate import RoomView
from mudpilot.session import Session
from mudpilot import lights as L
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

st = config.Settings(); st.save = lambda: None; st.board = "Paradigm"
check("off by default", st.auto_light_items is False)
s = Session(st); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
b, w, g = s.bot, s.world, s.state
b.send = sent.append
A = b.lights
g.in_combat = False

def room_with(light):
    return next(k for k, r in w.rooms.items() if int(r.light or 0) == light and r.exits)
lit0, dark200, dark325 = room_with(0), room_with(-200), room_with(-325)

# --- off: nothing happens
class Step:
    def __init__(self, dest): self.dest = dest; self.dir = "N"; self.pre = []
g.carrying = "2 torches, lantern, leather armour (Worn)"
check("setting off: no light readied", not A.before_step(Step(dark200)) and not sent)
st.auto_light_items = True

# --- what we know
cat = {v["name"]: v for v in L.catalogue(w).values()}
check(f"lights from MME: torch 100, lantern 175 ({cat['torch']['strength']}, {cat['lantern']['strength']})",
      cat["torch"]["strength"] == 100 and cat["lantern"]["strength"] == 175)
check(f"burn time from UseCount: torch ~40 min ({cat['torch']['burn_h']:.2f} h)", abs(cat["torch"]["burn_h"] - 0.667) < 0.01)
cs = L.parse_carried("2 torches, lantern (Readied/80), leather armour (Worn)", A.by_name())
check(f"pack parsed: 2 torches, a readied lantern with 80 left ({cs})",
      [(c["name"], c["qty"], c["readied"], c["left"]) for c in cs] == [("torch", 2, False, None), ("lantern", 1, True, 80)])
check(f"room needs: 0 → none, −200 → 50, −325 → 175 ({A.need(lit0)}, {A.need(dark200)}, {A.need(dark325)})",
      (A.need(lit0), A.need(dark200), A.need(dark325)) == (0, 50, 175))
check("weakest strong-enough light: torch for −200", A.pick(50)["name"] == "torch")
check("lantern for −325", A.pick(175)["name"] == "lantern")

# --- readying before a dark room
g.candidates = [lit0]
check("dark ahead: hold the step and light up", A.before_step(Step(dark200)) and sent[-1] == "use torch")
n = len(sent)
check("one 'use' at a time (latch)", A.before_step(Step(dark200)) and len(sent) == n)
A.note_line("You lit the torch.")
check(f"lit → a bare Enter to see the room ({sent[-1]!r})", A.lit == "torch" and sent[-1] == "")
check("lit and strong enough: walk on", not A.before_step(Step(dark200)))
sent.clear()
check("darker room ahead: the torch is too weak → rem it, use the lantern",
      A.before_step(Step(dark325)) and sent == ["rem torch", "use lantern"])
A.note_line("[HP=50/MA=10]:You have removed torch and extinguished it.")
A.note_line("You lit the lantern.")
check("now the lantern", A.lit == "lantern")

# --- put away where it's light enough (not straight after lighting, not with dark rooms just ahead)
class MP:
    title = "Loop"; steps = [Step(lit0), Step(lit0), Step(lit0)]
b.walking, b.path, b.idx, b.loop = True, MP(), 0, True
g.view = RoomView("Somewhere", {"N"}); g.view_seq += 1; g.candidates = [lit0]
sent.clear()
check("just lit: kept", not A.tick() and not sent)
A._lit_at = time.time() - 60
MP.steps = [Step(dark200), Step(lit0), Step(lit0)]
g.view_seq += 1
check("dark room just ahead: kept", not A.tick() and not sent)
MP.steps = [Step(lit0), Step(lit0), Step(lit0)]
g.view_seq += 1
check(f"light enough here and ahead: rem it ({sent})", A.tick() and sent == ["rem lantern"] and A.lit is None)

# --- burn-out lines
for line in ("Your torch flickers and goes out.", "Your lamp runs out of oil, and goes out.",
             "The light in the moon-lamp flickers, and goes out.", "Your light ball disappears out of existance.",
             "torch is no longer lit!"):
    A.lit = "torch"; sent.clear()
    A.note_line(line)
    check(f"burn-out read: {line!r}", A.lit is None and sent == ["i"] and A._relight)
# pack comes back, we're in the dark: light a spare
g.carrying = "torch, leather armour (Worn)"
g.view = RoomView("(dark)", None); g.view_seq += 1; g.candidates = [dark200]
g.inv_seq += 1
sent.clear()
check(f"spare lit after the burn-out ({sent})", A.tick() and sent == ["use torch"])
A.note_line("You lit the torch.")

# --- dark line while we think it's lit: stale belief → 'i', then a spare
A.pending = None; A._relight = False
g.view = RoomView("(dark)", None); g.view_seq += 1
sent.clear()
check(f"stale: can't see with the torch 'lit' → one 'i' ({sent})", A.tick() and sent == ["i"] and A.lit is None)
g.carrying = "2 torches"; g.inv_seq += 1
sent.clear()
A.tick()
check(f"…then a spare ({sent})", sent == ["use torch"])

# --- a light that won't light is dropped
A.note_line("You must recharge that before you may light it again.")
check("won't light → not used again", "torch" in A.bad and A.pick(1) is None)
A.bad.clear(); A.pending = None

# --- learned from what we saw: a room seen without a light is fine
A.lit = None
g.view = RoomView("Gloomy Hall", {"N"}); g.view_seq += 1; g.candidates = [dark200]
b.walking = False
A.tick()
check("seen without a light → that room needs none", A.need(dark200) == 0)
A.seen_ok.clear()

# --- buying at the end of a lap
g.carrying = "leather armour (Worn)"
class Loop:
    title = "Dark loop"; is_loop = True; resolved = True
    steps = [Step(lit0), Step(dark325)]
rec, cnt = A.buy_plan([lit0, dark325])
check(f"no light strong enough: buy the weakest that is ({rec['name']} ×{cnt})", rec["strength"] >= 175 and 1 <= cnt <= 5)
g.carrying = "lantern"
check("a lantern carried: nothing to buy", A.buy_plan([lit0, dark325]) is None)
g.carrying = "lantern (Readied/10)"
check("readied lantern nearly spent, no spare: buy", A.buy_plan([lit0, dark325]) is not None)
g.carrying = "lantern (Readied/10), lantern"
check("…with a spare: no", A.buy_plan([lit0, dark325]) is None)
check("a loop with no dark rooms: no", A.buy_plan([lit0]) is None)
g.carrying = "leather armour (Worn)"
g.wealth = 10 ** 6
trips = s.trips
trips._nearest = lambda rooms, limit: (rooms[0], 5)
calls = []
b.goto = lambda room, then=None, ask=None: calls.append(("goto", room)) or True
b.start_path = lambda mp, loop=None, checked=False: calls.append(("loop", mp.title)) or True
check("lap end: off to buy", A.lap_end(Loop()) and trips.trip and trips.trip["cmds"][0].startswith("buy "))
nm = A.buying["name"]
trips.trip = None
g.inv_seq += 1                                # the pack after the trip: still none
A.tick()
check(f"failed buy → back off ({A.backoff})", nm in A.backoff and A.backoff[nm][1] == L.BACKOFF_MIN)
check("…so the next lap doesn't go for the same light", not A.lap_end(Loop()) or trips.trip["cmds"][0] != f"buy {nm}")
trips.trip = None; A.buying = None
g.wealth = 0
A.backoff.clear()
check("no cash: no trip", not A.lap_end(Loop()))

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
