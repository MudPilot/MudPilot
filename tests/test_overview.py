"""All characters window (overview.py, 0.8.201): status folders (fresh, stale, offline, missing fields, odd values),
folder discovery, merge, the optional LAN packet (clean, LAN-only, no secrets), control.py's extra status fields,
and a headless build of the window. Never touches data\\boards; everything lives in a temp folder."""
import json, os, socket, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, overview as O

ok = True


def check(n, c):
    global ok
    ok &= bool(c)
    print(("PASS " if c else "FAIL ") + n)


tmp = tempfile.mkdtemp()
now = time.time()


def mk(root, name, status=None, app=None, raw=None, mtime=None):
    d = os.path.join(root, name)
    os.makedirs(os.path.join(d, "control"), exist_ok=True)
    sp = os.path.join(d, "control", "status.json")
    if raw is not None:
        open(sp, "w", encoding="utf-8").write(raw)
    elif status is not None:
        json.dump(status, open(sp, "w", encoding="utf-8"))
    if app is not None:
        json.dump(app, open(os.path.join(d, "app.json"), "w", encoding="utf-8"))
    if mtime and os.path.exists(sp):
        os.utime(sp, (mtime, mtime))
    return d


# a "remote PC" install with several data folders, plus this PC's own install
remote = os.path.join(tmp, "M", "MudPilot", "MudPilot")
fresh = mk(remote, "data", {"t": now - 3, "version": "0.8.201", "connected": True, "in_game": True, "walking": True,
                            "path": "Stonecaps", "loop": True, "status": "Walking", "room": [14, 6551],
                            "room_name": "Stonecap Grotto", "hp": 619, "max_hp": 713, "ma": 334, "max_ma": 496,
                            "hp_pct": 87, "ma_pct": 67, "in_combat": False, "exp_hr": 1842641, "name": "Miserable",
                            "board": "Paradigm", "pvp_realm": True, "level": 47, "cls": "Mage", "profile": "Miserable"})
stale = mk(remote, "data-PVE", {"t": now - 120, "version": "0.8.200", "connected": True, "in_game": True,
                                "walking": True, "path": "Tidepool", "status": "In combat", "in_combat": True,
                                "hp_pct": 62, "ma_pct": 81, "exp_hr": 5581053, "profile": "MiserablePVE"})
offline = mk(remote, "data-revolution", {"t": now - 3 * 86400, "version": "0.8.189", "connected": False,
                                         "in_game": False, "status": "Disconnected"})
ancient = mk(remote, "data-Old", {"t": now - 30 * 86400, "version": "0.8.50", "connected": False})
missing = mk(remote, "data-Buddy", {"connected": True}, app={"profile": "Buddy pve2"}, mtime=now - 5)
broken = mk(remote, "data-Broken", raw="{not json")
hung = mk(remote, "data-Hung", {"t": now - 4, "connected": False, "in_game": False, "hung_up": True,
                                "name": "Evolution", "status": "Disconnected"})
odd = mk(remote, "data-Odd", {"t": now - 2, "name": "Bad\x1b[31mName" + "x" * 500, "hp": "lots", "room": [1, "x"],
                              "connected": "yes", "password": "hunter2", "exp_hr": True, "status": "Idle"})
local_install = os.path.join(tmp, "Local", "MudPilot")
local_data = mk(local_install, "data", {"t": now - 1, "connected": True, "in_game": True, "walking": False,
                                        "status": "Resting (HP 10/20)", "name": "Desktop", "version": "0.8.201"})

# ---- reading a folder
r = O.read_folder(fresh, now)
check("fresh row: name from status", r["name"] == "Miserable")
check("fresh row: looping state", r["state"] == "loop" and "Stonecaps" in r["doing"])
cols = O.columns(r)
check("fresh row: realm column shows board + PvP", cols[1] == "Paradigm PvP")
check("fresh row: level/class column", cols[2] == "47 Mage")
check("fresh row: HP shows current/max", cols[3] == "87% 619/713")
check("fresh row: where shows room name and number", cols[5] == "Stonecap Grotto (14/6551)")
check("fresh row: exp/hr formatted", cols[7] == "1.84M")
check("fresh row: version", cols[9] == "0.8.201")

