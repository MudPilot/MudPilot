"""Paradigm shows slots like (Ears) / (Weapon Hand) — that's worn gear, not naked."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.gamestate import worn_list, wielded
st = config.Settings(); st.save = lambda: None; st.hangup_if_naked = True; st.hangup_low_hp = False
s = Session(st)
closed = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): closed.append(1); self.connected = False
s.telnet = T(); s._want_connected = True
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
inv = ["[HP=574/MA=335]:[HP=574/MA=335]:You are carrying 84 platinum pieces, 340 gold crowns, 9 silver nobles, golden",
       "snake earrings (Ears), skull mask (Face), rainbow stone (Neck), runed cape",
       "(Back), black embroidered robes (Torso), platinum bracers (Arms), sunstone",
       "wristband (Wrist), emerald-studded bracelet (Wrist), silversilk gloves (Hands), platinum ring (Finger), pearl rin",
       "g (Finger), sash of the arch-mage (Waist),",
       "silversilk trousers (Legs), snakeskin boots (Feet), vortex staff (Weapon Hand), magical quartz rod, phoenix feath",
       "er, ruby-eyed skull ring, diamond emblem,",
       "white keyring, platinum ring, diamond-studded ring, rope and grapple, coin bag, inscribed stone tablet, jade amul",
       "et, stone signet, 2 flaming dagger, 2 sealed", "clay flask, spiked obsidian collar",
       "You have the following keys: black star key, golden idol, green metal key,", "large iron key, black serpent key.",
       "Wealth: 874090 copper farthings", "Encumbrance: 1838/4032 - Medium [45%]"]
feed(*inv)
s.safety.tick()
wl = worn_list(s.state.carrying)
check(f"reads {len(wl)} worn items", len(wl) >= 14)
check(f"wielding vortex staff ({wielded(s.state.carrying)})", wielded(s.state.carrying) == "vortex staff")
check("no hang-up when dressed", not closed)
feed("[HP=574/MA=335]:You are carrying 84 platinum pieces, rope and grapple", "Wealth: 8400 copper farthings",
     "Encumbrance: 100/4032 - None [2%]")
s.safety.tick()
check("hangs up when really naked", closed)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
