"""Every fixture in tests/fixtures (a slice of a real or rebuilt session + what should be sent) is replayed
through MudPilot. A bug fixed from a log becomes one of these and stays fixed."""
import glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot.replay import check_fixture
ok = True
files = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "*.json")))
for fp in files:
    good, why = check_fixture(fp)
    ok &= good
    print(("PASS " if good else "FAIL ") + os.path.basename(fp) + f" ({why})")
print(f"{len(files)} fixtures")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
