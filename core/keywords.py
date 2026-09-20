"""Keyword list ingest + topic-idea selection.

The client supplies a keyword list (one phrase per line, or CSV with
phrase,intent,locality,priority). We normalise it, then pick the next topics
to write about using a least-recently-used + priority rule so the blog does not
hammer the same phrase every week.
"""
import csv
import io
import re
from . import db

INTENTS = ("informational", "commercial", "transactional", "local")

# crude but effective intent sniffing so a bare one-phrase-per-line list still
# gets sensible angles without the client having to tag anything
_COMMERCIAL = re.compile(r"\b(best|top|vs|compare|review|cost|price|fees?|worth)\b", re.I)
_TRANSACTIONAL = re.compile(r"\b(buy|sell|rent|hire|book|for sale|to let|near me)\b", re.I)
_LOCAL_HINT = re.compile(r"\bin ([A-Z][a-zA-Z\-']+(?: [A-Z][a-zA-Z\-']+)*)$")


def sniff_intent(phrase):
    if _TRANSACTIONAL.search(phrase):
        return "transactional"
    if _COMMERCIAL.search(phrase):
        return "commercial"
    if _LOCAL_HINT.search(phrase):
        return "local"
    return "informational"


def sniff_locality(phrase):
    m = _LOCAL_HINT.search(phrase.strip())
    return m.group(1) if m else None


def parse(text):
    """Accept a plain list or a CSV. Returns list of dicts."""
    text = text.strip()
    if not text:
        return []
    rows = []
    looks_csv = "," in text.splitlines()[0]
    if looks_csv:
        reader = csv.reader(io.StringIO(text))
        for r in reader:
            if not r or not r[0].strip():
                continue
            phrase = r[0].strip()
            if phrase.lower() in ("keyword", "phrase", "term"):
                continue  # header
            rows.append({
                "phrase": phrase,
                "intent": (r[1].strip().lower() if len(r) > 1 and r[1].strip() else sniff_intent(phrase)),
                "locality": (r[2].strip() if len(r) > 2 and r[2].strip() else sniff_locality(phrase)),
                "priority": int(r[3]) if len(r) > 3 and r[3].strip().isdigit() else 5,
            })
    else:
        for line in text.splitlines():
            phrase = line.strip().lstrip("-•*").strip()
            if not phrase:
                continue
            rows.append({
                "phrase": phrase,
                "intent": sniff_intent(phrase),
                "locality": sniff_locality(phrase),
                "priority": 5,
            })
    # de-dupe, keep first occurrence
    seen, out = set(), []
    for r in rows:
        k = r["phrase"].lower()
        if k in seen:
            continue
        seen.add(k)
        if r["intent"] not in INTENTS:
            r["intent"] = "informational"
        out.append(r)
    return out


def ingest(conn, text):
    """Insert new phrases, update priority/intent on ones we already hold."""
    added = updated = 0
    for r in parse(text):
        existing = conn.execute(
            "SELECT id FROM keywords WHERE lower(phrase)=lower(?)", (r["phrase"],)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE keywords SET intent=?, locality=?, priority=? WHERE id=?",
                (r["intent"], r["locality"], r["priority"], existing["id"]),
            )
            updated += 1
        else:
            conn.execute(
                "INSERT INTO keywords (phrase, intent, locality, priority, created_at) "
                "VALUES (?,?,?,?,?)",
                (r["phrase"], r["intent"], r["locality"], r["priority"], db.now()),
            )
            added += 1
    conn.commit()
    return added, updated


def next_topics(conn, count=3):
    """Least-used first, then highest priority, then oldest-used.

    Skips phrases that already have a live (non-rejected) post waiting, so a
    run does not queue three drafts about the same thing.
    """
    rows = conn.execute(
        """
        SELECT k.* FROM keywords k
        WHERE NOT EXISTS (
            SELECT 1 FROM posts p
            WHERE p.keyword_id = k.id
              AND p.status IN ('pending_review','approved','scheduled')
        )
        ORDER BY k.times_used ASC,
                 k.priority DESC,
                 COALESCE(k.last_used_at, '0000') ASC,
                 k.id ASC
        LIMIT ?
        """,
        (count,),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_used(conn, keyword_id):
    conn.execute(
        "UPDATE keywords SET times_used = times_used + 1, last_used_at = ? WHERE id = ?",
        (db.now(), keyword_id),
    )
