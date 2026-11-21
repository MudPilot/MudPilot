"""Report a problem: zip has the screen, log, errors and settings with secrets removed; posts multipart."""
import os, sys, json, zipfile, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, report
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.username = "danmc"; st.my_name = "Miserable"
s = Session(st)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
report.ERRORS.append(("now", "Traceback: boom"))
path = report.build(s, "it walked into a wall", "[HP=600/MA=300]: line one\nline two", True)
z = zipfile.ZipFile(path)
names = set(z.namelist())
check(f"zip has everything ({names})", {"report.txt", "screen.txt", "log.txt", "errors.txt", "settings.json"} <= names)
sj = json.loads(z.read("settings.json"))
check("user name removed", sj["username"] == "(removed)")
check("nothing secret-looking left", all(v == "(removed)" for k, v in sj.items() if "pass" in k.lower()))
check("report says what happened", b"walked into a wall" in z.read("report.txt"))
got = []
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); got.append(self.rfile.read(n))
        self.send_response(204); self.end_headers()
    def log_message(self, *a): pass
srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
report.endpoint = lambda: f"http://127.0.0.1:{srv.server_port}/hook"
res = []
report.send(path, "it walked into a wall", "Miserable", lambda ok_, m: res.append((ok_, m)))
t = time.time()
while not res and time.time() - t < 10: time.sleep(0.05)
check(f"posted ({res})", res and res[0][0] and got and b"payload_json" in got[0] and b"PK" in got[0])
z.close()
os.remove(path)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
