"""Draft generation.

Providers are pluggable. `template` needs no API key and is what the demo runs
on; `anthropic` and `openai` produce the real posts once a key is supplied.
Every provider returns the same dict so the rest of the pipeline never has to
care which one produced the draft.
"""
import os
import re
import json
import random
import textwrap

from . import db, keywords as kw


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------

def slugify(text):
    """ASCII slug where possible, UTF-8 slug where not.

    Arabic titles strip to an empty string under an ASCII-only rule, and an
    empty slug is worse than a non-Latin one — Google indexes UTF-8 slugs
    fine. So: drop punctuation, keep letters and digits of any script.
    """
    s = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s, flags=re.UNICODE)
    if len(s) > 70:
        s = s[:70].rsplit("-", 1)[0]      # never cut a word in half
    s = s.strip("-")
    return s or "post"


def word_count(html):
    return len(re.sub(r"<[^>]+>", " ", html).split())


SYSTEM_PROMPT = """You are a working real-estate writer producing blog posts for \
a Dubai property agency's website. The audience is largely international buyers \
and investors looking at the UAE. Write the way a knowledgeable agent talks to a \
client: plain, specific, useful. No hype, no filler openings like "In today's \
fast-paced market", no stock phrases, no emoji.

Rules:
- 700-1000 words.
- Open with the reader's actual problem in one or two sentences. Never open with a definition.
- Use concrete numbers, timeframes and steps. If you don't know a current figure, \
describe how the reader can check it rather than inventing one.
- Never invent statistics, prices, laws, fees or named sources. Dubai property \
regulation changes often: describe the process and name the authority to verify \
with (DLD, RERA, the developer), never state a fee or rule as current fact.
- Prices in AED unless the keyword says otherwise.
- International English. Cover the topic honestly, including the downsides.

Return JSON only, matching the schema you are given."""

POST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "excerpt": {"type": "string"},
        "meta_title": {"type": "string"},
        "meta_desc": {"type": "string"},
        "body_html": {
            "type": "string",
            "description": "Article body as HTML. Use <h2>, <h3>, <p>, <ul>, <li>, "
                           "<strong> only. No <html>, <head>, <body> or <h1>.",
        },
    },
    "required": ["title", "excerpt", "meta_title", "meta_desc", "body_html"],
    "additionalProperties": False,
}


def _user_prompt(keyword):
    bits = [f'Target keyword: "{keyword["phrase"]}"',
            f'Search intent: {keyword["intent"]}']
    if keyword.get("locality"):
        bits.append(f'Locality: {keyword["locality"]} — keep local references generic '
                    f'unless they are facts anyone can verify.')
    bits.append("Write the post now.")
    return "\n".join(bits)


# --------------------------------------------------------------------------
# provider: anthropic
# --------------------------------------------------------------------------

def generate_anthropic(keyword, model="claude-opus-5"):
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": POST_SCHEMA}},
        messages=[{"role": "user", "content": _user_prompt(keyword)}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("model declined this keyword; skip it or reword the phrase")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


# --------------------------------------------------------------------------
# provider: openai
# --------------------------------------------------------------------------

def generate_openai(keyword, model="gpt-4.1"):
    from openai import OpenAI

    client = OpenAI()  # reads OPENAI_API_KEY
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(keyword)
                + "\n\nReturn a JSON object with keys: "
                  "title, excerpt, meta_title, meta_desc, body_html."},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


# --------------------------------------------------------------------------
# provider: template  (no API key — used for the demo and as a fallback)
# --------------------------------------------------------------------------

_OPENERS = [
    "Most people ask this question with a deadline already in mind — a lease ending, "
    "a job starting, a sale that has to complete before the school year.",
    "The honest answer is that it depends on a handful of variables, and the sooner "
    "you know which ones apply to you, the less time you waste.",
    "There is a short answer and a long one. The short answer rarely survives contact "
    "with a real property, so here is the long one.",
    "Get this wrong and it costs you weeks rather than dirhams — and on a purchase "
    "with a handover date attached, weeks are the expensive part.",
]

