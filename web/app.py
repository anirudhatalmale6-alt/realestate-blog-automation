"""Approval queue + calendar UI."""
import os
import sys
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import db, keywords as kw, generator, scheduler, publisher  # noqa: E402

app = Flask(__name__)
app.secret_key = os.environ.get("BLOGBOT_SECRET", "dev-only-change-me")


def conn():
    return db.init()


@app.template_filter("dt")
def _dt(value):
    if not value:
        return ""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime("%a %d %b, %H:%M")


@app.route("/")
def dashboard():
    c = conn()
    counts = {s: c.execute("SELECT COUNT(*) n FROM posts WHERE status=?", (s,)).fetchone()["n"]
              for s in (db.PENDING, db.SCHEDULED, db.PUBLISHED, db.REJECTED, db.PAUSED)}
    kw_total = c.execute("SELECT COUNT(*) n FROM keywords").fetchone()["n"]
    kw_unused = c.execute("SELECT COUNT(*) n FROM keywords WHERE times_used=0").fetchone()["n"]
    pending = c.execute(
        "SELECT p.*, k.phrase FROM posts p LEFT JOIN keywords k ON k.id=p.keyword_id "
        "WHERE p.status=? ORDER BY p.created_at ASC", (db.PENDING,)).fetchall()
    upcoming = c.execute(
        "SELECT * FROM posts WHERE status=? ORDER BY scheduled_for ASC LIMIT 5",
        (db.SCHEDULED,)).fetchall()
    cfg = scheduler.get_config(c)
    return render_template("dashboard.html", counts=counts, kw_total=kw_total,
                           kw_unused=kw_unused, pending=pending, upcoming=upcoming,
                           provider=generator.pick_provider(c), cfg=cfg)


@app.route("/keywords", methods=["GET", "POST"])
def keywords_page():
    c = conn()
    if request.method == "POST":
        added, updated = kw.ingest(c, request.form.get("keywords", ""))
        flash(f"{added} new keyword(s) added, {updated} updated.")
        return redirect(url_for("keywords_page"))
    rows = c.execute("SELECT * FROM keywords ORDER BY times_used ASC, priority DESC, id ASC"
                     ).fetchall()
    return render_template("keywords.html", rows=rows)


@app.route("/generate", methods=["POST"])
def generate():
    c = conn()
    n = int(request.form.get("count", 3))
    if not kw.next_topics(c, 1):
        flash("No unused keywords left — add more on the Keywords page.")
        return redirect(url_for("keywords_page"))
    ids = generator.run_batch(c, n)
    flash(f"Drafted {len(ids)} post(s). They are waiting for your approval.")
    return redirect(url_for("dashboard"))


@app.route("/post/<int:post_id>")
def post_detail(post_id):
    c = conn()
    row = c.execute("SELECT p.*, k.phrase FROM posts p LEFT JOIN keywords k ON k.id=p.keyword_id "
                    "WHERE p.id=?", (post_id,)).fetchone()
    if row is None:
        return "Not found", 404
    events = c.execute("SELECT * FROM events WHERE post_id=? ORDER BY id DESC", (post_id,)).fetchall()
    return render_template("post.html", post=row, events=events)


@app.route("/post/<int:post_id>/approve", methods=["POST"])
def approve(post_id):
    c = conn()
    slot = scheduler.approve(c, post_id, request.form.get("note", ""))
    flash(f"Approved — scheduled for {slot.strftime('%a %d %b at %H:%M')}.")
    return redirect(request.form.get("next") or url_for("dashboard"))


@app.route("/post/<int:post_id>/reject", methods=["POST"])
def reject(post_id):
    c = conn()
    scheduler.reject(c, post_id, request.form.get("note", ""))
    flash("Rejected. The keyword goes back in the pool for a fresh attempt.")
    return redirect(request.form.get("next") or url_for("dashboard"))


@app.route("/post/<int:post_id>/pause", methods=["POST"])
def pause(post_id):
    c = conn()
    scheduler.pause(c, post_id)
    flash("Paused and taken off the calendar.")
    return redirect(url_for("calendar_page"))


@app.route("/post/<int:post_id>/reschedule", methods=["POST"])
def reschedule(post_id):
    c = conn()
    when = scheduler.reschedule(c, post_id, request.form["when"])
    flash(f"Moved to {when.strftime('%a %d %b at %H:%M')}.")
    return redirect(url_for("calendar_page"))


@app.route("/calendar")
def calendar_page():
    c = conn()
    return render_template("calendar.html", weeks=scheduler.calendar(c, weeks=8),
                           cfg=scheduler.get_config(c))


@app.route("/rebalance", methods=["POST"])
def rebalance():
    c = conn()
    moved = scheduler.rebalance(c)
    flash(f"Re-spaced {len(moved)} scheduled post(s).")
    return redirect(url_for("calendar_page"))


@app.route("/publish-due", methods=["POST"])
def publish_due():
    c = conn()
    done, failed = publisher.run_due(c)
    flash(f"Published {len(done)}." + (f" {len(failed)} failed." if failed else ""))
    return redirect(url_for("calendar_page"))


@app.route("/settings", methods=["GET", "POST"])
def settings():
    c = conn()
    if request.method == "POST":
        scheduler.save_config(c, **{k: request.form[k] for k in scheduler.DEFAULTS
                                    if k in request.form})
        for k in ("provider", "publisher", "laravel_endpoint", "laravel_token",
                  "wp_site_url", "wp_username", "wp_app_password",
                  "wp_category_id", "wp_author_id"):
            if request.form.get(k) is not None:
                db.set_setting(c, k, request.form.get(k))
        c.commit()
        flash("Settings saved.")
        return redirect(url_for("settings"))
    cfg = {k: db.get_setting(c, k, v) for k, v in scheduler.DEFAULTS.items()}
    extra = {k: db.get_setting(c, k, "") for k in
             ("provider", "publisher", "laravel_endpoint", "laravel_token",
              "wp_site_url", "wp_username", "wp_app_password",
              "wp_category_id", "wp_author_id")}
    return render_template("settings.html", cfg=cfg, extra=extra,
                           active_provider=generator.pick_provider(c))


if __name__ == "__main__":
    db.init()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5057)), debug=False)
