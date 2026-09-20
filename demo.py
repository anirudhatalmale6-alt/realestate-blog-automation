"""Seed the demo: sample keywords, three drafts, approve them, show the calendar.

    python3 demo.py           # seed + run
    python3 demo.py --reset   # wipe the db first
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import db, keywords as kw, generator, scheduler, publisher  # noqa: E402

SAMPLE_KEYWORDS = """\
how to value a house before selling
best time of year to sell a flat
letting agent fees explained
what does a property survey actually cover
buying a leasehold flat: what to check
shared ownership vs help to buy
how long does conveyancing take
selling a house with tenants in it
estate agent commission compared
houses for sale in Didsbury
"""


def main():
    if "--reset" in sys.argv and os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)

    conn = db.init()

    added, updated = kw.ingest(conn, SAMPLE_KEYWORDS)
    print(f"Keywords: {added} added, {updated} updated")

    provider = generator.pick_provider(conn)
    print(f"Writer: {provider}")

    ids = generator.run_batch(conn, 3)
    print(f"\nDrafted {len(ids)} posts:")
    for pid in ids:
        r = conn.execute("SELECT title, word_count, slug FROM posts WHERE id=?", (pid,)).fetchone()
        print(f"  [{pid}] {r['title']}  ({r['word_count']} words, /{r['slug']}/)")

    print("\nApproving all three (in the UI this is a button per post):")
    for pid in ids:
        slot = scheduler.approve(conn, pid)
        print(f"  [{pid}] -> {slot.strftime('%a %d %b %Y, %H:%M %Z')}")

    print("\nCalendar:")
    for week, items in scheduler.calendar(conn).items():
        print(f"  {week}")
        for it in items:
            print(f"    {it['when'].strftime('%a %d %b %H:%M')}  {it['title'][:58]}")

    due = scheduler.due_posts(conn)
    print(f"\nDue for publishing right now: {len(due)} "
          f"(correct - the first slot is in the future)")

    print(f"\nDatabase: {db.DB_PATH}")
    print("Start the UI with:  python3 web/app.py   ->  http://127.0.0.1:5057")


if __name__ == "__main__":
    main()
