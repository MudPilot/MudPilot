"""Dan, 2026-11-13: Revolution's PC lost power; PVEREV came back on its 'PVEREV' profile (last saved Oct 30) instead of
'Revolution', the profile it had run on for two weeks: no blesses, no @ players. Now the profile the last run had open
(control/status.json, written every 30 s) wins over app.json when it's the newer of the two, the log says which
settings opened, and Game Data's players file is flushed to the disk like the profiles."""
import json, os, sys, tempfile, time, shutil
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
D = os.path.join(tempfile.gettempdir(), "mudpilot_test_profile_kept")
shutil.rmtree(D, ignore_errors=True)
os.environ["MUDPILOT_DATA_DIR"] = D
from mudpilot import config
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

os.makedirs(os.path.join(D, "profiles"), exist_ok=True)
os.makedirs(os.path.join(D, "control"), exist_ok=True)
for name, buffs in (("PVEREV", []), ("Revolution", [{"cast": "bless"}, {"cast": "halo"}])):
    with open(os.path.join(D, "profiles", name + ".json"), "w", encoding="utf-8") as f:
        json.dump({"username": "rev", "my_name": "Revolution", "buffs": buffs, "settings_version": config.Settings.settings_version}, f)
app_json = os.path.join(D, "app.json")
status = os.path.join(D, "control", "status.json")

def write(p, d, t):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.utime(p, (t, t))

now = time.time()
# the power cut: app.json names the stale profile, the last run had 'Revolution' open (status is newer)
write(app_json, {"profile": "PVEREV"}, now - 3600)
write(status, {"t": now, "profile": "Revolution"}, now - 60)
config.Settings._profile_note = ""
s = config.Settings.load()
check(f"the profile that was running opens ({s.profile})", s.profile == "Revolution")
check(f"…with its settings ({s.buffs if hasattr(s, 'buffs') else '?'})", [b.get("cast") for b in getattr(s, "buffs", [])] == ["bless", "halo"])
check(f"…and says why ({config.Settings._profile_note!r})", "PVEREV" in config.Settings._profile_note
      and "Revolution" in config.Settings._profile_note)
check(f"the log line names it with its save time ({s.describe()})", s.describe().startswith("Revolution (saved "))

# a character picked on purpose since (app.json newer than the status file): that one stands
write(app_json, {"profile": "PVEREV"}, now)
write(status, {"t": now - 30, "profile": "Revolution"}, now - 30)
config.Settings._profile_note = ""
s = config.Settings.load()
check(f"picked on purpose since: app.json's profile stands ({s.profile})", s.profile == "PVEREV" and
      not config.Settings._profile_note)

# the status names a profile that's gone: app.json's
write(app_json, {"profile": "PVEREV"}, now - 3600)
write(status, {"t": now, "profile": "Deleted"}, now - 60)
s = config.Settings.load()
check(f"a profile that's not there any more is ignored ({s.profile})", s.profile == "PVEREV")

# no status file at all (first run): app.json
os.remove(status)
s = config.Settings.load()
check(f"no status file: app.json ({s.profile})", s.profile == "PVEREV")

# Game Data's players file goes through the safe writer
import inspect
from mudpilot import players
check("players.json is written with the flushed safe writer", "_write_safely" in inspect.getsource(players.PlayerDB.save))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
