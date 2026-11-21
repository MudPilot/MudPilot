"""Dan, 2026-11-01: Miserable PVE bashed a door it could pick, Pick locks ticked. Picklocks over what the door needs →
pick first: before the key, before bashing."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import Step
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.pick_locks = True; st.bash_doors_first = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


g, b, w = s.state, s.bot, s.world
door = (8, 433)
ex = w.room(door).exits.get("D")
check(f"the Dark Passageway door: picklocks/strength ({ex.etype})", ex is not None and "picklocks/strength" in ex.etype)
need = int(b.DOOR_NEED_RE.search(ex.etype).group(1))


def first_cmds(picklocks, n=2):
    g.picklocks, g.strength, g.max_hp, g.hp = picklocks, 70, 500, 500
    g.candidates = [door]
    b.walking, b.path = True, type("P", (), {"steps": [Step("D", 0, "D", [], door, ex.to)], "title": "old path",
                                             "is_loop": False, "filename": "", "needed_item": ""})()
    b.idx, b._lock_tries, b._unlocked = 0, {"D": 0}, None
    sent.clear(); b._cool.clear()
    out = []
    for _ in range(n):
        b._door_wait_until, b._locked_dir = 0, "D"
        try:
            b.walk([], True)
        except Exception:
            pass
    out = [c for c in sent if c.split()[0] in ("pick", "bash", "use", "open")]
    b.walking, b.path = False, None
    return out


got = first_cmds(need + 20)
check(f"picklocks {need + 20} ≥ {need}: picks first, no bash ({got})", got and got[0].startswith("pick") and
      not any(c.startswith("bash") for c in got))
got = first_cmds(max(1, need - 20))
check(f"picklocks under what it needs: bashes ({got})", got and got[0].startswith("bash"))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
