"""Party: par every 5 s, heal lowest % with priority players, attack last."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
st = config.Settings(); st.save = lambda: None
st.my_name = "Tester"; st.auto_heal = True; st.heal_cmd = "mend"; st.heal_pct = 50
st.party_heal = True; st.party_heal_pct = 70; st.party_heal_cmd = "mend {name}"
s = Session(st)
sent = []
class FakeTel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = FakeTel(); s._want_connected = True
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
def par(rows):
    feed("[HP=600/MA=300]: par", "The following people are in your travel party:", *rows, "[HP=600/MA=300]:")
feed("[HP=600/MA=300]:Town Gates", "Obvious exits: north, south"); s.bot._attack_sent_at = 0; s.bot._attack_cmd = None; s.bot._melee_on = False; s.bot._cool.clear()
s.state.max_hp, s.state.hp, s.state.max_ma, s.state.ma = 600, 600, 300, 300
check("default party check is 5 s", st.party_check_secs == 5)
par(["  Tester Abil                   (Druid)      [M:100%] [H:100%] - Backrank",
     "  Miserable Par                 (Mage)       [M: 50%] [H: 60%]M - Frontrank",
     "  Revolution Abil               (Priest)     [M: 90%] [H: 55%]R - Backrank"])
s.bot._cool.clear(); s.bot._last_spell_at = 0; sent.clear(); s.bot.tick()
check("heals lowest % (Revolution 55%)", "mend Revolution" in sent)
st.party_heal_priority = ["Miserable"]; st.party_priority_bonus = 15
par(["  Tester Abil                   (Druid)      [M:100%] [H:100%] - Backrank",
     "  Miserable Par                 (Mage)       [M: 50%] [H: 60%]M - Frontrank",
     "  Revolution Abil               (Priest)     [M: 90%] [H: 55%]R - Backrank"])
s.bot._cool.clear(); s.bot._last_spell_at = 0; sent.clear(); s.bot.tick()
check("priority player first (Miserable 60% beats 55%)", "mend Miserable" in sent)
s.bot._cool.clear(); s.bot._last_spell_at = 0; sent.clear(); s.bot.tick()
check("doesn't heal the same reading twice", "mend Miserable" not in sent)
par(["  Tester Abil                   (Druid)      [M:100%] [H:100%] - Backrank",
     "  Miserable Par                 (Mage)       [M: 50%] [H: 95%]M - Frontrank",
     "  Revolution Abil               (Priest)     [M: 90%] [H: 90%]R - Backrank"])
s.bot._cool.clear(); s.bot._last_spell_at = 0; sent.clear(); s.bot.tick()
check("nobody low -> no heal", not any(c.startswith("mend") for c in sent))
s.state.hp = 200
s.bot._cool.clear(); s.bot._last_spell_at = 0; sent.clear(); s.bot.tick()
check("own HP lowest -> self heal", "mend" in sent)
s.state.hp = 600
# party check cadence
sent.clear(); s.bot._cool.clear(); s.bot.party_tick(); first = list(sent)
sent.clear(); s.bot.party_tick()
check("par sent, not again within 5 s", first == ["par"] and not sent)
# attack last (Revolution, 2026-10-31): attack at once, then again after a party member joins in — be the last
st.attack_last = True; st.auto_combat = True; st.min_mobs = 1
st.party_heal = False; st.auto_spells = False; st.auto_heal = False
feed("[HP=600/MA=300]:Town Gates", "Also here: giant rat.", "Obvious exits: north, south")
s.bot._cool.clear(); s.bot._last_spell_at = 0; sent.clear()
for _ in range(3): s.bot.tick()
check(f"attack last: attacks straight away ({sent})", any(c.startswith(("a ", "attack")) or "rat" in c for c in sent))
s.state.in_combat = True
ac0 = s.bot._attack_cmd
sent.clear(); feed("Miserable moves to attack giant rat.")
check(f"0.8.224: joined before our opening cast could land — not re-sent yet ({sent})", not any("rat" in c for c in sent))
s.bot._attack_cmd = (ac0[0], time.time() - 2); s.bot._al_pending = ("Miserable", s.bot._attack_cmd[1])
sent.clear(); s.bot.tick()
check(f"…and again when a party member joins in after, once it's had time ({sent})", any("rat" in c for c in sent))
def aged():
    s.bot._attack_cmd = (s.bot._attack_cmd[0], time.time() - 2)
sent.clear(); feed("Miserable swings at the giant rat with his vortex staff!")
check(f"…once per member, not on every swing ({sent})", not any("rat" in c for c in sent))
sent.clear(); feed("Lyra moves to attack giant rat.")
s.state.party["Lyra"] = {"hp": 100, "t": time.time()}
aged(); sent.clear(); feed("Lyra moves to attack giant rat.")
check(f"…and again right away for the next member to join ({sent})", any("rat" in c for c in sent))
# two MudPilots both on attack last: their answers would bounce forever — at most 5 a round
sent.clear()
for i in range(12):
    s.bot._al_answered = set(); aged(); feed("Lyra moves to attack giant rat.")
check(f"at most 5 re-attacks in a round ({len(sent)})", 1 <= len([c for c in sent if "rat" in c]) <= 5)
s.bot._al_times = []
# the re-attack's own *Combat Off* / *Combat Engaged* isn't the fight ending: Lyra stays answered
s.bot._al_answered = {"lyra"}; s.bot._attack_cmd = ("a rat", time.time())
feed("*Combat Off*", "*Combat Engaged*")
sent.clear(); feed("Lyra moves to attack giant rat.")
check(f"re-attack's Combat Off doesn't reset who's answered ({sent})", not any("rat" in c for c in sent))
feed("*Combat Off*"); s.state.in_combat = False
st.attack_last = False
sent.clear(); s.bot._attack_cmd = ("a rat", time.time()); s.state.in_combat = True
feed("Lyra moves to attack giant rat.")
check("attack last off: no re-attack", not any("rat" in c for c in sent))
s.state.in_combat = False
feed("[HP=600/MA=300]:Town Gates", "Obvious exits: north, south"); s.bot._attack_sent_at = 0; s.bot._attack_cmd = None; s.bot._melee_on = False; s.bot._cool.clear()
# party rank keeper + per-player invite/join
st.attack_last = False
st.party_rank = "front"
par(["  Tester Abil                   (Druid)      [M:100%] [H:100%] - Backrank",
     "  Miserable Par                 (Mage)       [M: 90%] [H: 95%]M - Frontrank"])
s.state.in_combat = False
s.state.need_refresh = False; s.bot._refresh_at = 0     # (0.8.224: the room's been shown again since the fight)
sent.clear()
for _ in range(3):
    s.bot._cool = {"par": time.time(), "par_solo": time.time()}; s.bot.tick()
check(f"goes frontrank when par shows backrank ({sent})", "frontrank" in sent)
p = s.players.get("Lyra"); p["invite_if_seen"] = True
sent.clear(); feed("[HP=600/MA=300]:Town Gates", "Also here: Lyra.", "Obvious exits: north, south")
check("invites a player marked 'invite if seen'", "invite Lyra" in sent)
feed("You have invited Lyra to follow you.")
check(f"then tells them @join as soon as the game confirms ({sent})", "/Lyra @join" in sent)
s.players.get("Revolution")["join_if_invited"] = True
sent.clear(); feed("Revolution has invited you to join his party.")
check("joins when a 'join if invited' player invites", "join Revolution" in sent)
sent.clear(); feed("Stranger has invited you to join his party.")
check("ignores other invites", "join Stranger" not in sent)
# leader can't change rank: never sends it
par(["  Tester Abil                   (Druid)      [M:100%] [H:100%] - Frontrank",
     "  Miserable Par                 (Mage)       [M: 90%] [H: 95%]M - Backrank"])
st.party_rank = "back"; s.bot.x._rank_tries = 0; st.party_leader = "Tester"
sent.clear()
for _ in range(3):
    s.bot._cool = {"par": time.time(), "par_solo": time.time()}; s.bot.tick()
check(f"leader never sends a rank ({sent})", not any("rank" in c for c in sent))
st.party_leader = ""
s.bot.x._rank_tries = 0
s.bot.x._own_party = False          # (the invite above made us leader; this part is about a follower)
for i in range(6):
    s.bot._cool = {"par": time.time(), "par_solo": time.time()}; s.bot.x.b._cool.pop("rank", None); s.bot.x.rank_tick()
check(f"gives up after 3 tries when the game won't change it (tries={s.bot.x._rank_tries})", s.bot.x._rank_tries == 3)
sent.clear(); s.send("invite re")
check(f"short name: nothing guessed yet ({sent})", sent == ["invite re"])
feed("You have invited Revolution to follow you.")
check(f"typed 'invite re' → /Revolution @join, the full name ({sent})", sent == ["invite re", "/Revolution @join"])
print("ALL PASS" if ok else "SOME FAILED")
