"""0.8.200 auto-train, the train stats form (training.py). CP can't be unspent, so: every automatic command is held
from the moment 'train stats' goes out until the form is gone; the six stats and CP Left are read off the screen; the
11 field payloads go ~200 ms apart; the form is read back before the final Enter and anything not exactly as typed
backs out with QUIT (Space at most 4 times, Enter only once Exit reads QUIT) — never SAVE a form that can't be
verified. A bare Enter after leaving. Both the Character Editor and Paradigm's cursor-drawn Char. Creation box."""
import os, sys, time, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot import training as T
from mudpilot.ansi import AnsiStream
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

LABELS = ("Strength", "Intellect", "Willpower", "Agility", "Health", "Charm")
RANGES = ((55, 160), (30, 130), (30, 135), (45, 145), (55, 165), (30, 120))


def editor(stats, cp, exit_="SAVE", field=0):
    """The Character Editor as the game paints it: a clear, a row per line, the cursor parked on the field's row."""
    rows = ["    .-------------------------------------.--.",
            "   / M A J O R  M U D Character Editor /    \\  +-    Point Cost Chart    -+",
            "  |                                     +--.   | |                          |",
            "  | > Given Name   Someone            < |___\\_/  | 1st 10 points: 1 CP each |",
            "  | > Family Name                     < |        | 2nd 10 points: 2 CP each |",
            "  | > Race         Human              < |        | 3rd 10 points: 3 CP each |",
            "  | > Class        Mage               < |        |     ... and so on ...    |",
            "  |                                     |        |                          |"]
    for i, lab in enumerate(LABELS):
        lo, hi = RANGES[i]
        rows.append(f"  | > {lab:<9}  ({lo:4} to {hi:4})  {stats[i]:4} < |        |")
    rows += ["  |                                     |",
             "  | >  Hair Length   None             < |",
             "  | >  Hair Colour   Black            < |",
             "  | >  Eye Colour    Black            < |",
             "  |                                     |",
             f"  | >  Exit: {exit_:<4} <  > CP Left:    {cp:4} < | -------- SAVE, EDIT or QUIT",
             "  +-----------------------------------.     |"]
    row = {0: 5}.get(field, 8 + field if field <= 6 else (9 + field if field <= 9 else 20))
    return "\x1b[2J\x1b[H" + "".join(r + "\r\n" for r in rows) + f"\x1b[{row};36H"


def creation_box(stats, cp):
    """Paradigm's Char. Creation box: cursor-positioned, the title row painted last (the cursor's left there)."""
    out = "\x1b[2J\x1b[1;1H\x1b[5;3H| > Family Name\x1b[5;39H<"
    for i, lab in enumerate(LABELS):
        r = 9 + i
        lo, hi = RANGES[i]
        out += f"\x1b[{r};3H| > {lab}\x1b[{r};39H<\x1b[{r};41H|\x1b[{r};18H({lo:4} to {hi:4})\x1b[{r};34H{stats[i]:4}"
    out += f"\x1b[20;3H| >  Exit:\x1b[20;14HSAVE\x1b[20;19H<\x1b[20;22H> CP Left:\x1b[20;33H{cp:4}\x1b[20;39H<"
    return out + "\x1b[2;4H/ P A R A D I G M      Char. Creation /    \\  --    Point Cost Chart    --"


def screen_of(wire):
    a = AnsiStream()
    a.feed(wire)
    return "\n".join(a.screen.text_rows())

# ------------------------------------------------------------ reading the form
BASE = [55, 30, 30, 45, 55, 30]
f = T.read_form(screen_of(editor([133, 40, 30, 100, 60, 30], 26)))
check(f"Character Editor read ({f})", f and f["stats"] == [133, 40, 30, 100, 60, 30] and f["cp"] == 26
      and f["exit"] == "SAVE" and f["mins"][0] == 55 and f["maxs"][3] == 145)
f = T.read_form(screen_of(creation_box([133, 40, 30, 100, 60, 30], 26)))
check(f"Paradigm's cursor-drawn Char. Creation box read ({f})", f and f["stats"] == [133, 40, 30, 100, 60, 30]
      and f["cp"] == 26 and f["exit"] == "SAVE")
full = screen_of(editor(BASE, 40))
check("half-drawn (a stat row missing) is not read in part", T.read_form(full.replace("Charm", "     ")) is None)
check("…nor without CP Left", T.read_form(full.replace("CP Left:", "        ")) is None)
check("a room screen isn't a form", T.read_form("Obvious exits: north\nStrength:  153    Agility: 90\n") is None)
scroll = ("M A J O R   M U D\nCharacter Generator\n+---- Point Cost Chart ----+\nStrength  55 - 160\n"
          "Intellect 30 - 130\nYou have 26 CP to distribute.\n")
check("Stock's scrolling Character Generator (no current values) is not read", T.read_form(scroll) is None)

