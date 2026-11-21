"""Dan, 2026-11-15: '@collect <item>' and '@stash <item>' set a character's auto-get / auto-stash remotely, the same
item rules Game Data → Items writes."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
st.item_rules = ["kobold ear: get"]
s = Session(st); s._no_log_file = True
s.world.gear = {1: {"name": "runed stone cudgel"}, 2: {"name": "stone cudgel"}, 3: {"name": "silver dagger"},
                4: {"name": "silver-threaded armwraps"}}
r, x = s.remote, s.bot.x
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

a = r.c_collect("Miserable", "silver dagger")
check(f"@collect silver dagger ({a}, {st.item_rules})", "silver dagger: get" in st.item_rules and st.auto_loot)
a = r.c_collect("Miserable", "cudgel")
check(f"two cudgels: asks which ({a})", a.startswith("which one?") and "runed stone cudgel" in a)
a = r.c_stash("Miserable", "runed stone cudgel")
check(f"@stash runed stone cudgel ({a}, {st.item_rules})", "runed stone cudgel: get, stash" in st.item_rules)
check("…in the stash list", x.stash_flagged_names() == ["runed stone cudgel"])
a = r.c_stash("Miserable", "list")
check(f"@stash list ({a})", "runed stone cudgel" in a)
a = r.c_stash("Miserable", "off runed stone cudgel")
check(f"@stash off: still picked up, not stashed ({st.item_rules})", "runed stone cudgel: get" in st.item_rules)
a = r.c_collect("Miserable", "silver dagger off")
check(f"@collect … off: back to normal ({st.item_rules})", not any(l.startswith("silver dagger") for l in st.item_rules))
a = r.c_collect("Miserable", "")
check(f"@collect lists ({a})", "kobold ear" in a and "runed stone cudgel" in a)
check("ears untouched", "kobold ear: get" in st.item_rules)
need = {}
r.allowed = lambda who, n, *a, **k: need.setdefault("n", n) and False
r.handle("telepath", "Miserable", "@stash runed stone cudgel") if st.remote_channels.get("telepath") else None
check(f"'@stash <item>' needs the settings permission ({need})", need.get("n") in ("settings", None))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
