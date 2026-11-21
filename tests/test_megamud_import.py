"""Import a MegaMUD character .ini: read the UserID and decode the saved password so a user can move to MudPilot
by pointing at their file. The password is only decoded to use it (store + log in), never shown."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import megamud_import as M
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


def encode(pw: str) -> str:
    """MegaMUD's stored hex for a password (the inverse of the decoder), for the test only."""
    out = []
    for i, ch in enumerate(pw):
        b = ((-(i * i)) - ord(ch)) % 256
        out.append(f"{b:02X}")
    return "".join(out)


# round-trips a known password
for pw in ("test123", "getfucked", "aB3$xZ9!qw", "a"):
    check(f"decodes {pw!r}", M._decode_password(encode(pw)) == pw)

# a full character .ini
d = tempfile.mkdtemp()
p = os.path.join(d, "REVOLUTION.ini")
open(p, "w", encoding="latin-1").write(
    "[Character]\nName=Revolution\nSurname=TheDruid\n"
    f"UserID=revo1\nPassword={encode('hunter2stuff')}\nBbsName=Paradigm PVP\n")
info = M.read_login(p)
check(f"reads UserID ({info['user']})", info["user"] == "revo1")
check("decodes the password", info["password"] == "hunter2stuff")
check(f"reads the character name ({info['name']})", info["name"] == "Revolution TheDruid")
check(f"reads the BBS ({info['bbs']})", info["bbs"] == "Paradigm PVP")

# garbage / non-ASCII payload → empty (don't hand back junk)
check("non-text password → empty", M._decode_password("FFFFFFFF") == "")
check("no password line → empty", M.read_login.__doc__ is not None and
      M.read_login(os.path.join(d, "REVOLUTION.ini"))["password"] == "hunter2stuff")
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
