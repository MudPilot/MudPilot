"""0.8.201 upgrade alerts: weapons that hit harder and shop lists join the armour watch; phone alert hook; weapons
are never picked up or wielded by themselves (gearwatch.py)."""
import os, sys, time, shutil, tempfile
_tmp = tempfile.mkdtemp()
os.environ["MUDPILOT_DATA_DIR"] = os.path.join(_tmp, "data")      # never the real data folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, notify
from mudpilot import gearcalc as G
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
db = os.path.join(_tmp, "world.db")
shutil.copy2(os.path.join(config.BUNDLED_DIR, "Paradigm.db"), db)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.board = "Paradigm"
st.auto_combat = False; st.auto_rest = False; st.auto_bless = False; st.auto_spells = False
s = Session(st, world_path=db); s._no_log_file = True
sent, logs, alerts, phone = [], [], [], []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
s.log = lambda m, *a, **k: logs.append(m)
s.on_alert = lambda m: alerts.append(m)
s.notify.send = lambda kind, msg, force=False: phone.append((kind, msg))
w, gw = s.world, s.gearwatch
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)

check("defaults: watch on, weapons on", config.Settings().gear_watch and config.Settings().gear_watch_weapons)
check("'upgrade' is a phone alert kind", "upgrade" in notify.KINDS)

st.char_class = "Warrior"; s.state.char_class = "Warrior"
s.state.level = 30; s.state.strength = 90; s.state.agility = 70
ch, f = gw.char(), gw.fighter()
check(f"warrior found (class {ch.cls})", ch.cls > 0)
best = [sw for sw in G.best_weapons(w, ch, f) if G.usable(w, sw.weapon, ch)[0]]
top = best[0].weapon if best else None
weak = next((g for g in w.gear.values() if (g.get("name") or "").lower() == "dagger"), None)
check(f"a top weapon ({top and top['name']}) and a dagger", top is not None and weak is not None)
s.state.carrying = "dagger (Weapon Hand), torch"
up = gw.upgrade(top["name"])
check(f"weapon upgrade spotted ({up and (up[1], up[2])})", up and up[1] == "Weapon" and up[2] > 0 and up[3] is weak)
check("the dagger isn't an upgrade over itself", gw.upgrade("dagger") is None)
s.state.carrying = f"{top['name']} (Weapon Hand), torch"
check("not when already wielding it", gw.upgrade(top["name"]) is None)
check("a dagger isn't an upgrade over the top weapon", gw.upgrade("dagger") is None)
s.state.carrying = "dagger (Weapon Hand), torch"
st.gear_watch_weapons = False
check("weapons off → no weapon alert", gw.upgrade(top["name"]) is None)
st.gear_watch_weapons = True

# ---- floor: alert + phone, never picked up even with Pick upgrades up
st.gear_grab_upgrades = True; st.gear_auto_wear = True
s.state.view = RoomView("x", {"N"}, items=[(1, top["name"])])
sent.clear(); gw.told.clear()
gw.on_room(s.state)
check(f"alert said ({alerts[-1] if alerts else ''})", alerts and "Upgrade here" in alerts[-1] and "damage/round" in alerts[-1])
check(f"phone hook called ({phone})", phone and phone[-1][0] == "upgrade")
check(f"weapon not picked up ({sent})", not any(x.startswith("get") for x in sent))
gw.told.clear(); sent.clear()
gw.feed_line(f"You picked up {top['name']}.")
check(f"picked up: said, not wielded ({sent})", alerts and "picked up" in alerts[-1]
      and not any(x.startswith(("wear", "wield", "eq")) for x in sent))
st.gear_grab_upgrades = False; st.gear_auto_wear = False

# ---- armour still works, once per hour
arm = next((g for g in w.gear.values() if int(g.get("ItemType") or 0) == 0 and int(g.get("Worn") or 0) == 11
            and int(g.get("ArmourClass") or 0) >= 40 and not g["abils"].get(135) and not g.get("classes")
            and G.usable(w, g, ch)[0]), None)
gw.told.clear(); alerts.clear()
s.state.view = RoomView("x", {"N"}, items=[(1, arm["name"])])
gw.on_room(s.state); gw.on_room(s.state)
check(f"armour alert once ({alerts})", len(alerts) == 1 and "(Torso)" in alerts[0])

# ---- shop list
gw.told.clear(); alerts.clear()
nm = top["name"][:29]
for ln in ["The following items are for sale here:", "", "Item                          Quantity    Price",
           "dagger                        5           10 gold crowns",
           f"{nm:<30}1          900 gold crowns",
           f"{arm['name'][:29]:<30}1          50 gold crowns (You can't use)"]:
    gw.feed_line(ln)
check(f"shop: the weapon alerted with its price ({alerts})",
      len(alerts) == 1 and "for sale" in alerts[0] and top["name"] in alerts[0] and "900 gold" in alerts[0])
gw.feed_line("[HP=100/MA=50]:")
check("list over at the prompt", gw._shop is None)
st.gear_watch = False
gw.told.clear(); alerts.clear()
gw.feed_line("The following items are for sale here:")
check("watch off → no shop reading", getattr(gw, "_shop", None) is None and not alerts)

shutil.rmtree(_tmp, ignore_errors=True)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
