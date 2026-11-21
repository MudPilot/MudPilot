"""0.8.200 (Dan): tell players when a newer MudPilot is out, with What's new / Update / Skip. Faked GitHub answers."""
import io, json, os, sys, tempfile, types, zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tkinter as tk
from tkinter import ttk
from mudpilot import updater, __version__
from mudpilot.app import App
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

def fake_release(ver, assets):
    body = json.dumps({"tag_name": "v" + ver, "html_url": "https://github.com/MudPilot/MudPilot/releases/tag/v" + ver,
                       "body": "## What's new\n- things", "assets": assets}).encode()
    class R(io.BytesIO):
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *a): return False
    return lambda req, timeout=0: R(body)

real = updater.urllib.request.urlopen
try:
    updater.urllib.request.urlopen = fake_release("0.8.1", [])
    check("older release: nothing to say", updater.check() is None)
    name = "MudPilot-9.9.9-linux.zip" if updater.LINUX else "MudPilot-9.9.9.zip"
    url = "https://github.com/MudPilot/MudPilot/releases/download/v9.9.9/" + name
    updater.urllib.request.urlopen = fake_release("9.9.9", [{"name": name, "browser_download_url": url, "size": 10},
                                                            {"name": "other.zip", "browser_download_url": "x"}])
    info = updater.check()
    check(f"newer release found, this system's zip picked ({info})", info and info["version"] == "9.9.9" and info["asset"] == url)
    # download: only from the release host, and only a real MudPilot zip
    try:
        updater.download({**info, "asset": "https://evil.example/x.zip"})
        check("refuses a download from anywhere else", False)
    except ValueError:
        check("refuses a download from anywhere else", True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("MudPilot/README.md", "hi")
    data = buf.getvalue()
    class D(io.BytesIO):
        headers = {"Content-Length": str(len(data))}
        def __enter__(self): return self
        def __exit__(self, *a): return False
    updater.urllib.request.urlopen = lambda req, timeout=0: D(data)
    tmpd = tempfile.mkdtemp()
    real_dir = updater.download_dir
    updater.download_dir = lambda: tmpd
    p = updater.download(info)
    check(f"downloaded beside the install as {os.path.basename(p)}", os.path.exists(p) and not os.path.exists(p + ".part"))
    updater.download_dir = real_dir
finally:
    updater.urllib.request.urlopen = real

# the bar
root = tk.Tk(); root.withdraw()
saved = []
settings = types.SimpleNamespace(update_skip="", save=lambda: saved.append(1))
info_row = ttk.Frame(root); info_row.pack()
stub = types.SimpleNamespace(root=root, s=types.SimpleNamespace(settings=settings), toolbar=ttk.Frame(root),
                             _info_row=info_row, add_log=lambda m: None, _restart_quit=lambda: None)
App._update_bar(stub, {"version": "9.9.9", "url": "", "notes": "notes", "asset": None, "size": 0})
root.update()
bar = stub._upd_bar
texts = [w.cget("text") for w in bar.winfo_children()]
check(f"bar shows the versions and buttons ({texts})",
      any("9.9.9" in t and __version__ in t for t in texts) and {"What's new", "Update", "Skip this version"} <= set(texts))
skipb = next(w for w in bar.winfo_children() if w.cget("text") == "Skip this version")
skipb.invoke()
check("Skip remembers the version", settings.update_skip == "9.9.9" and saved)
root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
