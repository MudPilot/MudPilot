"""ntfy phone alerts: hang-up / PvP posts to the topic, rate-limited, never the password."""
import os, sys, time, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, notify
from mudpilot.session import Session
got = []
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        got.append((self.path, self.headers.get("Title"), self.rfile.read(n).decode()))
        self.send_response(200); self.end_headers()
    def log_message(self, *a): pass
srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
notify.get_topic = lambda: "dans-secret-topic"
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
st.ntfy_on = True; st.ntfy_server = f"http://localhost:{srv.server_port}"
s = Session(st)
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
def wait_for(n, secs):
    t0 = time.time()           # Windows tries 'localhost' as IPv6 first: a post can take a second or two
    while len(got) < n and time.time() - t0 < secs:
        time.sleep(0.05)
s.safety.hangup("HP 100/674 below 25%")
wait_for(1, 5)
check(f"hang-up alert posted ({got})", got and got[0][0] == "/dans-secret-topic" and "Hung up" in got[0][2]
      and got[0][1].startswith("Miserable"))
s.safety.hangup("again")
wait_for(2, 3)
check("rate limited (one per 30 s per kind)", len(got) == 1)
st.ntfy_kinds = ["pvp"]
s.notify._last.clear(); s.telnet.connected = True
s.safety.hangup("x"); wait_for(2, 3)
check("kind unticked → no alert", len(got) == 1)
st.ntfy_server = "http://example.com"
check("plain http to another host refused", not s.notify.send("pvp", "x"))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