# ------------------------------------------------------------ what to type
form = {"stats": list(BASE), "mins": [r[0] for r in RANGES], "maxs": [r[1] for r in RANGES], "cp": 40}
tg, cost = T.targets_for(form, {"STR": 60, "AGL": 50})
check(f"plan STR 60 AGL 50 from the minimums: 5 + 5 CP ({tg}, {cost})", tg == [60, 30, 30, 50, 55, 30] and cost == 10)
tg, cost = T.targets_for(form, {"STR": 50, "INT": 30})
check("a stat already at/over the plan is left alone (no untraining)", tg == BASE and cost == 0)
tg, cost = T.targets_for(dict(form, cp=10 ** 6), {"STR": 999})
check(f"never past the race maximum ({tg[0]})", tg[0] == 160)
form12 = dict(form, cp=12)
tg, cost = T.targets_for(form12, {"STR": 70, "AGL": 50})
check(f"CP short: raised in plan order as far as it goes ({tg}, {cost} CP)",
      tg[0] == 66 and tg[3] == 45 and cost == 12)
check(f"payloads: Family Name, six stats (digits only for a raise), three appearance boxes "
      f"({T.payloads(BASE, [60, 30, 30, 50, 55, 30])})",
      T.payloads(BASE, [60, 30, 30, 50, 55, 30]) == ["", "60", "", "", "50", "", "", "", "", ""])

# ------------------------------------------------------------ the whole thing on a Session
sent, raw = [], []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def send_raw(self, b): raw.append(b.decode("cp437"))
    def close(self): pass

clock = [time.time()]
logs = []
T.time = types.SimpleNamespace(time=lambda: clock[0])      # the form's timings run on a fake clock

def make():
    st = config.Settings(); st.save = lambda: None; st.board = "Paradigm"; st.my_name = "Miserable"
    s = Session(st); s._no_log_file = True
    s.telnet = Tel(); s._entered = True
    s.log = lambda m, *a, **k: logs.append(m)
    s.state.char_class, s.state.race, s.state.level = "Mage", "Human", 10
    s.state.in_combat = s.state.resting = False
    st.auto_train = st.train_stats = True
    st.train_stats_plan = "5: HEA 55; 10: STR 60 AGL 50"
    return s, st

def begin(s, done):
    s.training._me_start(0, on_done=lambda n, why: done.append((n, why)))
    s.training.me["trained"] = 1
    s.training._after_trains("all banked levels trained")

def run(s, secs, step=0.1):
    end = clock[0] + secs
    while clock[0] < end:
        clock[0] += step
        s.training.tick()

def run_until(s, cond, secs=5.0, step=0.05):
    end = clock[0] + secs
    while clock[0] < end and not cond():
        clock[0] += step
        s.training.tick()

def paint(s, wire):
    s.ansi.feed(wire)

s, st = make()
Tr = s.training
done = []
sent.clear(); raw.clear()
begin(s, done)
check(f"'train stats' sent ({sent})", sent == ["train stats"])
check("the hold starts as it goes out (not when the form shows)", s.form_held() and Tr.me["phase"] == "form_wait")
s.send("par", from_bot=True)
s.remote.reply("telepath", "Revolution", "HP=100/100")
s.send("@ok", from_bot=True)
check(f"automatic commands held: par, a telepath reply ({sent})", sent == ["train stats"])
s.send("look", from_bot=False)
check("what you type yourself still goes", sent[-1] == "look")
sent.clear()
paint(s, editor(BASE, 40))
run(s, 0.8)
check(f"form read: typing ({Tr.me['phase']}, targets {Tr.me.get('targets')}, {Tr.me.get('cost')} CP)",
      Tr.me["phase"] in ("typing", "verify") and Tr.me["targets"] == [60, 30, 30, 50, 55, 30] and Tr.me["cost"] == 10)
run_until(s, lambda: Tr.me["phase"] == "verify")
check(f"10 field payloads, digits + CR, ~200 ms apart ({raw})",
      raw == ["\r", "60\r", "\r", "\r", "50\r", "\r", "\r", "\r", "\r", "\r"])
check("…and no Enter on Exit yet (it waits to read the form back)", Tr.me["phase"] == "verify")
paint(s, editor([60, 30, 30, 50, 55, 30], 30, field=10))
run(s, 1.0)
check(f"read back exactly as typed, CP Left 40 - 10 = 30: SAVE ({raw[10:]})", raw[10:] == ["\r"]
      and Tr.me["phase"] == "closing")
check("still held while it closes", s.form_held())
Tr.note_line("Training complete! Stats updated.")
run(s, 0.2)
check(f"form gone: hold released, a bare Enter for the room ({sent})", not s.form_held() and sent == [""])
check(f"done ({done})", done and done[0][0] == 1 and Tr.me is None)

