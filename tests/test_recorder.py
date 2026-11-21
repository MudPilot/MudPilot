"""Session recorder: writes rx/tx/log/decisions, never a password; replay reads it back."""
import json, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("MUDPILOT_NO_RECORD", None)
from mudpilot import config, recorder
tmp = tempfile.mkdtemp()
recorder.trace_dir = lambda: tmp
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.username = "dan"
s = Session(st)
s.password = "hunter2"
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): pass
s.telnet = Tel()
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
rec = s.recorder
rec.mark("connect")
rec.rx("Enter your password: ")
s.send("whatever-I-typed")
rec.rx("[HP=684/MA=473]:")
s.send("hunter2")
s.send("esto")
rec.rx("Recover Password:    123456\r\n")
s.decide("cast", spell="esto")
s.log("hello log")
p = rec.flush_now()
time.sleep(0.3); rec.flush_now()
text = open(rec.path, encoding="utf-8").read()
recs = [json.loads(l) for l in text.splitlines()]
check("recording written", recs and recs[0]["k"] == "head")
check("typed at the password prompt → hidden", "whatever-I-typed" not in text)
check("your saved password → hidden", "hunter2" not in text)
check("a password the game prints → hidden", "123456" not in text)
check("commands kept", any(r["k"] == "tx" and r["d"] == "esto" for r in recs))
check("decisions kept", any(r["k"] == "dec" and r["d"].get("spell") == "esto" for r in recs))
check("log kept", any(r["k"] == "log" and r["d"] == "hello log" for r in recs))
check("user name not in the settings copy", '"username": "dan"' not in text)
from mudpilot.replay import load
check("replay reads it", len(load(rec.path)) == len(recs))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
