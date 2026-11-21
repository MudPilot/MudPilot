"""0.8.201 bug hunt (rest / heal / blesses + new features): regression checks for bug_hunt/rest_heal.md #1-10 and
bug_hunt/new_features.md #1-6."""
import io, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session

real = time.time
clock = [real()]
ok = True


def check(n, c):
    global ok
    ok &= bool(c)
    print(("PASS " if c else "FAIL ") + n)


class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def send_raw(self, x): pass
    def close(self): pass


def fresh(**kw):
    st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
    for k, v in kw.items():
        setattr(st, k, v)
    s = Session(st); s._no_log_file = True
    s.telnet = T(); s._entered = True
    sent = []
    s.bot.send = lambda c, *a, **k: sent.append(c)
    s.send = lambda c, from_bot=False: sent.append(c)
    logs = []
    s.bot.log = lambda m, *a, **k: logs.append(m)
    return s, s.bot, s.state, sent, logs


def at(t):
    clock[0] = t


time.time = lambda: clock[0]
try:
    t0 = real()
    STOCK = ["Name: Miserable Revolution             Lives/CP:      8/0",
             "Willpower: 60     Charm:   60          MagicRes:       82"]
    # ---- rest_heal #1: stock 'st' (no effects list) doesn't expire blesses
    at(t0)
    s, b, g, sent, logs = fresh()
    prot = {"name": "prot", "cast": "prot", "on_msg": "You feel protected!"}
    s.settings.buffs = [prot]
    b.x._bless_active["prot"] = t0 - 5
    for l in STOCK:
        b.note_line(l)
    at(t0 + 2)
    b.x.stat_block_tick()
    check("#1 stock 'st': an active bless isn't marked worn off", not b._buff_off.get("prot")
          and "prot" in b.x._bless_active)
    # the judge counts a reading after a cast even when a recast came later
    s, b, g, sent, logs = fresh()
    s.settings.buffs = [prot]
    for i in range(2):
        base = t0 + 100 * (i + 1)
        b._buff_cast["prot"] = base - 3
        at(base)
        for l in STOCK:
            b.note_line(l)
        b._buff_cast["prot"] = base + 2             # recast after the reading
        at(base + 5)
        b._st_judge()
    check("#1 stock: two readings after casts -> stops asking 'st' for timers", b._st_no_timers >= 2)
    # Paradigm keeps working: effects listed with timers, then an 'st' without the bless -> recast
    s, b, g, sent, logs = fresh()
    s.settings.buffs = [prot]
    at(t0 + 1000)
    for l in STOCK + ["You feel protected! (100s)"]:
        b.note_line(l)
    at(t0 + 1002)
    b.x.stat_block_tick()
    check("#1 Paradigm: 'st' lists effects", getattr(b.x, "_stat_lists_effects", False))
    b.x._bless_active["prot"] = t0 + 1003
    at(t0 + 1010)
    for l in STOCK:
        b.note_line(l)
    at(t0 + 1012)
    b.x.stat_block_tick()
    check("#1 Paradigm: a bless missing from the list is recast", b._buff_off.get("prot"))

    # ---- rest_heal #2: a leftover idle-rest flag is cleared when a real rest starts
    at(t0 + 2000)
    s, b, g, sent, logs = fresh(rest_below_hp=60, rest_until_hp=100, auto_rest=True)
    g.max_hp, g.hp = 100, 40
    b._idle_rest = True
    b.should_rest([], False)
    check(f"#2 real rest starts ({sent}) and drops the idle flag", s.settings.rest_cmd in sent and not b._idle_rest)

    # ---- rest_heal #3: rest broken by a fight, over the rest line -> @ok after a few seconds
    at(t0 + 3000)
    s, b, g, sent, logs = fresh(rest_below_hp=60, rest_until_hp=100)
    g.max_hp, g.hp = 100, 70
    g.party = {"Leader": {"hp": 100, "t": t0 + 3000}, "Miserable": {"hp": 70, "t": t0 + 3000}}
    b.x.send = lambda c, *a, **k: sent.append(c)
    b._rest_begun = True
    b.x._sent_wait, b.x._wait_to = True, "Leader"
    b.x._hold_reasons = {"resting"}
    b.should_rest([], False)
    at(t0 + 3006)
    b.should_rest([], False)
    check(f"#3 broken rest: @ok sent ({sent[-1:]})", not b._rest_begun and not b.x._sent_wait
          and any("@ok" in c or s.settings.party_resume_msg in c for c in sent))

    # ---- rest_heal #4: HP stuck below a stale max while resting -> 'st'
    at(t0 + 4000)
    s, b, g, sent, logs = fresh(rest_below_hp=60, rest_until_hp=100)
    g.max_hp, g.hp, g.resting = 400, 380, True
    b.should_rest([], False)
    at(t0 + 4061)
    b.should_rest([], False)
    check(f"#4 stale max: 'st' read while resting ({sent})", "st" in sent)

    # ---- rest_heal #5: "You feel sick." isn't poison; death clears ailments; self-cure capped at 3
    at(t0 + 5000)
    s, b, g, sent, logs = fresh(cure_poison_cmd="cupo")
    b.x.note_line("You feel sick.")
    check("#5 'You feel sick.' isn't poison", "poison" not in b.x.ailments)
    b.x.note_line("You have been poisoned!")
    check("#5 real poison still noticed", "poison" in b.x.ailments)
    for i in range(6):
        at(t0 + 5000 + i * 5)
        b.x.cure_tick()
    check(f"#5 cure poison tried 3 times, then dropped ({sent.count('cupo')})",
          sent.count("cupo") == 3 and "poison" not in b.x.ailments)
    b.x.ailments["blind"] = t0
    try:
        b.on_death()
    except Exception as e:
        print("  (on_death raised", e, ")")
    check("#5 death clears ailments", not b.x.ailments)

    # ---- rest_heal #6: no mana for the heal -> no heal spam, ask for one
    at(t0 + 6000)
    s, b, g, sent, logs = fresh(heal_cmd="mihe", heal_pct=50, request_heal_pct=50)
    s.spellbook.find = lambda w: {"ManaCost": 5, "Name": "minor healing"} if w == "mihe" else None
    g.max_hp, g.hp, g.max_ma, g.ma = 100, 40, 50, 0
    g.party = {"Leader": {"hp": 100, "t": t0 + 6000}}
    b.heal_tick()
    check(f"#6 0 mana: no 'mihe', a heal request instead ({sent})", "mihe" not in sent and len(sent) == 1)
    g.ma = 20
    at(t0 + 6030)
    sent.clear()
    b.heal_tick()
    check(f"#6 with mana: heals ({sent})", "mihe" in sent)

    # ---- rest_heal #7: after the wait timeout, no log spam and no instant re-timeout
    at(t0 + 7000)
    s, b, g, sent, logs = fresh(party_wait_pct=50, party_wait_mins=1, party_check_secs=0)
    b.x._own_party = True
    def par(hp):
        g.party = {"Aa": {"hp": hp, "ma": 100, "t": clock[0]}, "Miserable": {"hp": 100, "t": clock[0]}}
    par(30)
    check("#7 waits for a low member", b.x.wait_for_party())
    at(t0 + 7061); par(30)
    check("#7 gives up after the wait time", not b.x.wait_for_party())
    for i in range(40):
        at(t0 + 7062 + i); par(30)
        b.x.wait_for_party()
    n = sum(1 for m in logs if m.startswith("Waiting for"))
    check(f"#7 no 'Waiting for' every tick after the timeout ({n})", n == 1)
    at(t0 + 7110); par(80); b.x.wait_for_party()
    at(t0 + 7111); par(30)
    check("#7 back over the line and down again -> waits again", b.x.wait_for_party())

    # ---- rest_heal #8: area heal not recast on the same old 'par'
    at(t0 + 8000)
    s, b, g, sent, logs = fresh(party_heal=True, party_area_cmd="gahe", party_area_pct=60, party_area_count=2)
    b.slot_free = lambda: True
    g.max_hp, g.hp = 100, 100
    g.party = {"Aa": {"hp": 50, "t": t0 + 8000}, "Bb": {"hp": 50, "t": t0 + 8000}, "Miserable": {"hp": 100, "t": t0}}
    b.heal_tick()
    at(t0 + 8004)
    b.heal_tick()
    check(f"#8 one area heal on one reading ({sent.count('gahe')})", sent.count("gahe") == 1)

    # ---- rest_heal #9: "You do not have enough mana" -> the bless isn't counted as up
    at(t0 + 9000)
    s, b, g, sent, logs = fresh()
    b._buff_cast["bles"], b._rerolls["bles"] = t0 + 8999, 1
    b.note_line("You do not have enough mana to cast that spell.")
    check("#9 not enough mana: bless marked down, reroll undone", b._buff_off.get("bles") and not b._rerolls["bles"])

    # ---- rest_heal #10: kai class, prompt with no KAI -> 0
    s, b, g, sent, logs = fresh()
    g._check_prompt("[HP=100/KAI=5]:")
    g._check_prompt("[HP=100]:")
    check(f"#10 no KAI in the prompt = 0 kai ({g.ma})", g.ma == 0)
    s, b, g, sent, logs = fresh()
    g._check_prompt("[HP=100/MA=30]:")
    g._check_prompt("[HP=100]:")
    check("#10 a mana class is left alone", g.ma == 30)

    # ---- new_features #1: party training asks a trailing member again after "notthere"
    at(t0 + 10000)
    s, b, g, sent, logs = fresh()
    tr = s.training
    tr.trip = {"stops": [{"room": (1, 2), "targets": {"Bob": 5}, "members": ["Bob"], "me": False, "markup": 0}],
               "i": 0, "queue": ["Bob"], "cur": None, "trained": 0}
    tr._stop_tick(t0 + 10000)
    tr.party_msg("Bob", "done 0 notthere")
    at(t0 + 10003)
    tr._stop_tick(t0 + 10003)
    n = sum(1 for c in sent if "@ptrain train" in c)
    check(f"#NF1 'notthere' -> asked again ({n})", n == 2 and tr.trip["cur"] is not None)
    tr.party_msg("Bob", "done 0 busy")
    tr._stop_tick(t0 + 10006)
    check("#NF1 a real refusal still skips the member", tr.trip["cur"] is None)

    # ---- new_features #2: Hands off mid-form keeps the form ticking
    s, b, g, sent, logs = fresh()
    ticked = []
    s.training._form_tick = lambda now: ticked.append(now)
    s.training.me = {"phase": "typing"}
    s.settings.hands_off = True
    try:
        s.poll()
    except Exception as e:
        print("  (poll raised", e, ")")
    check("#NF2 Hands off: the train stats form still ticks", ticked)

    # ---- new_features #3: someone's gossip about a level isn't our level-up
    s, b, g, sent, logs = fresh(auto_scrolls=True)
    s.scrolls.note_line("Bob gossips: you are now level 20, grats")
    check("#NF3 gossip isn't a level-up", s.scrolls.pending is None)
    s.scrolls.note_line("You are now level 20!")
    check("#NF3 the real line is", s.scrolls.pending == "level-up")

    # ---- new_features #4: someone else's light going out
    s, b, g, sent, logs = fresh(auto_light_items=True)
    b.lights.lit = "torch"
    b.lights.note_line("Bob's torch is no longer lit!")
    check("#NF4 Bob's torch going out leaves ours lit", b.lights.lit == "torch")
    b.lights.note_line("The torch is no longer lit!")
    check("#NF4 ours going out is noticed", b.lights.lit is None)

    # ---- new_features #5: made a follower mid-errand -> the errand ends
    s, b, g, sent, logs = fresh(auto_scrolls=True)
    s.scrolls.trip = {"phase": "reading", "t": clock[0] - 10, "back": None, "why": "x", "visited": set(),
                      "next_at": 0, "sent": False, "stop": None, "queue": [], "cur": None, "forced": False}
    b.x._following = "Leader"
    s.scrolls.tick()
    check("#NF5 scrolls errand ends when following", s.scrolls.trip is None)
    s, b, g, sent, logs = fresh(auto_train=False)
    s.training.trip = {"phase": "going", "t": clock[0] - 10, "back": None, "stops": [{"room": (1, 1)}], "i": 0,
                       "members0": [], "trained": 0, "went": clock[0]}
    s.training.tick()
    check("#NF5 training trip ends when auto-train is off", s.training.trip is None)

    # ---- new_features #6: a bad download leaves no .part and says so plainly
    from mudpilot import updater
    import urllib.request
    d = tempfile.mkdtemp()
    class R(io.BytesIO):
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *a): return False
    old_open, old_dir = urllib.request.urlopen, updater.download_dir
    urllib.request.urlopen = lambda *a, **k: R(b"not a zip")
    updater.download_dir = lambda: d
    try:
        try:
            updater.download({"asset": "https://github.com/MudPilot/MudPilot/releases/download/v9/x.zip",
                              "version": "9.9.9"})
            err = None
        except Exception as e:
            err = e
    finally:
        urllib.request.urlopen, updater.download_dir = old_open, old_dir
    check(f"#NF6 bad zip -> ValueError ({type(err).__name__})", isinstance(err, ValueError))
    check(f"#NF6 no .part left ({os.listdir(d)})", not os.listdir(d))
finally:
    time.time = real

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
