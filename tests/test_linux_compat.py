"""Linux build pieces: the starter script, the font mapping, the zip names and 'can run' bits."""
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mudpilot import config, launcher  # noqa: E402


def test_starter_script():
    b = open(os.path.join(ROOT, "build_exe", "starter.sh"), "rb").read()
    assert b.startswith(b"#!/bin/sh\n")
    assert b"\r" not in b, "the Linux starter must have Unix line endings"
    assert b'-m mudpilot.launcher "$@"' in b


def test_font_conf():
    p = os.path.join(ROOT, "mudpilot", "assets", "fonts-linux.conf")
    root = ET.parse(p).getroot()
    fams = {s.text for s in root.iter("string")}
    assert {"Consolas", "Segoe UI", "monospace", "sans-serif"} <= fams
    assert root.find("include").text == "/etc/fonts/fonts.conf"


def test_zip_names():
    import re
    win = re.compile(r"^MudPilot-(\d+(?:\.\d+)+)\.zip$", re.I)
    assert launcher.ZIP_RE.pattern == win.pattern          # from source on any system: the plain zip
    assert not win.match("MudPilot-0.8.193-linux.zip")      # a Windows install never takes the Linux zip


def test_keep_mode():
    if os.name == "nt":
        return
    with tempfile.TemporaryDirectory() as d:
        zp = os.path.join(d, "z.zip")
        src = os.path.join(d, "prog")
        open(src, "w").write("x")
        os.chmod(src, 0o755)
        with zipfile.ZipFile(zp, "w") as z:
            z.write(src, "prog")
        out = os.path.join(d, "out")
        with zipfile.ZipFile(zp) as z:
            zi = z.getinfo("prog")
            open(out, "wb").write(z.read(zi))
            launcher._keep_mode(zi, out)
        assert os.stat(out).st_mode & 0o111


def test_open_path_exists():
    assert callable(config.open_path)
    assert config.EXE_NAME == ("MudPilot.exe" if os.name == "nt" else "MudPilot")


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
    print("ok")
