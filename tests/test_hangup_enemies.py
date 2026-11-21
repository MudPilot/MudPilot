"""Hang up on nobody by default; only on players marked Enemy (and an old 'Users' setting is turned off once)."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
d = tempfile.mkdtemp()
config.Settings.profile_path = classmethod(lambda cls, p: os.path.join(d, p + ".json"))
json.dump({"hangup_on_player": True, "settings_version": 12,
           "mode_defaults": {"auto": {"hangup_on_player": True}, "manual": {"hangup_on_player": True}}},
          open(os.path.join(d, "Old.json"), "w"))
s = config.Settings.load("Old")
check("old 'hang up on any player' turned off once", s.hangup_on_player is False)
check("…in the Auto/Manual mode defaults too", not any(m.get("hangup_on_player") for m in s.mode_defaults.values()))
check("enemies still hang up", s.hangup_on_enemy)
check("a new character: off", config.Settings().hangup_on_player is False)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
