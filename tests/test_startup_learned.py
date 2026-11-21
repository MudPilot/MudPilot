"""Starting up with learned exits on disk (0.8.35 crashed: logged before the log existed)."""
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None
probe = Session(st)
path = probe.learned_file
os.makedirs(os.path.dirname(path), exist_ok=True)
old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
k = next(iter(probe.world.rooms))
try:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([[list(k), "crawl under the rock", list(k[:1] + (k[1] + 1,))]], f)
    s = Session(st)
    ok = any("learned from your paths" in l for l in s.logs)
    print(("PASS " if ok else "FAIL ") + "starts with a learned exit on disk, and says so in the log")
finally:
    if old is None:
        os.remove(path)
    else:
        open(path, "w", encoding="utf-8").write(old)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
