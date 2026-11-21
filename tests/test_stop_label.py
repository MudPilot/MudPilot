"""The Stop button says Stop only while walking; a stopped character shows 'Stopped' (Dan, 2026-11-03: "makes me
think he's trying to go somewhere"); something to resume shows Rego."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import app as A
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
class Btn:
    def configure(self, **k): self.k = k
def label(walking, resume):
    o = type("O", (), {})()
    o.s = type("S", (), {"bot": type("B", (), {"walking": walking, "resume": resume})()})()
    o.btn_stop = Btn()
    A.App._stop_btn_refresh(o)
    return o.btn_stop.k["text"]
check("walking: Stop", "Stop" in label(True, None))
check("walking with a resume: Stop", "Stop" in label(True, {"x": 1}))
check("standing still: Stopped", label(False, None) == "Stopped")
check("stopped with something to resume: Rego", "Rego" in label(False, {"x": 1}))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