r = O.read_folder(stale, now)
check("stale row: grey 'stale' state after 75 s", r["state"] == "stale" and "no word for" in r["doing"])
check("old status (no name): profile + folder label", r["name"] == "MiserablePVE (PVE)")

r = O.read_folder(offline, now)
check("offline row: not running, last seen days ago", r["state"] == "offline" and "days" in r["doing"])

r = O.read_folder(missing, now)
check("missing fields: name from app.json profile", r["name"] == "Buddy pve2 (Buddy)")
check("missing fields: no 't' → age from the file's own time", r["age"] is not None and 0 <= r["age"] < 60)
check("missing fields: columns all render", all(isinstance(c, str) for c in O.columns(r)))

r = O.read_folder(broken, now)
check("unreadable status.json: offline row, no crash", r is not None and r["state"] == "offline")

r = O.read_folder(hung, now)
check("hung up shows as hung", r["state"] == "hung" and "hung up" in r["doing"])

r = O.read_folder(odd, now)
check("odd values: wrong types dropped", "hp" not in r["d"] and "room" not in r["d"] and "connected" not in r["d"]
      and "exp_hr" not in r["d"])
check("odd values: unknown keys (password) never kept", "password" not in r["d"])
check("odd values: control chars stripped, string cut short", "\x1b" not in r["name"] and len(r["name"]) <= O.STR_MAX)

check("no control folder → no row", O.read_folder(os.path.join(tmp, "nothing"), now) is None)

big = mk(remote, "data-Big", raw=json.dumps({"t": now, "status": "x" * (O.MAX_FILE + 10)}))
check("oversized status.json ignored", O.read_folder(big, now)["state"] == "offline")
import shutil; shutil.rmtree(big)

# a status written on a PC whose clock is ahead: fall back to the file time
ahead = mk(remote, "data-Ahead", {"t": now + 3600, "connected": True, "in_game": True, "name": "Ahead"}, mtime=now - 2)
r = O.read_folder(ahead, now)
check("clock ahead: file time used, not shown as stale/negative", r["state"] != "stale" and 0 <= r["age"] < 60)
shutil.rmtree(ahead)

# ---- activity states
A = O.activity
check("in combat → fight", A({"t": 1, "connected": True, "in_game": True, "in_combat": True, "status": "Casting"}, 5)[0] == "fight")
check("resting → rest", A({"t": 1, "connected": True, "in_game": True, "status": "Resting (HP 1/2)"}, 5)[0] == "rest")
check("go to → walking to", A({"t": 1, "connected": True, "in_game": True, "walking": True, "path": "Go to 1/2"}, 5)
      == ("walk", "walking: to 1/2"))
check("at the BBS menu", A({"t": 1, "connected": True, "in_game": False}, 5) == ("down", "at the BBS menu"))
check("stopped", A({"t": 1, "connected": True, "in_game": True, "walking": False, "status": "Idle"}, 5) == ("idle", "stopped"))
check("dead", A({"t": 1, "connected": True, "in_game": True, "dead": True}, 5)[0] == "dead")
check("no status at all", A({}, None)[0] == "offline")

# ---- finding folders
found = O.expand(remote)
check("install folder expands to its data* folders", O._key(fresh) in {O._key(f) for f in found} and len(found) >= 7)
check("a single data folder is itself", O.expand(fresh) == [fresh])
check("a control folder → its data folder", O._key(O.expand(os.path.join(fresh, "control"))[0]) == O._key(fresh))
check("drive root finds <x>\\<y>\\data*", O._key(fresh) in {O._key(f) for f in O.expand(os.path.join(tmp, "M"))})
check("missing folder → nothing", O.expand(os.path.join(tmp, "nope")) == [])
check("local roots: this data folder and its siblings", O._key(local_data) in {O._key(f) for f in O.local_roots(local_data)})