_SECTIONS = {
    "informational": [
        ("What actually decides the outcome",
         ["The condition of the property relative to others on the same street.",
          "How long comparable listings have been sitting.",
          "Whether your timeline is fixed or flexible.",
          "The paperwork you already hold versus the paperwork you still need to request."]),
        ("A sequence that works",
         ["Establish your non-negotiables in writing before you look at anything.",
          "Pull three comparable sales from the last six months, not the last two years.",
          "Get the boring documents early — title, lease terms, service charge history.",
          "Only then start booking viewings."]),
        ("Where people lose time", None),
        ("What to do this week", None),
    ],
    "commercial": [
        ("How to compare like with like",
         ["Ask what is included, not just what is charged.",
          "Separate one-off fees from recurring ones.",
          "Ask what happens if the sale falls through — that clause is where the real cost sits.",
          "Get every quoted figure in writing with a date on it."]),
        ("What the numbers usually look like", None),
        ("The trade-off nobody mentions", None),
        ("How to decide", None),
    ],
    "transactional": [
        ("Before you commit to anything",
         ["Confirm your budget with a lender, not a calculator.",
          "Read the full listing, including the small print on tenure and charges.",
          "Book a second viewing at a different time of day.",
          "Ask directly why the current owner is moving."]),
        ("What happens once you proceed", None),
        ("The documents to have ready", None),
        ("Next step", None),
    ],
    "local": [
        ("What the area is actually like",
         ["Walk it on a weekday morning and a Saturday afternoon — they are different places.",
          "Check transport at the times you would really travel.",
          "Look at what is being built nearby, not just what is there now.",
          "Talk to someone who already lives there."]),
        ("What tends to sell, and what sits", None),
        ("Practical considerations", None),
        ("If you are moving here", None),
    ],
}

_PROSE = [
    "The pattern is consistent enough to plan around. People move quickly on the parts "
    "that feel urgent and slowly on the parts that actually control the timeline, which "
    "is the wrong way round. Documents and finance take as long as they take, and no "
    "amount of enthusiasm shortens them.",
    "Set a date and work backwards from it. If the date is fixed by something outside "
    "your control, say so early and loudly — everyone in the chain plans differently "
    "when they know there is a hard stop.",
    "Price is the visible number, but it is rarely the one that decides whether a move "
    "works. Timing, condition and how much flexibility the other side has will move the "
    "outcome further than a few percent on the asking figure.",
    "Ask for things in writing. Not because anyone is being dishonest, but because "
    "written answers are specific and spoken ones drift. A figure with a date attached "
    "is a figure you can hold someone to.",
    "Do the unglamorous checks first. Title, tenure, charges, planning history — they "
    "are dull, they are cheap to look at, and they are the only things that reliably "
    "kill a deal late.",
    "Comparables are only useful if they are genuinely comparable. Same street is better "
    "than same community, same layout is better than same number of bedrooms, and anything "
    "older than six months is context rather than evidence.",
    "Be honest with yourself about what is a preference and what is a requirement. "
    "Preferences are negotiable and requirements are not, and confusing the two is how "
    "people end up three months in on a property that was never going to work.",
    "Keep one written record of every figure, date and promise, and share it with whoever "
    "is acting for you. When something slips — and something usually does — the person "
    "with the clearest notes sets the terms of the conversation.",
]


# Keyword lists are typed lowercase; these still need to read as proper nouns
# in a headline. Extend as his own list arrives.
_PROPER_NOUNS = (
    "Dubai", "Abu Dhabi", "Sharjah", "UAE", "Dubai Marina", "Downtown Dubai",
    "Palm Jumeirah", "Business Bay", "JVC", "JLT", "DIFC", "Emaar", "DAMAC",
    "Nakheel", "RERA", "DLD", "Expo", "Golden Visa",
)


def _fix_proper_nouns(text):
    for noun in sorted(_PROPER_NOUNS, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(noun)}\b", noun, text, flags=re.IGNORECASE)
    return text


