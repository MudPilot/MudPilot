"""Dan, 2026-11-01: Buddy's Go to the Iceforge stopped dead at "can't fetch dragon key automatically" — MME knows
nowhere to get one, but someone in the party might carry it. Ask the party first; nobody has one → stop and say so.
And the status bar kept saying "Waiting for Evolution" long after that wait was over."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
b, g, er = s.bot, s.state, s.bot.errands
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


# a key with no shop, no drop and no recipe in MME (the dragon key has a recipe now: test_dragon_key.py)
KEY = next(n for n, i in sorted(s.world.items.items()) if "key" in i["name"] and i.get("gettable", 1)
           and not er.source_for(n) and not s.world.recipe_for(n))
KNAME = s.world.item_name(KEY)
mp = type("P", (), {"steps": [], "title": "Go to 3/632 The Iceforge", "is_loop": False, "filename": "",
                    "needed_item": ""})()
g.party = {"Buddy": {}, "Revolution": {}, "Evolution": {}}
g.candidates = [(3, 595)]
okk, why = er.plan(mp, False, [KEY])
check(f"no known source, but a party: plans to ask them ({okk}, {why})", okk and er.active["todo"][0]["kind"] == "party")
sent.clear(); er.tick()
check(f"asks the party ({sent})", f"/Revolution @have {KNAME}" in sent and f"/Evolution @have {KNAME}" in sent)
er.have_answer("Revolution", "{yes: " + KNAME + "}")
er.have_answer("Evolution", "{no " + KNAME + "}")
sent.clear(); er.tick()
check(f"Revolution has one: asked to hand it over ({sent})", f"/Revolution @do give {KNAME} to Buddy" in sent)
# nobody has one
er.active = None
okk, why = er.plan(mp, False, [KEY])
er.tick()
er.have_answer("Revolution", "{no " + KNAME + "}"); er.have_answer("Evolution", "{no " + KNAME + "}")
er.tick(); er.tick()
check(f"nobody has one: stops and says so ({b.status})", not er.active and "nobody in the party has one" in b.status)
# solo: as before
g.party = {}
okk, why = er.plan(mp, False, [KEY])
check(f"solo: can't fetch, as before ({why})", not okk and ("can't fetch" in why or "won't kill an NPC" in why))
# a stale party wait doesn't outlive the walk
b.x.waiting_on = ["Evolution"]
b.stop("Stopped by you")
check("stopping clears 'waiting for Evolution'", not b.x.waiting_on)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