# --- mismatch → QUIT
s, st = make(); Tr = s.training; done = []
sent.clear(); raw.clear()
begin(s, done)
paint(s, editor(BASE, 40))
run_until(s, lambda: Tr.me["phase"] == "verify")
assert Tr.me["phase"] == "verify", Tr.me["phase"]
paint(s, editor([60, 30, 30, 49, 55, 30], 31, field=10))          # Agility didn't take what was typed
run(s, 1.2)
check(f"mismatch: no SAVE — a Space on Exit instead ({raw[10:]})", raw[10:] == [" "] and Tr.me["phase"] == "backout")
run(s, 2.0)
check(f"Exit still shows SAVE: more Spaces, never an Enter ({raw[10:]})", "\r" not in raw[10:])
paint(s, editor([60, 30, 30, 49, 55, 30], 31, exit_="QUIT", field=10))
n_before = len(raw)
run(s, 0.8)
check(f"Exit reads QUIT → Enter ({raw[n_before:]})", raw[n_before:] == ["\r"] and Tr.me["phase"] == "closing")
check(f"at most 4 Spaces ({raw.count(' ')})", raw.count(" ") <= 4)
s.state.last_prompt = time.time() + 5        # the prompt after leaving
run(s, 0.2)
check(f"left the form: hold released, bare Enter ({sent[-1:]}, {done})", not s.form_held() and sent[-1] == ""
      and done and any("not saving the train stats form" in m for m in logs))

# --- QUIT never shows: press nothing more, leave it for the player
s, st = make(); Tr = s.training; done = []
sent.clear(); raw.clear()
begin(s, done)
paint(s, editor(BASE, 40))
run_until(s, lambda: Tr.me["phase"] == "verify")
paint(s, editor([61, 30, 30, 50, 55, 30], 28, field=10))
run(s, 6.0)
check(f"never QUIT after 4 Spaces: no Enter, form left open ({raw[10:]})",
      raw[10:] == [" ", " ", " ", " "] and Tr.me["phase"] == "left_open")
check("…the bot's stopped and the hold stays up", s.form_held() and "train stats" in str(s.bot.status))

# --- the game refuses a value mid-typing
s, st = make(); Tr = s.training; done = []
sent.clear(); raw.clear()
begin(s, done)
paint(s, editor(BASE, 40))
run(s, 0.8)
run(s, 0.3, step=0.05)
typed = Tr.me["typed"]
Tr.note_line("Strength may not be higher than 58.")
run(s, 0.05)
check(f"value refused → backing out ({Tr.me['phase']})", Tr.me["phase"] == "backout")
run(s, 3.0, step=0.05)
enters = [k for k in raw[typed:] if k == "\r"]
check(f"Enters to the Exit field only (never past it): {len(enters)} after {typed} keys",
      len(enters) == 10 - (typed - 1))
paint(s, editor([55, 30, 30, 45, 55, 30], 40, exit_="QUIT", field=10))
n_before = len(raw)
run(s, 1.0)
check(f"…then Enter on QUIT ({raw[n_before:]})", raw[n_before:][-1:] == ["\r"] and Tr.me["phase"] == "closing")

# --- train stats refused
s, st = make(); Tr = s.training; done = []
sent.clear(); raw.clear()
begin(s, done)
Tr.note_line("You may not train your stats here!")
run(s, 0.2)
check(f"refused: hold released, bare Enter, nothing typed ({sent}, {raw})", not s.form_held() and sent[-1] == ""
      and not raw and done)
s, st = make(); Tr = s.training; done = []
sent.clear(); raw.clear()
begin(s, done)
Tr.note_line("Your stats are unnaturally altered!  You may not train stats now.")
run(s, 0.2)
check("Stock's altered-stats refusal too", not s.form_held() and done)

# --- no form at all
s, st = make(); Tr = s.training; done = []
sent.clear(); raw.clear()
begin(s, done)
run(s, 11.0, step=0.5)
check(f"no form in 10 s: carries on, nothing typed ({sent}, {raw})", not s.form_held() and not raw and done)

# --- nothing to raise: leave with QUIT, never SAVE
s, st = make(); Tr = s.training; done = []
st.train_stats_plan = "10: STR 50"
sent.clear(); raw.clear()
begin(s, done)
paint(s, editor(BASE, 40))
run(s, 3.5, step=0.05)
check(f"plan already met: Enters to Exit (10) and no SAVE ({raw})", raw == ["\r"] * 10 + [" "] or raw == ["\r"] * 10)
paint(s, editor(BASE, 40, exit_="QUIT", field=10))
run(s, 1.0)
check("…QUIT, then Enter", raw[-1] == "\r" and Tr.me["phase"] == "closing")

# --- your Stop mid-typing: QUIT
s, st = make(); Tr = s.training; done = []
sent.clear(); raw.clear()
begin(s, done)
paint(s, editor(BASE, 40))
run(s, 0.8)
run(s, 0.4, step=0.05)
s.bot._user_stop_at = clock[0] + 1
run(s, 0.05)
check("Stop mid-typing: backs out (nothing saved)", Tr.me["phase"] == "backout")

# --- no plan row for this level: no form at all
s, st = make(); Tr = s.training; done = []
st.train_stats_plan = "20: STR 60"
sent.clear()
begin(s, done)
check(f"no plan row at this level: train stats not sent ({sent})", "train stats" not in sent and done)

# --- your own 'train stats' starts the hold too; back in the realm ends it
s, st = make()
sent.clear()
s.send("train stats")
check("typed 'train stats': hold on", s.form_held())
s.note_form_seen()
s.send("par", from_bot=True)
check("…automatic par held", "par" not in sent)
s.end_form_hold("test")
s.send("par", from_bot=True)
check("released: par goes", sent[-1] == "par")

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
