"""The compiled MudPilot.exe's entry point (Nuitka). It stands in for 'pythonw -m …': the launcher starts MudPilot
as '<exe> -m mudpilot' and itself as '<exe> -m mudpilot.launcher', the same as from source."""
import sys


def selftest(out):
    """'<exe> --selftest <file>': every module loads, the bundled MME data opens, Credential Manager answers —
    written to <file> (the exe has no console to print to)."""
    import importlib, os, pkgutil, traceback
    lines, bad = [], 0
    import mudpilot
    lines.append(f"version {mudpilot.__version__}")
    for m in pkgutil.iter_modules(mudpilot.__path__):
        if m.name.startswith("__"):
            continue                                 # (__main__ opens MudPilot)
        try:
            importlib.import_module("mudpilot." + m.name)
        except Exception as ex:
            bad += 1
            lines.append(f"FAIL import {m.name}: {ex!r}")
    try:
        from mudpilot import config
        from mudpilot.worlddb import WorldDB
        w = WorldDB(os.path.join(config.BUNDLED_DIR, "Paradigm.db"))
        lines.append(f"paradigm: {len(w.rooms)} rooms; install folder {config.APP_DIR}")
    except Exception:
        bad += 1
        lines.append("FAIL board: " + traceback.format_exc())
    try:
        import keyring
        import keyring.errors
        if sys.platform.startswith("linux"):
            import secretstorage  # noqa: F401  (GNOME Keyring / KWallet over D-Bus: bundled, used when running)
            from keyring.backends import SecretService  # noqa: F401
        try:
            keyring.get_password("MudPilot-selftest", "nobody")
            lines.append(f"keyring: {type(keyring.get_keyring()).__name__}")
        except keyring.errors.NoKeyringError:
            if not sys.platform.startswith("linux"):
                raise
            # a Linux box with no password store running: MudPilot asks for the password each session
            lines.append("keyring: no password store running here (passwords kept for the session only)")
    except Exception as ex:
        bad += 1
        lines.append(f"FAIL keyring: {ex!r}")
    try:
        import tkinter
        lines.append(f"tk {tkinter.TkVersion}")
    except Exception as ex:
        bad += 1
        lines.append(f"FAIL tk: {ex!r}")
    lines.append("ALL OK" if not bad else f"{bad} FAILED")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 1 if bad else 0


def main():
    args = sys.argv[1:]
    if args[:1] == ["--selftest"]:
        sys.exit(selftest(args[1] if len(args) > 1 else "selftest.txt"))
    if "--overview" in args:                     # (0.8.201) the All characters window on its own
        from mudpilot.overview import main as overview_main
        sys.exit(overview_main())
    if args[:2] == ["-m", "mudpilot"]:
        sys.argv = [sys.argv[0]] + args[2:]
        from mudpilot.app import main as app_main
        app_main()
        return
    if args[:2] == ["-m", "mudpilot.launcher"]:
        args = args[2:]
    from mudpilot import launcher
    launcher.main(args)


if __name__ == "__main__":
    main()
