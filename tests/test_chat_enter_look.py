"""0.8.227.6 (Dan: "after i just killed bloody executioner on pve... enter from the convo box had no effect i
couldn't check the room to see if anything dropped... It worked when i clicked the box below the mud window"): an
empty Enter in the conversation window's box is a look, like the command line's."""
import os, sys, tempfile, types
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_chat_enter"))
import tkinter as tk
from mudpilot import config
from mudpilot.session import Session
from mudpilot.windows import ChatPane
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.telnet = types.SimpleNamespace(connected=True)
s.send = lambda c, from_bot=False: sent.append(c)
root = tk.Tk(); root.withdraw()
app = types.SimpleNamespace(s=s, root=root, _last_input=0)
pane = ChatPane(root, app)
pane.entry.delete(0, "end")
pane.send()
check(f"empty Enter in the conversation box: a look ({sent})", sent == [""])
sent.clear(); pane.entry.insert(0, "gos hi"); pane.send()
check(f"typed text still goes as typed ({sent})", sent == ["gos hi"] and pane.entry.get() == "")
s.telnet.connected = False; sent.clear(); pane.send()
check("not connected: nothing sent", not sent)
root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
