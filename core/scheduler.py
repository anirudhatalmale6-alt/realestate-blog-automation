"""Calendar: spaces approved posts evenly and drops them on good publish slots.

Slot rule
---------
A slot is (allowed weekday) x (allowed time-of-day). We walk forward from the
later of "now" and "the last thing already scheduled", and take the first slot
that is free and at least `min_gap_hours` after the previous post. That gives
an evenly spaced calendar without ever double-booking a time.

The default days/times below are sensible starting points for a Dubai property
audience - note the UAE working week runs Monday to Friday with the weekend on
Saturday and Sunday, so the slots sit mid-week. They are NOT measured. Once the
site has a few months of analytics, replace them with the real best-performing
slots; they live in settings so that is a config change, not a code change.
"""
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

from . import db

DEFAULTS = {
    "timezone": "Asia/Dubai",
    "publish_days": "1,2,3",          # Mon=0 ... Sun=6  -> Tue, Wed, Thu
    "publish_times": "09:30,13:00",
    "min_gap_hours": "36",
    "posts_per_week": "2",
}


def get_config(conn):
    cfg = {}
    for k, default in DEFAULTS.items():
        cfg[k] = db.get_setting(conn, k, default)
    cfg["tz"] = ZoneInfo(cfg["timezone"])
    cfg["days"] = sorted({int(d) for d in cfg["publish_days"].split(",") if d.strip() != ""})
    cfg["times"] = []
    for t in cfg["publish_times"].split(","):
        t = t.strip()
        if not t:
            continue
        hh, mm = t.split(":")
        cfg["times"].append(dtime(int(hh), int(mm)))
    cfg["times"].sort()
    cfg["min_gap"] = timedelta(hours=float(cfg["min_gap_hours"]))
    return cfg


def save_config(conn, **kwargs):
    for k, v in kwargs.items():
        if k in DEFAULTS:
            db.set_setting(conn, k, v)
    conn.commit()


def _iter_slots(cfg, start, horizon_days=400):
    """Yield every publish slot from `start` forward, in order."""
    day = start.astimezone(cfg["tz"]).date()
    for offset in range(horizon_days):
        d = day + timedelta(days=offset)
        if d.weekday() not in cfg["days"]:
            continue
        for t in cfg["times"]:
            slot = datetime.combine(d, t, tzinfo=cfg["tz"])
            if slot > start:
                yield slot


def _taken(conn):
    rows = conn.execute(
        "SELECT scheduled_for FROM posts "
        "WHERE scheduled_for IS NOT NULL AND status IN ('scheduled','published')"
    ).fetchall()
    out = []
    for r in rows:
        out.append(datetime.fromisoformat(r["scheduled_for"]))
    return sorted(out)


def next_slot(conn, after=None):
    """First free slot that also respects the minimum gap."""
    cfg = get_config(conn)
    now = datetime.now(cfg["tz"])
    taken = _taken(conn)
    start = after or now
    if taken:
        start = max(start, taken[-1])          # keep the calendar moving forward

    taken_set = {t.isoformat() for t in taken}
    for slot in _iter_slots(cfg, start):
        if slot.isoformat() in taken_set:
            continue
        if taken and (slot - taken[-1]) < cfg["min_gap"]:
            continue
        return slot
    raise RuntimeError("no free slot found inside the horizon - widen publish_days/times")


def approve(conn, post_id, note=""):
    """Approve a draft and give it the next slot on the calendar."""
    row = conn.execute("SELECT status FROM posts WHERE id=?", (post_id,)).fetchone()
    if row is None:
        raise ValueError(f"no post {post_id}")
    if row["status"] == db.PUBLISHED:
        raise ValueError("already published")

    slot = next_slot(conn)
    conn.execute(
        "UPDATE posts SET status=?, scheduled_for=?, review_note=?, updated_at=? WHERE id=?",
        (db.SCHEDULED, slot.isoformat(), note, db.now(), post_id),
    )
    db.log_event(conn, post_id, "approved", f"scheduled_for={slot.isoformat()}")
    conn.commit()
    return slot


def reject(conn, post_id, note=""):
    conn.execute(
        "UPDATE posts SET status=?, scheduled_for=NULL, review_note=?, updated_at=? WHERE id=?",
        (db.REJECTED, note, db.now(), post_id),
    )
    db.log_event(conn, post_id, "rejected", note)
    conn.commit()


def pause(conn, post_id):
    conn.execute(
        "UPDATE posts SET status=?, scheduled_for=NULL, updated_at=? WHERE id=?",
        (db.PAUSED, db.now(), post_id),
    )
    db.log_event(conn, post_id, "paused", "")
    conn.commit()


def reschedule(conn, post_id, when):
    """Move one post to an explicit datetime (manual override from the calendar)."""
    cfg = get_config(conn)
    if isinstance(when, str):
        when = datetime.fromisoformat(when)
    if when.tzinfo is None:
        when = when.replace(tzinfo=cfg["tz"])
    conn.execute(
        "UPDATE posts SET scheduled_for=?, status=?, updated_at=? WHERE id=?",
        (when.isoformat(), db.SCHEDULED, db.now(), post_id),
    )
    db.log_event(conn, post_id, "rescheduled", when.isoformat())
    conn.commit()
    return when


def rebalance(conn):
    """Re-space every scheduled post onto clean slots, keeping their order.

    Used after the publishing rhythm is changed (e.g. 2/week -> 3/week).
    """
    cfg = get_config(conn)
    rows = conn.execute(
        "SELECT id FROM posts WHERE status=? ORDER BY COALESCE(scheduled_for,'9999'), id",
        (db.SCHEDULED,),
    ).fetchall()
    conn.execute("UPDATE posts SET scheduled_for=NULL WHERE status=?", (db.SCHEDULED,))
    conn.commit()

    out = []
    for r in rows:
        slot = next_slot(conn)
        conn.execute("UPDATE posts SET scheduled_for=?, updated_at=? WHERE id=?",
                     (slot.isoformat(), db.now(), r["id"]))
        conn.commit()
        out.append((r["id"], slot))
    db.log_event(conn, None, "rebalanced", f"{len(out)} posts")
    conn.commit()
    return out


def calendar(conn, weeks=6):
    """Everything scheduled or published, grouped by ISO week - drives the UI."""
    cfg = get_config(conn)
    rows = conn.execute(
        "SELECT id, title, status, scheduled_for, published_at, remote_url FROM posts "
        "WHERE scheduled_for IS NOT NULL ORDER BY scheduled_for ASC"
    ).fetchall()
    limit = datetime.now(cfg["tz"]) + timedelta(weeks=weeks)
    grouped = {}
    for r in rows:
        when = datetime.fromisoformat(r["scheduled_for"])
        if when > limit:
            continue
        key = when.strftime("%G-W%V")
        grouped.setdefault(key, []).append({
            "id": r["id"], "title": r["title"], "status": r["status"],
            "when": when, "remote_url": r["remote_url"],
        })
    return grouped


def due_posts(conn, now=None):
    """Scheduled posts whose slot has arrived - what the cron job publishes."""
    cfg = get_config(conn)
    now = now or datetime.now(cfg["tz"])
    rows = conn.execute(
        "SELECT * FROM posts WHERE status=? AND scheduled_for IS NOT NULL", (db.SCHEDULED,)
    ).fetchall()
    return [dict(r) for r in rows
            if datetime.fromisoformat(r["scheduled_for"]) <= now]
