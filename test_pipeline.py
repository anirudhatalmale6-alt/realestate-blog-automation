"""End-to-end checks against a throwaway database.

    python3 test_pipeline.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["BLOGBOT_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from core import db, keywords as kw, generator, scheduler, publisher  # noqa: E402

PASS = FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok    {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")


conn = db.init()
print("\nkeyword parsing")
added, _ = kw.ingest(conn, """\
how to value a house before selling
best letting agent fees compared
houses for sale in Didsbury
buy a flat near me
""")
check("4 keywords ingested", added == 4, added)
rows = {r["phrase"]: r for r in conn.execute("SELECT * FROM keywords")}
check("commercial intent sniffed", rows["best letting agent fees compared"]["intent"] == "commercial")
check("local intent + locality sniffed",
      rows["houses for sale in Didsbury"]["locality"] == "Didsbury")
check("transactional beats local for 'near me'",
      rows["buy a flat near me"]["intent"] == "transactional")
again, updated = kw.ingest(conn, "how to value a house before selling")
check("re-ingest updates rather than duplicates", again == 0 and updated == 1)

print("\ndrafting")
ids = generator.run_batch(conn, 3, provider="template")
check("3 drafts created", len(ids) == 3, ids)
posts = [dict(conn.execute("SELECT * FROM posts WHERE id=?", (i,)).fetchone()) for i in ids]
check("all land in pending_review", all(p["status"] == db.PENDING for p in posts))
check("all have a body over 400 words", all(p["word_count"] > 400 for p in posts),
      [p["word_count"] for p in posts])
check("slugs unique", len({p["slug"] for p in posts}) == 3)
check("no two drafts share a keyword", len({p["keyword_id"] for p in posts}) == 3)
check("titles differ", len({p["title"] for p in posts}) == 3)
more = generator.run_batch(conn, 3, provider="template")
check("only the 1 remaining unused keyword is drafted", len(more) == 1, more)

print("\nscheduling")
cfg = scheduler.get_config(conn)
slots = [scheduler.approve(conn, i) for i in ids]
check("slots strictly increasing", all(b > a for a, b in zip(slots, slots[1:])), slots)
check("all slots on an allowed weekday", all(s.weekday() in cfg["days"] for s in slots),
      [s.weekday() for s in slots])
check("all slots at an allowed time",
      all(s.time() in cfg["times"] for s in slots), [str(s.time()) for s in slots])
gaps = [(b - a) for a, b in zip(slots, slots[1:])]
check("minimum gap respected", all(g >= cfg["min_gap"] for g in gaps), [str(g) for g in gaps])
check("all slots in the future", all(s > datetime.now(cfg["tz"]) for s in slots))
check("status is scheduled",
      all(conn.execute("SELECT status FROM posts WHERE id=?", (i,)).fetchone()["status"]
          == db.SCHEDULED for i in ids))

print("\nmanual override")
moved = scheduler.reschedule(conn, ids[1], slots[1] + timedelta(days=7))
check("reschedule moves the post", moved == slots[1] + timedelta(days=7))
scheduler.pause(conn, ids[2])
paused = conn.execute("SELECT status, scheduled_for FROM posts WHERE id=?", (ids[2],)).fetchone()
check("pause clears the slot", paused["status"] == db.PAUSED and paused["scheduled_for"] is None)

print("\npublishing (dry run)")
back = datetime.now(cfg["tz"]) - timedelta(hours=1)
conn.execute("UPDATE posts SET scheduled_for=?, status=? WHERE id=?",
             (back.isoformat(), db.SCHEDULED, ids[0]))
conn.commit()
due = scheduler.due_posts(conn)
check("backdated post shows as due", [d["id"] for d in due] == [ids[0]], [d["id"] for d in due])
done, failed = publisher.run_due(conn)
check("one post published, none failed", len(done) == 1 and not failed, failed)
row = conn.execute("SELECT * FROM posts WHERE id=?", (ids[0],)).fetchone()
check("status published + url recorded",
      row["status"] == db.PUBLISHED and row["remote_url"], dict(row))
check("nothing left due after the run", scheduler.due_posts(conn) == [])
done2, _ = publisher.run_due(conn)
check("re-running publishes nothing twice", done2 == [])

print("\nsocial hook (dormant)")
n = publisher.fan_out(conn, dict(row))
check("no channels configured -> no jobs queued", n == 0)
conn.execute("INSERT INTO distribution_channels (kind,label,enabled,created_at) "
             "VALUES ('linkedin','Test page',1,?)", (db.now(),))
conn.commit()
n = publisher.fan_out(conn, dict(row))
jobs = conn.execute("SELECT * FROM distribution_jobs").fetchall()
check("adding a channel switches it on with no code change", n == 1 and len(jobs) == 1)
check("queued job carries the live url", row["remote_url"] in jobs[0]["payload"])

print("\nrebalance")
scheduler.save_config(conn, publish_days="0,1,2,3,4", publish_times="09:00,15:00",
                      min_gap_hours="20")
out = scheduler.rebalance(conn)
new_slots = [s for _, s in out]
check("rebalance re-spaces everything", len(new_slots) == len(set(new_slots)) and new_slots)
cfg2 = scheduler.get_config(conn)
check("new rhythm applied", all(s.weekday() in cfg2["days"] and s.time() in cfg2["times"]
                                for s in new_slots), [str(s) for s in new_slots])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
