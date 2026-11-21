"""Player DB: look once per day, shadow form, don't-look, friend/enemy, macros, hang-ups."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, players as P, macros as M
from mudpilot.session import Session
from mudpilot.ansi import Style
import tempfile
tmp = tempfile.mkdtemp()
P.players_file = lambda board: os.path.join(tmp, "players.json")
M.MACRO_FILE = os.path.join(tmp, "macros.json")
st = config.Settings(); st.save = lambda: None
s = Session(st)
sent, closed = [], []
class FakeTel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): closed.append(1); self.connected = False
s.telnet = FakeTel(); s._want_connected = True
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
def room(*who):
    feed("[HP=650/MA=394]:Town Gates", "Also here: " + ", ".join(who) + ".", "Obvious exits: north, south")
room("Mirage", "Ming")
s.players._last_look = 0; s.players.tick()
check("looks at first player", sent[-1:] == ["look Mirage"])
feed("[ Mirage Darkblade ]", "Mirage is a lithe Dark-Elf Ninja with cold eyes.", "He is equipped with:",
     "crimson bracers                (Arms)", "golden headdress               (Head)", "vortex staff                   (Weapon)")
s.players._capture["t"] -= 5; s.players.tick()
p = s.players.data["mirage"]
check("learned gear/race/class/surname", len(p["wearing"]) == 3 and p["race"] == "Dark-Elf" and p["class"] == "Ninja" and p["surname"] == "Darkblade")
s.players._last_look = 0; s.players.tick()
check("then looks at the second", sent[-1] == "look Ming")
feed("[ Ming ]", "You see nothing special about her.")   # shadow form: no gear shown
s.players._capture["t"] -= 5; s.players.tick()
n = len(sent)
for _ in range(5):
    room("Mirage", "Ming"); s.players._last_look = 0; s.players.tick()
check("no re-looks within 24h (shadow form too)", len(sent) == n)
s.players.data["ming"]["last_looked"] -= 25 * 3600
room("Ming"); s.players._last_look = 0; s.players.tick()
check("looks again after 24h", sent[-1] == "look Ming")
s.players._capture = None
s.players.get("Lot")["dont_look"] = True
room("Lot"); s.players._last_look = 0; s.players.tick()
check("Don't look respected", sent[-1] != "look Lot")
# enemy hangs up, friend never does
s.players.get("Lot")["relationship"] = "Enemy"
room("Lot")
check("enemy seen hangs up", closed)
# low HP hang-up
closed.clear(); s.telnet.connected = True
feed("[HP=600/MA=394]:"); s.state.max_hp = 600; s.state.hp = 600; s.poll()   # back in at full
s.state.hp = 120; s.poll()
check("hangs up below 25% HP", closed)
# macros
check("macro split", M.split("n^Ml n^Mask rod ") == (["n", "l n"], "ask rod "))
mac = M.Macros(st)
check("default keypad", mac.get("Keypad 8") == "n^M")
mac.set("F2", "curp^Me^M")
check("char macro", mac.get("F2") == "curp^Me^M" and any(r[0] == "F2" and r[2] == "Char" for r in mac.table()))
check("key names", M.key_name("F2", 113, 1, True) == "Shift+F2" and M.key_name("KP_8", 0, 0, False) == "Keypad 8"
      and M.key_name("8", 104, 0, True) == "Keypad 8" and M.key_name("Up", 38, 0, True, extended=False) == "Keypad 8"
      and M.key_name("Up", 38, 0, True, extended=True) is None)
check("ini macro keys", M._ini_key("F1") == "F1" and M._ini_key("ShiftF3") == "Shift+F3" and M._ini_key("Num5") == "Keypad 5")
print("ALL PASS" if ok else "SOME FAILED")

# Dan's real board output (2026-10-25)
real = """[ Miserable Cunt ](House of Rage)
Miserable is a colossal, powerfully built Nekojin Mage with shoulder-length
silver hair and black eyes. He moves with uncanny speed, and is likable in an
unassuming sort of way. Miserable appears to be all-knowing and looks fairly
knowledgeable. He is slightly wounded.

He is equipped with:

golden snake earrings          (Ears)
skull mask                     (Face)
rainbow stone                  (Neck)
runed cape                     (Back)
black embroidered robes        (Torso)
platinum bracers               (Arms)
sunstone wristband             (Wrist)
emerald-studded bracelet       (Wrist)
silversilk gloves              (Hands)
platinum ring                  (Finger)
pearl ring                     (Finger)
sash of the arch-mage          (Waist)
silversilk trousers            (Legs)
snakeskin boots                (Feet)
vortex staff                   (Weapon Hand)

Miserable is looking at you.""".splitlines()
s.telnet.connected = True
s.players.look_now("Miserable")
feed(*real)
s.players._capture["t"] -= 5; s.players.tick()
p = s.players.data["miserable"]
check("real look: 15 items, Nekojin Mage, surname, gang",
      len(p["wearing"]) == 15 and p["wearing"][-1] == ["vortex staff", "Weapon Hand"] and p["race"] == "Nekojin"
      and p["class"] == "Mage" and p["surname"] == "Cunt" and p["gang"] == "House of Rage")
print("ALL PASS" if ok else "SOME FAILED")
