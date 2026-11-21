"""Import a character's login from a MegaMUD character file (Chars\\<name>.ini) so moving from MegaMUD to MudPilot
is one step: point at the file and go. MudPilot reads the UserID and the saved password and uses them to log in —
the password goes straight into Windows Credential Manager (encrypted) and is never shown, logged or returned.

MegaMUD stores the password as a 30-byte field in hex, each byte mixed with its position:
    stored[i] = (-(i*i) - password[i]) mod 256   →   password[i] = (-(i*i) - stored[i]) mod 256
up to the first 0 byte. It's only local obfuscation of your own saved login, the same credential you type into the
Connect box by hand.
"""
from __future__ import annotations

import re

MAX_LEN = 60                 # 30 bytes, hex


def _decode_password(hexstr: str) -> str:
    h = re.sub(r"[^0-9A-Fa-f]", "", hexstr or "")[:MAX_LEN]
    out = []
    for i in range(0, len(h) - 1, 2):
        try:
            b = int(h[i:i + 2], 16)
        except ValueError:
            break
        j = i // 2
        c = ((-(j * j)) - b) % 256
        if c == 0:
            break
        if not (32 <= c < 127):
            return ""        # not a plain-text password under this scheme: hand back nothing
        out.append(chr(c))
    return "".join(out)


def read_login(path: str) -> dict:
    """{'user', 'password', 'bbs', 'name'} from a MegaMUD character .ini. The caller stores 'password' in the
    credential store and connects with it; it is never displayed. Missing fields come back ''."""
    vals = {}
    with open(path, "r", encoding="latin-1", errors="replace") as f:
        for line in f:
            m = re.match(r"^\s*(UserID|Password|BbsName|Name|Surname)\s*=\s*(.*?)\s*$", line, re.I)
            if m:
                vals.setdefault(m.group(1).lower(), m.group(2))
    name = (vals.get("name", "") + (" " + vals["surname"] if vals.get("surname") else "")).strip()
    return {"user": vals.get("userid", ""), "password": _decode_password(vals.get("password", "")),
            "bbs": vals.get("bbsname", ""), "name": name or vals.get("name", "")}