# ---- prefs (only this PC's own data folder)
check("prefs default: no folders, listen off", O.load_prefs(local_data) == {"folders": [], "listen": False,
                                                                            "port": O.UDP_PORT, "show_old": False})
O.save_prefs({"folders": [remote], "listen": False, "port": 99, "show_old": False}, local_data)
p = O.load_prefs(local_data)
check("prefs round trip; bad port → default", p["folders"] == [remote] and p["port"] == O.UDP_PORT)
json.dump({"folders": "C:\\", "listen": "yes"}, open(O.prefs_path(local_data), "w"))
p = O.load_prefs(local_data)
check("odd prefs file: listen only on a real true", p["listen"] is False)

# ---- scanner (worker threads) + merge
sc = O.Scanner(local_data)
sc.scan([remote])
t0 = time.time()
while (sc.busy or not sc.results) and time.time() - t0 < 10:
    time.sleep(0.05)
time.sleep(0.2)
while sc.busy and time.time() - t0 < 10:
    time.sleep(0.05)
rows = O.merge(sc.rows([remote]))
names = [x["name"] for x in rows]
check("scanner finds local + remote characters", "Desktop" in names and "Miserable" in names)
check("week-old folders hidden by default", not any("Old" in n for n in names))
check("…and shown with Show old", any("Old" in x["name"] for x in sc.rows([remote], show_old=True)))
check("live rows sorted before offline ones",
      [x["state"] for x in rows].index("offline") > names.index("Miserable"))
check("removed entry's rows drop out", all(x["name"] != "Miserable" for x in sc.rows([])))
sc.close()

# ---- LAN packet
d = {"t": now, "name": "Miserable", "status": "Walking", "hp": 10, "max_hp": 20, "password": "hunter2",
     "chat": "secret words", "room": [1, 2]}
raw = O.packet(d)
check("packet: small", len(raw) <= O.UDP_MAX)
check("packet: no password / chat", b"hunter2" not in raw and b"secret" not in raw)
check("packet: parse from a LAN address", (O.parse_packet(raw, "192.168.1.20") or {}).get("name") == "Miserable")
check("packet: refused from a public address", O.parse_packet(raw, "8.8.8.8") is None)
check("packet: refused from a Tailscale/CGNAT address", O.parse_packet(raw, "100.64.0.12") is None)
check("packet: refused without the magic", O.parse_packet(b'{"name":"x"}', "10.0.0.5") is None)
check("packet: refused when too big", O.parse_packet(b" " * (O.UDP_MAX + 1), "10.0.0.5") is None)
check("packet: garbage refused", O.parse_packet(b"\xff\xfe", "10.0.0.5") is None)
lis = O.UdpListener(0)
for i in range(O.UDP_MAX_SENDERS + 5):
    lis.take(O.packet({"name": f"N{i}"}), "10.0.0.5")
check("listener: at most 64 senders", len(lis.got) == O.UDP_MAX_SENDERS)
lr = lis.rows()
check("listener rows are 'udp' rows, fresh", lr and lr[0]["via"] == "udp" and lr[0]["age"] < 5)
# same character by folder and by packet → shown once
lis2 = O.UdpListener(0)
lis2.take(O.packet({"name": "Miserable", "board": "Paradigm", "connected": True}), "192.168.1.9")
m = O.merge([O.read_folder(fresh, now)] + lis2.rows())
check("merge: folder + packet of the same character shows once", len(m) == 1 and m[0]["via"] == "folder")
m = O.merge([O.read_folder(stale, now), O.read_folder(offline, now)])
check("merge: two folders never merged", len(m) == 2)

