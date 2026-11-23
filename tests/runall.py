"""Run every test (tests/test_*.py and tests/e2e_*.py) one at a time, ~30 min. Prints PASS n / FAIL list.
Usage (from the MudPilot folder):  python tests/runall.py            — all
                                   python tests/runall.py pilot door — only files whose name has 'pilot' or 'door'
Never run two of these at once (they share the Main board's map data)."""
import glob, os, subprocess, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(here)
env = {**os.environ, "MUDPILOT_NO_RECORD": "1", "MUDPILOT_DEFAULT_BOARD": "Main",
       "PYTHONIOENCODING": "utf-8"}   # Windows console is cp1252: '→' in PASS lines would crash the test
files = sorted(glob.glob("tests/test_*.py") + glob.glob("tests/e2e_*.py"))
if sys.argv[1:]:
    files = [f for f in files if any(a in os.path.basename(f) for a in sys.argv[1:])]
ok, bad = 0, []
for f in files:
    try:
        r = subprocess.run([sys.executable, f], env=env, capture_output=True, text=True, timeout=(900 if os.path.basename(f).startswith('e2e_') else 400),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))   # no console flashing per test
        out = r.stdout + r.stderr
        good = r.returncode == 0 and "SOME FAILED" not in out and "Traceback" not in out and \
            not any(l.startswith("FAIL") for l in out.splitlines())
    except subprocess.TimeoutExpired:
        good, out = False, "timed out"
    if good:
        ok += 1
    else:
        bad.append(f)
        print(f"FAIL {f}\n" + "\n".join(l for l in out.splitlines() if l.startswith("FAIL") or "Error" in l)[:2000])
print(f"PASS {ok}  FAIL {len(bad)}: {' '.join(bad)}")
sys.exit(1 if bad else 0)
