"""Cron entry points.

    */15 * * * *  cd /path/to/blogbot && python3 cron.py publish
    0 6 * * 1     cd /path/to/blogbot && python3 cron.py draft 3

`publish` pushes anything whose slot has arrived. `draft` tops up the approval
queue from the keyword pool - it never publishes, so the human approval step
stays in the loop.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import db, generator, publisher, scheduler  # noqa: E402


def cmd_publish():
    conn = db.init()
    done, failed = publisher.run_due(conn)
    for p in done:
        print(f"published [{p['id']}] {p['title']} -> {p.get('remote_url')}")
    for pid, err in failed:
        print(f"FAILED [{pid}]: {err}", file=sys.stderr)
    return 1 if failed else 0


def cmd_draft(count):
    conn = db.init()
    ids = generator.run_batch(conn, count)
    for pid in ids:
        r = conn.execute("SELECT title FROM posts WHERE id=?", (pid,)).fetchone()
        print(f"drafted [{pid}] {r['title']}")
    if not ids:
        print("no unused keywords left", file=sys.stderr)
    return 0


def cmd_status():
    conn = db.init()
    for s in (db.PENDING, db.SCHEDULED, db.PUBLISHED, db.REJECTED, db.PAUSED):
        n = conn.execute("SELECT COUNT(*) n FROM posts WHERE status=?", (s,)).fetchone()["n"]
        print(f"{s:16} {n}")
    nxt = conn.execute(
        "SELECT title, scheduled_for FROM posts WHERE status=? ORDER BY scheduled_for LIMIT 1",
        (db.SCHEDULED,)).fetchone()
    if nxt:
        print(f"\nnext out: {nxt['scheduled_for']}  {nxt['title']}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "publish":
        sys.exit(cmd_publish())
    elif cmd == "draft":
        sys.exit(cmd_draft(int(sys.argv[2]) if len(sys.argv) > 2 else 3))
    elif cmd == "status":
        sys.exit(cmd_status())
    else:
        print(__doc__)
        sys.exit(2)