def generate_template(keyword):
    phrase = keyword["phrase"]
    intent = keyword.get("intent") or "informational"
    rng = random.Random(phrase.lower())          # deterministic per keyword
    title_phrase = phrase[0].upper() + phrase[1:]

    title_forms = {
        "informational": [f"{title_phrase}: what to check before you commit",
                          f"{title_phrase}, explained without the sales pitch",
                          f"A practical guide to {phrase}"],
        "commercial": [f"{title_phrase} — what it really costs, and what you get",
                       f"Comparing {phrase}: the questions that matter",
                       f"{title_phrase}: how to judge value"],
        "transactional": [f"{title_phrase}: a step-by-step walkthrough",
                          f"{title_phrase}: the order things actually happen in",
                          f"{title_phrase} — what happens, and when"],
        "local": [f"{title_phrase}: an honest look at the area",
                  f"What to know about {phrase}",
                  f"{title_phrase} — the practical detail"],
    }
    title = _fix_proper_nouns(rng.choice(title_forms.get(intent, title_forms["informational"])))

    parts = [f"<p>{rng.choice(_OPENERS)} This piece sets out what matters for "
             f"<strong>{phrase}</strong>, in the order it usually matters.</p>"]

    prose_pool = _PROSE[:]
    rng.shuffle(prose_pool)
    n = len(prose_pool)
    for i, (heading, bullets) in enumerate(_SECTIONS.get(intent, _SECTIONS["informational"])):
        parts.append(f"<h2>{heading}</h2>")
        parts.append(f"<p>{prose_pool[(i * 2) % n]}</p>")
        if bullets:
            parts.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            parts.append(f"<p>{prose_pool[(i * 2 + 1) % n]}</p>")
        else:
            parts.append(f"<p>{prose_pool[(i * 2 + 1) % n]}</p>")
            parts.append(f"<p>{prose_pool[(i * 2 + 3) % n]}</p>")

    parts.append("<h2>In short</h2>")
    parts.append(f"<p>Work backwards from your date, get the paperwork moving before you "
                 f"get emotionally attached to a property, and put every number in writing. "
                 f"If you want a second opinion on {phrase}, ask — it costs nothing to "
                 f"sanity-check a plan before you act on it.</p>")

    body = "\n".join(parts)
    excerpt = _fix_proper_nouns(
        f"A plain-English look at {phrase} — what decides the outcome, where people "
        f"lose time, and the checks worth doing first.")

    return {
        "title": title,
        "excerpt": excerpt,
        "meta_title": _clip(title, 60),
        "meta_desc": _clip(excerpt, 155),
        "body_html": body,
    }


def _clip(text, limit):
    """Trim to a length search engines will show, on a word boundary."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-—") + "…"


PROVIDERS = {
    "template": generate_template,
    "anthropic": generate_anthropic,
    "openai": generate_openai,
}


def pick_provider(conn):
    """Explicit setting wins; otherwise use whichever key is present."""
    chosen = db.get_setting(conn, "provider")
    if chosen in PROVIDERS:
        return chosen
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "template"


def generate_draft(conn, keyword, provider=None):
    provider = provider or pick_provider(conn)
    fn = PROVIDERS[provider]
    try:
        data = fn(keyword)
    except Exception as exc:
        if provider == "template":
            raise
        # never lose the run because a key expired mid-batch
        db.log_event(conn, None, "generation_fallback", f"{provider}: {exc}")
        provider, data = "template", generate_template(keyword)

    slug = slugify(data["title"])
    now = db.now()
    cur = conn.execute(
        """INSERT INTO posts (keyword_id, title, slug, excerpt, body_html, meta_title,
                              meta_desc, word_count, provider, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (keyword["id"], data["title"], slug, data["excerpt"], data["body_html"],
         data.get("meta_title"), data.get("meta_desc"), word_count(data["body_html"]),
         provider, db.PENDING, now, now),
    )
    post_id = cur.lastrowid
    kw.mark_used(conn, keyword["id"])
    db.log_event(conn, post_id, "draft_created", f"provider={provider}")
    conn.commit()
    return post_id


def run_batch(conn, count=3, provider=None):
    """Pull the next N topics and draft one post each."""
    topics = kw.next_topics(conn, count)
    return [generate_draft(conn, t, provider) for t in topics]
