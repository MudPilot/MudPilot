"""Build the compiled MudPilot (no source inside) for players outside the house:

    <build venv python> build_exe/build.py [--skip-compile]

Nuitka compiles mudpilot\\ to machine code (Zig as the C compiler) into a standalone folder with its own Python;
that becomes app\\<version>\\, with the Zig-built starter (build_exe/starter.c) as MudPilot.exe on top. Out comes
dist\\MudPilot-<version>.zip — the first install (unzip, run MudPilot.exe) and every update (drop it in Downloads)
are the same zip. The build venv needs: nuitka, ziglang, and requirements.txt.

Run on Linux (WSL is fine) it makes dist/MudPilot-<version>-linux.zip instead: the same app/<version>/ layout, with
build_exe/starter.sh as the 'MudPilot' starter on top. Linux needs gcc and patchelf, and a Python with Tk
(python3-tk); build on an older distro (Ubuntu 22.04) so the result runs on the newer ones too.

Run on macOS it makes dist/MudPilot-<version>-mac-arm64.zip (Apple Silicon) or -mac-x64.zip (Intel), the Linux layout
with the same starter.sh; it needs Xcode's command-line tools (clang) and a python.org-style Python with Tk.
GitHub builds those on its macOS runners (.github/workflows/macos.yml)."""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
WORK = os.path.join(HERE, "work")
DIST = os.path.join(SRC, "dist")
GUIDES = ("MudPilot Setup Guide.pdf", "MudPilot Setup Guide.docx")
WIN = os.name == "nt"
MAC = sys.platform == "darwin"
EXE = "MudPilot.exe" if WIN else "MudPilot"


def version() -> str:
    with open(os.path.join(SRC, "mudpilot", "__init__.py"), encoding="utf-8") as f:
        return re.search(r'__version__\s*=\s*"([^"]+)"', f.read()).group(1)


def mac_arch() -> str:
    return "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"


def run(cmd, **kw):
    print(">", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def compile_app():
    cmd = [sys.executable, "-m", "nuitka", "--standalone", "--assume-yes-for-downloads",
           "--enable-plugin=tk-inter", "--include-package=mudpilot", "--include-package-data=mudpilot",
           "--nofollow-import-to=tests", "--include-package=keyring", "--include-package=access_parser",
           "--no-deployment-flag=self-execution",   # (the launcher runs '<exe> -m …')
           "--python-flag=no_docstrings",       # (they're the design notes; nothing reads them)
           "--output-filename=" + EXE, "--output-dir=" + WORK, "--remove-output"]
    if WIN:
        cmd += ["--zig", "--windows-console-mode=disable",
                "--windows-icon-from-ico=" + os.path.join(SRC, "mudpilot", "assets", "mudpilot.ico"),
                "--product-name=MudPilot", "--file-version=" + version(), "--product-version=" + version()]
    elif not MAC:
        # keyring's Linux store (GNOME Keyring / KWallet over D-Bus)
        cmd += ["--include-package=secretstorage", "--include-package=jeepney"]
    run(cmd + [os.path.join(HERE, "mudpilot_boot.py")], cwd=SRC)


def starter(out):
    if not WIN:
        out = os.path.join(os.path.dirname(out), "MudPilot")
        with open(os.path.join(HERE, "starter.sh"), "rb") as f:
            data = f.read().replace(bytes([13, 10]), bytes([10]))
        with open(out, "wb") as f:
            f.write(data)
        os.chmod(out, 0o755)
        return
    run([sys.executable, "-m", "ziglang", "cc", "-target", "x86_64-windows-gnu", "-O2", "-municode",
         "-Wl,--subsystem,windows", "starter.c", "starter.rc", "-o", out], cwd=HERE)


def main(argv):
    v = version()
    if "--skip-compile" not in argv:
        compile_app()
    built = os.path.join(WORK, "mudpilot_boot.dist")
    stage = os.path.join(WORK, "stage", "MudPilot")
    shutil.rmtree(os.path.join(WORK, "stage"), ignore_errors=True)
    shutil.copytree(built, os.path.join(stage, "app", v))
    with open(os.path.join(stage, "app", v, "version.txt"), "w", encoding="utf-8") as f:
        f.write(v + "\n")
    starter(os.path.join(stage, "MudPilot.exe"))
    for n in os.listdir(stage):
        if n.lower().endswith((".pdb", ".lib")):
            os.remove(os.path.join(stage, n))        # (Zig's debug files)
    for g in GUIDES:
        if os.path.exists(os.path.join(SRC, g)):
            shutil.copy2(os.path.join(SRC, g), stage)
    # no source in the zip — that's the point
    leaks = [os.path.relpath(os.path.join(d, n), stage) for d, _s, fs in os.walk(stage) for n in fs
             if n.endswith((".py", ".pyc", ".pyw")) and "mudpilot" in os.path.relpath(d, stage).lower()]
    if leaks:
        raise SystemExit("Source in the build: " + ", ".join(leaks[:10]))
    os.makedirs(DIST, exist_ok=True)
    zp = os.path.join(DIST, f"MudPilot-{v}.zip" if WIN else f"MudPilot-{v}-mac-{mac_arch()}.zip" if MAC
                      else f"MudPilot-{v}-linux.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for d, _s, fs in os.walk(stage):
            for n in fs:
                full = os.path.join(d, n)
                z.write(full, os.path.join("MudPilot", os.path.relpath(full, stage)).replace("\\", "/"))
    print(f"{zp}  {os.path.getsize(zp) / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1:])
