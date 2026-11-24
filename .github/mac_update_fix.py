"""The macOS start-up hang fix (splash stuck on 'Opening the gates…'), applied to a MudPilot source tree:
    python mac_update_fix.py <tree>
On macOS a full Tk update() never returns while MudPilot's timers run (the Aqua event source always has another
event), so the splash's update() hangs for ever; and the conversations/map split re-applied itself on every
<Configure>, ~230,000 times in its first 10 s on a Mac. Windows/Linux behave as before."""
import io, os, sys

root = sys.argv[1]


def edit(rel, pairs):
    p = os.path.join(root, rel)
    raw = io.open(p, "rb").read().decode("utf-8")
    crlf = "\r\n" in raw
    s = raw.replace("\r\n", "\n")
    for a, b in pairs:
        if s.count(a) != 1:
            raise SystemExit(f"{rel}: expected one match for {a!r}, found {s.count(a)}")
        s = s.replace(a, b)
    io.open(p, "wb").write((s.replace("\n", "\r\n") if crlf else s).encode("utf-8"))
    print("patched", rel)


edit("mudpilot/splash.py", [
    ("import os\nimport tkinter as tk\n", "import os\nimport sys\nimport tkinter as tk\n"),
    ("            if msg:\n                self.c.itemconfigure(self.text, text=msg)\n            self.win.update()\n",
     "            if msg:\n                self.c.itemconfigure(self.text, text=msg)\n"
     "            if sys.platform == \"darwin\":\n"
     "                # (macOS: a full update() never returns once MudPilot's timers are running — the splash froze\n"
     "                # on 'Opening the gates…'; redrawing is enough there)\n"
     "                self.win.update_idletasks()\n"
     "            else:\n"
     "                self.win.update()\n"),
])
edit("mudpilot/app.py", [
    ("        rside.bind(\"<Configure>\", lambda e: (time.time() - self._layout_t0 < 10 and not self._layout_dragged\n"
     "                                             and self.root.after_idle(self._apply_layout)), add=\"+\")\n",
     "        # (only when its size really changed: on a Mac applying the split fires <Configure> again, ~230,000\n"
     "        # times in the first 10 s)\n"
     "        self._layout_size = None\n\n"
     "        def resized(e):\n"
     "            if time.time() - self._layout_t0 >= 10 or self._layout_dragged or (e.width, e.height) == self._layout_size:\n"
     "                return\n"
     "            self._layout_size = (e.width, e.height)\n"
     "            self.root.after_idle(self._apply_layout)\n"
     "        rside.bind(\"<Configure>\", resized, add=\"+\")\n"),
    ("        self.root.clipboard_append(text)\n        self.root.update()\n",
     "        self.root.clipboard_append(text)\n"
     "        if sys.platform != \"darwin\":\n"
     "            self.root.update()                # (macOS: a full update() can hang; the clipboard keeps it anyway)\n"),
])
