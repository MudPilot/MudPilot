import os, sys, shutil, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route, write_mp
s = Session(config.Settings())                      # migrates data/world.db -> data/boards/Main
print("boards:", config.list_boards(), "| legacy world.db left behind:", os.path.exists(config.LEGACY_WORLD_DB))
print("Main rooms:", len(s.world.rooms))
# make a second board with different data (only map 1) to prove they're separate
b2 = config.world_path("Other BBS"); os.makedirs(os.path.dirname(b2), exist_ok=True)
shutil.copy(config.world_path("Main"), b2)
con = sqlite3.connect(b2); con.execute("DELETE FROM rooms WHERE map <> 1"); con.commit(); con.close()
# a path saved on Main only
mp = path_from_route(s.world, (1, 1), s.world.route((1, 1), (1, 16)), name="Main-only path")
s.save_path(mp, "mainonly.mp")
s.bosses.record_kill(s.world.monster_names["dark phoenix"])
print("Main: paths", [p.title for p in s.paths], "| bosses", [m["name"] for m in s.bosses.tracked()])
s.settings.board = "Other BBS"; s.switch_board()
print("Other: rooms", len(s.world.rooms), "| paths", [p.title for p in s.paths], "| bosses", [m["name"] for m in s.bosses.tracked()])
s.settings.board = "Main"; s.switch_board()
print("Back on Main: rooms", len(s.world.rooms), "| paths", [p.title for p in s.paths], "| bosses", [m["name"] for m in s.bosses.tracked()])
# cleanup test-only data
shutil.rmtree(config.board_dir("Other BBS"))
os.remove(os.path.join(config.paths_dir("Main"), "mainonly.mp"))
os.remove(os.path.join(config.board_dir("Main"), "bosses.json"))
