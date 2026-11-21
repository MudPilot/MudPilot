"""Phone page (webremote): off by default, never listens on every address, pairing code → key, every data request
needs the key, watch-only (no POST but pairing), the screen feed, the other MudPilots on this PC."""
import json, os, sys, tempfile, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, webremote
from mudpilot.ansi import Style
from mudpilot.session import Session

ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

# never touch the real Credential Manager in a test
vault = {}
config.get_password = lambda user: vault.get(user)
def _setpw(user, pw):
    if pw is None:
        vault.pop(user, None)
    else:
        vault[user] = pw
    return True
config.set_password = _setpw

root = tempfile.mkdtemp()
config.DATA_DIR = os.path.join(root, "data")
os.makedirs(os.path.join(config.DATA_DIR, "control"))
sib = os.path.join(root, "data-Buddy", "control")
os.makedirs(sib)
json.dump({"t": time.time(), "name": "Buddy", "connected": True, "in_game": True, "exp_hr": 446000,
           "status": "Fighting troll", "hp_pct": 80}, open(os.path.join(sib, "status.json"), "w"))
json.dump({"port": 8799, "t": time.time()}, open(os.path.join(sib, "web.json"), "w"))

st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st)
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()

check("off by default", st.web_on is False)
s.web.tick()
check("nothing listening while off", s.web.server is None)
check("won't listen on every address", not webremote.bind_ok("0.0.0.0") and not webremote.bind_ok("::"))
check("tailnet / loopback / LAN addresses allowed", webremote.bind_ok("100.70.1.2") and webremote.bind_ok("127.0.0.1")
      and webremote.bind_ok("192.168.1.20"))
check("public address refused", not webremote.bind_ok("8.8.8.8"))

st.web_on, st.web_bind = True, "0.0.0.0"
s.web.tick()
check("0.0.0.0 in Settings refused, not started", s.web.server is None and "won't listen" in s.web.state)

st.web_bind = "127.0.0.1"
s.web._next_try = 0
s.web.tick()
check("started on loopback", s.web.server is not None and s.web.addr == "127.0.0.1")
base = s.web.url
check("key made and kept in the vault", bool(vault.get(webremote.SECRET_USER)))
wj = json.load(open(os.path.join(config.DATA_DIR, "control", "web.json")))
check("port written to the control folder", wj.get("port") == s.web.port)


def req(path, key=None, data=None):
    h = {"X-MudPilot-Key": key} if key else {}
    if data is not None:
        h["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    r = urllib.request.Request(base.rstrip("/") + path, data=data, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


code, body, hd = req("/")
check("page served without a key (it holds no data)", code == 200 and b"MudPilot" in body)
check("strict CSP: no inline script", "script-src 'self'" in (hd.get("Content-Security-Policy") or ""))
code, body, hd = req("/app.js")
check("app.js served", code == 200 and b"/api/peers" in body)
check("no data without the key", req("/api/me")[0] == 403 and req("/api/screen")[0] == 403
      and req("/api/peers")[0] == 403)
check("wrong key refused", req("/api/me", key="nope")[0] == 403)
check("pairing with no code shown fails", req("/api/pair", data={"code": "123456"})[0] == 403)

c = s.web.pair_code()
check("6-digit code", len(c) == 6 and c.isdigit())
wrong = "000000" if c != "000000" else "111111"
check("wrong code refused", req("/api/pair", data={"code": wrong})[0] == 403)
code, body, _ = req("/api/pair", data={"code": c})
key = json.loads(body).get("key") if code == 200 else None
check("right code gives the key", key == vault.get(webremote.SECRET_USER))
check("code works once", req("/api/pair", data={"code": c})[0] == 403)

c2 = s.web.pair_code()
w2 = "000000" if c2 != "000000" else "111111"
for _ in range(webremote.CODE_TRIES):
    req("/api/pair", data={"code": w2})
check("5 wrong tries burn the code", s.web.code is None and req("/api/pair", data={"code": c2})[0] == 403)
s.web.fails.clear(); s.web.blocked.clear()

s.state.hp, s.state.max_hp = 500, 812
s.web._snap_at = 0
s.web.tick()
code, body, _ = req("/api/me", key=key)
me = json.loads(body)
check("me: name and HP", code == 200 and me.get("name") == "Miserable" and me.get("hp") == 500)

s.web.clear()
s.web.add_line([("You gain 3,120 experience.", Style(2, True))])
s._line([("Obvious exits: north, south", Style(6, False))])
code, body, _ = req("/api/screen?since=0", key=key)
sc = json.loads(body)
txt = " ".join(seg[0] for ln in sc["lines"] for seg in ln)
check("screen: lines and colours", "3,120 experience" in txt and "Obvious exits" in txt
      and sc["lines"][0][0][1:] == [2, True])
code, body, _ = req(f"/api/screen?since={sc['seq']}", key=key)
check("screen: nothing new since seq", json.loads(body)["lines"] == [] and not json.loads(body)["reset"])
s._line([("Recover Password: hunter2", Style(7, False))])
code, body, _ = req(f"/api/screen?since={sc['seq']}", key=key)
check("recover password stays hidden on the phone", b"hunter2" not in body)

code, body, _ = req("/api/peers", key=key)
peers = json.loads(body)["peers"]
names = [p.get("name") for p in peers]
check("peers: me first, then Buddy", names[:2] == ["Miserable", "Buddy"])
bud = peers[1]
check("peers: Buddy's port and exp/hr", bud["port"] == 8799 and bud["exp_hr"] == 446000 and bud["fresh"])

check("watch-only: no other POST", req("/api/stop", key=key, data={})[0] == 404)

for _ in range(webremote.FAIL_MAX):
    req("/api/me", key="bad")
check("an address that keeps failing is shut out", req("/api/me", key=key)[0] == 403)
s.web.blocked.clear(); s.web.fails.clear()

old = key
s.web.forget_phones()
check("forget all phones: old key stops working", req("/api/me", key=old)[0] == 403)

st.web_on = False
s.web.tick()
time.sleep(1.2)
check("unticked: stops", s.web.server is None)
try:
    urllib.request.urlopen(base, timeout=2)
    gone = False
except Exception:
    gone = True
check("unticked: port closed", gone)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
