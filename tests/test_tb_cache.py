"""0.8.225 (bug hunt #27): the parsed MME text blocks (room commands) are cached next to world.db, keyed by its time
and size. The world loaded from the cache must be the same as one parsed fresh: rooms, exits and their actions,
room commands, quest steps, routes. A damaged or stale cache is parsed again."""
import os, sys, time, shutil, tempfile, hashlib
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import worlddb
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

SKIP = {"_plan_lock", "_memo", "path"}
def state(w):
    """Everything the load built, as one text (dataclass reprs are complete)."""
    parts = []
    for k in sorted(vars(w)):
        if k in SKIP:
            continue
        parts.append(f"{k}={vars(w)[k]!r}")
    return "\n".join(parts)

def digest(w):
    return hashlib.sha256(state(w).encode("utf-8", "surrogatepass")).hexdigest()

tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "world.db")
shutil.copy2(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"), db)
cache = db + ".actions.cache"

os.environ["MUDPILOT_NO_TB_CACHE"] = "1"
t = time.time(); fresh = worlddb.WorldDB(db); t_fresh = time.time() - t
check("no cache written when switched off", not os.path.exists(cache))
del os.environ["MUDPILOT_NO_TB_CACHE"]

t = time.time(); first = worlddb.WorldDB(db); t_first = time.time() - t
check("cache written on the first load", os.path.exists(cache))
t = time.time(); cached = worlddb.WorldDB(db); t_cached = time.time() - t
print(f"  load: parse {t_fresh:.2f}s, parse+write {t_first:.2f}s, from cache {t_cached:.2f}s")
check("world has rooms and room commands", len(fresh.rooms) > 1000 and len(fresh.room_actions) > 50)
d0 = digest(fresh)
check("first load (writing the cache) = fresh parse", digest(first) == d0)
check("load from the cache = fresh parse", digest(cached) == d0)
check("loading from the cache is faster", t_cached < t_fresh)

# routes: the same over a spread of room pairs. (Equal-length ties can break differently between two loads even
# with no cache at all, so compare what matters: found or not, how many steps, where it ends.)
def sig(r):
    if not isinstance(r, list):
        return repr(r)
    return (len(r), getattr(r[-1], "to", None) if r else None)
keys = sorted(fresh.rooms)
pairs = [(keys[i], keys[(i * 7919) % len(keys)]) for i in range(0, len(keys), max(1, len(keys) // 40))]
same = True
for a, b in pairs:
    try:
        ra = fresh.route(a, b)
    except Exception as ex:
        ra = repr(ex)
    try:
        rb = cached.route(a, b)
    except Exception as ex:
        rb = repr(ex)
    if sig(ra) != sig(rb):
        same = False
        print("  differs:", a, b)
check(f"routes identical ({len(pairs)} pairs)", same)

# a damaged cache: parsed again, same world, cache rewritten
with open(cache, "wb") as f:
    f.write(b"not a pickle")
w = worlddb.WorldDB(db)
check("damaged cache: parsed again, same world", digest(w) == d0)
with open(cache, "rb") as f:
    check("damaged cache replaced", f.read(12) != b"not a pickle")

# world.db changed (time/size): the old cache isn't used
st = os.stat(db)
os.utime(db, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000_000))
import pickle
with open(cache, "rb") as f:
    old_key = pickle.load(f)["key"]
w = worlddb.WorldDB(db)
with open(cache, "rb") as f:
    new_key = pickle.load(f)["key"]
check("changed world.db: new cache key", new_key != old_key and digest(w) == d0)

shutil.rmtree(tmp, ignore_errors=True)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
