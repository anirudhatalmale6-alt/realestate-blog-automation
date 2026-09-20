# Blog automation — generator, approval queue and scheduler

Built for the real-estate site upgrade (Freelancer project 40721961). This is
phase one: **automated content generation + automated scheduling, with a human
approval gate in the middle.** Nothing publishes without a click.

## What it does

1. **Keywords in.** Paste a list (one phrase per line, or CSV with
   `phrase,intent,locality,priority`). Intent and locality are auto-detected if
   you don't supply them.
2. **Drafts out.** Picks the least-recently-used keywords first so the blog
   never writes the same thing twice, and drafts a post per keyword.
3. **You approve.** Every draft lands in `pending_review`. Approve, reject, or
   leave it. Rejecting puts the keyword back in the pool for a fresh attempt.
4. **The calendar places it.** On approval the post takes the next free publish
   slot — evenly spaced, on your chosen days and times, never double-booked and
   never closer together than your minimum gap.
5. **Cron publishes it.** A job every 15 minutes pushes anything whose slot has
   arrived, then calls the social distribution hook.

## Running it

```bash
python3 demo.py --reset     # seed sample keywords, draft 3, approve, show calendar
python3 web/app.py          # UI on http://127.0.0.1:5057
python3 test_pipeline.py    # 30 end-to-end checks
```

Cron in production:

```
*/15 * * * *  cd /path/to/blogbot && python3 cron.py publish
0 6 * * 1     cd /path/to/blogbot && python3 cron.py draft 3
```

`cron.py status` prints the current queue.

## The writer

Three providers, same output shape — the rest of the pipeline never knows which
one ran.

| Provider   | Needs | Use |
|------------|-------|-----|
| `template` | nothing | The demo, and the automatic fallback if an API call fails mid-batch |
| `anthropic`| `ANTHROPIC_API_KEY` | Claude, with a JSON schema so the output is always parseable |
| `openai`   | `OPENAI_API_KEY` | GPT |

Keys are read from the environment and never written to the database. With no
key set it runs on `template`, which is why the demo works out of the box —
those posts are structurally real but generic; the live posts come from the
model once a key is in place.

The system prompt bans invented statistics, prices and named sources. That
matters more in property than most sectors.

## The calendar

Configured on the Settings page, stored in `settings`, not in code:

| Setting | Default | Meaning |
|---|---|---|
| `publish_days` | `1,2,3` | Mon=0 … Sun=6 → Tue, Wed, Thu |
| `publish_times` | `09:30,13:00` | Local times |
| `timezone` | `Europe/London` | |
| `min_gap_hours` | `36` | Never two posts closer than this |
| `posts_per_week` | `2` | Target rhythm |

The default days and times are a reasonable starting point for a UK property
audience — **they are not measured**. Once the site has a few months of
analytics, replace them with the slots that actually perform. That is a
settings change, not a code change.

"Re-space everything" re-flows the whole queue onto clean slots after you change
the rhythm, keeping the existing order.

## Publishing

`publisher.py` is an adapter. `WordPressPublisher` posts to the WP REST API v2
using an **Application Password** (Users → Profile → Application Passwords) —
not the account password, so it can be revoked on its own. `DryRunPublisher` is
the default, so nothing can go live before the site is wired up.

Swap in a different adapter for a non-WordPress site and nothing else changes.

## Social distribution — built, dormant

Every publish calls `fan_out()`, which queues one job per row in
`distribution_channels`. No channels are configured, so today it is a no-op.
Adding a Facebook Page or LinkedIn channel later switches it on without touching
the publish path — that is the "future hook" in the brief, built now rather than
retrofitted.

## Layout

```
core/db.py          schema, status constants, event log
core/keywords.py    list parsing, intent detection, topic selection
core/generator.py   provider adapters + the draft record
core/scheduler.py   slot maths, approve/reject/pause, calendar, rebalance
core/publisher.py   WP + dry-run adapters, social hook, cron publish step
web/app.py          Flask UI (dashboard, keywords, post review, calendar, settings)
cron.py             publish / draft / status
demo.py             seeded walkthrough
test_pipeline.py    30 end-to-end checks
```

SQLite, no build step, no external services. Everything is replaceable in
isolation.
