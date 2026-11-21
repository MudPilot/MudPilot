"""Best spots in the background doesn't bog the rest of MudPilot down (Dan, 2026-11-02): the window's thread
keeps getting its turn while the search runs, and opening the window again shows the last search."""
import os, sys, time, threading
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.spots import calm_thread
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
k = s.world.by_name["rotting glade, trail"][0]
s.state.candidates = [k]; s.state.level = 47; s.state.max_hp = 684; s.state.hp = 684
check("nothing kept before the first search", s.spots.kept() is None)
res = {}
def work():
    with calm_thread():
        res["r"] = s.spots.find()
th = threading.Thread(target=work, daemon=True); th.start()
gaps, t0 = [], time.perf_counter()
while th.is_alive():                                  # the 'window': wants a turn every 10 ms
    a = time.perf_counter(); time.sleep(0.01); sum(range(2000)); gaps.append(time.perf_counter() - a)
dt = time.perf_counter() - t0
gaps.sort()
worst = gaps[int(len(gaps) * 0.99) - 1] if len(gaps) > 20 else max(gaps or [0])
check(f"search done ({dt:.1f} s, {len(res['r'].get('spots') or [])} spots)", res["r"].get("spots"))
check(f"the window kept its turns (99% of 10 ms waits under 60 ms: {worst * 1000:.0f} ms)", worst < 0.06)
check(f"switch interval back to normal ({sys.getswitchinterval()})", sys.getswitchinterval() >= 0.004)
kept = s.spots.kept()
check("reopening shows the last search", kept and kept[0] is res["r"])
s.state.party = {"Miserable": {}, "Revolution": {}}
check("…but not once the party's changed", s.spots.kept() is None)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