# real socket round trip on loopback (listener bound to a free port, sender aimed at 127.0.0.1)
probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); probe.bind(("127.0.0.1", 0))
port = probe.getsockname()[1]; probe.close()
lis3 = O.UdpListener(port)
if lis3.start():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
        u.sendto(O.packet({"name": "Loopy", "t": now}), ("127.0.0.1", port))
    t0 = time.time()
    while not lis3.got and time.time() - t0 < 3:
        time.sleep(0.05)
    check("listener receives a real packet", any(n == "Loopy" for (_ip, n) in lis3.got))
    lis3.stop()
else:
    check("listener could bind a free port (" + lis3.error + ")", False)
O.send_status({"name": "x"}, port)           # broadcast must never raise
check("send_status never raises", True)

# ---- control.py: the extra fields in status.json, never secrets
from mudpilot import control
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_class = "Mage"
s = Session(st)
st.board = "Paradigm"          # set after the Session opened its board (the test board stays Main)
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()
box = control.ControlBox(s, folder=os.path.join(tmp, "ctl-test", "control"))
s.state.hp, s.state.max_hp, s.state.level = 50, 100, 47
box.write_status()
w = json.load(open(os.path.join(box.dir, "status.json"), encoding="utf-8"))
check("status.json: name/board/level/class/hp written", w.get("name") == "Miserable" and w.get("board") == "Paradigm"
      and w.get("level") == 47 and w.get("cls") == "Mage" and w.get("max_hp") == 100)
check("status.json: still has the old keys (minipc/rollout)", all(k in w for k in ("t", "version", "connected",
                                                                                  "in_game", "walking", "status")))
txt = json.dumps(w).lower()
check("status.json: no password/username keys", "password" not in txt and "username" not in txt)
check("status broadcast off by default", st.status_broadcast is False)
r = O.read_folder(os.path.dirname(box.dir), time.time())
check("written status reads back as a row", r["name"] == "Miserable" and r["state"] != "offline")

# ---- headless window build
import tkinter as tk
try:
    root = tk.Tk()
    root.withdraw()
except tk.TclError as ex:
    root = None
    check("Tk available (" + str(ex) + ")", False)
if root is not None:
    O.save_prefs({"folders": [remote], "listen": False}, local_data)
    pane = O.OverviewPane(root, data_dir=local_data, auto=False)
    pane.pack(fill="both", expand=True)
    pane.scanner.scan(pane.prefs["folders"])
    t0 = time.time()
    while time.time() - t0 < 10:
        time.sleep(0.1)
        if not pane.scanner.busy and len(pane.scanner.results) >= 7:
            break
    pane.refresh()
    kids = pane.tree.get_children()
    check("window: one row per character", len(kids) >= 6)
    vals = [pane.tree.item(k, "values")[0] for k in kids]
    check("window: Miserable row present", "Miserable" in vals)
    k = next(k for k in kids if pane.tree.item(k, "values")[0] == "Miserable")
    check("window: row tagged with its state colour", pane.tree.item(k, "tags")[0] == "loop")
    k2 = next(k for k in kids if "revolution" in pane.tree.item(k, "values")[0])
    check("window: offline row tagged offline (red)", pane.tree.item(k2, "tags")[0] == "offline")
    pane.tree.selection_set(k)
    pane._show_detail()
    check("window: detail line shows source folder", "folder" in pane.v_detail.get())
    check("window: footer counts running", "running" in pane.v_foot.get())
    pane.refresh()                       # second refresh updates in place
    check("window: refresh keeps rows (no duplicates)", len(pane.tree.get_children()) == len(kids))
    dlg = pane.edit_folders()
    dlg.destroy()
    pane.set_folders([remote, remote.upper()])
    check("window: folder list de-duplicated", len(pane.prefs["folders"]) == 1)
    check("window: listener off by default", pane.listener is None)
    root.update()
    root.destroy()
    check("window: closing stops its scanner", pane.scanner.closed)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
