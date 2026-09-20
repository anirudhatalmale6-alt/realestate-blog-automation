"""Publishing + the social distribution hook.

The publisher is an adapter: swap the adapter for whatever the site actually
runs on and nothing else in the pipeline changes.

dxbproperty.ae is Laravel (PHP 8.4 / LiteSpeed) with its own blog at /blog and
/ar/blog, so `LaravelApiPublisher` is the live path — it POSTs the finished
article to a single token-protected route added to his app. `WordPressPublisher`
is kept because the adapter interface is the point, not because this site needs
it.

Social distribution is deliberately built now and switched off. `fan_out()`
reads the `distribution_channels` table, and every publish calls it. Today the
table is empty so it is a no-op; adding a channel row later turns it on with
no change to the publish path.
"""
import json
import urllib.request
import urllib.error
import base64
from datetime import datetime, timedelta

from . import db


class PublishError(Exception):
    pass


# --------------------------------------------------------------------------
# adapters
# --------------------------------------------------------------------------

class BasePublisher:
    name = "base"

    def publish(self, post):
        raise NotImplementedError


class DryRunPublisher(BasePublisher):
    """Used by the demo and by tests. Pretends to publish, records where."""
    name = "dryrun"

    def publish(self, post):
        return {"remote_id": f"dry-{post['id']}",
                "remote_url": f"https://example.com/blog/{post['slug']}/"}


class WordPressPublisher(BasePublisher):
    """WordPress REST API v2 with an Application Password.

    Needs: site URL, a WP user with author/editor rights, and an Application
    Password (Users -> Profile -> Application Passwords). Not the login
    password - the application password can be revoked on its own.
    """
    name = "wordpress"

    def __init__(self, site_url, username, app_password, category_id=None, author_id=None):
        self.base = site_url.rstrip("/") + "/wp-json/wp/v2"
        token = base64.b64encode(f"{username}:{app_password}".encode()).decode()
        self.auth = f"Basic {token}"
        self.category_id = category_id
        self.author_id = author_id

    def _call(self, path, payload):
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": self.auth},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise PublishError(f"WP {e.code}: {e.read().decode()[:400]}") from e
        except urllib.error.URLError as e:
            raise PublishError(f"WP unreachable: {e.reason}") from e

    def publish(self, post):
        payload = {
            "title": post["title"],
            "slug": post["slug"],
            "content": post["body_html"],
            "excerpt": post["excerpt"] or "",
            "status": "publish",
        }
        if self.category_id:
            payload["categories"] = [int(self.category_id)]
        if self.author_id:
            payload["author"] = int(self.author_id)
        data = self._call("/posts", payload)
        return {"remote_id": str(data.get("id")), "remote_url": data.get("link")}


class LaravelApiPublisher(BasePublisher):
    """POST the finished article to a token-protected route in his Laravel app.

    The route is ~60 lines added to his codebase (see `laravel/` in this repo).
    Nothing here needs a server login, a database password, or SSH.

    The payload deliberately uses OUR field names. The Laravel side maps them to
    whatever his `blogs` table actually calls its columns, so an unexpected
    schema is one config array to edit, not a rewrite on this side.
    """
    name = "laravel"

    def __init__(self, endpoint, token, locale="en", timeout=30):
        self.endpoint = endpoint
        self.token = token
        self.locale = locale
        self.timeout = timeout

    def _payload(self, post):
        return {
            "locale": post.get("locale") or self.locale,
            "title": post["title"],
            "slug": post["slug"],
            "excerpt": post["excerpt"] or "",
            "body_html": post["body_html"],
            "meta_title": post.get("meta_title") or post["title"],
            "meta_desc": post.get("meta_desc") or post["excerpt"] or "",
            "status": "published",
            "published_at": post.get("scheduled_for") or db.now(),
            # set when the Arabic half of a pair is sent, so his app can link
            # the two rows as translations of each other
            "translation_of": post.get("translation_remote_id"),
        }

    def publish(self, post):
        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(self._payload(post)).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            raise PublishError(f"Laravel {e.code}: {e.read().decode()[:400]}") from e
        except urllib.error.URLError as e:
            raise PublishError(f"Laravel endpoint unreachable: {e.reason}") from e

        if not data.get("id"):
            raise PublishError(f"endpoint returned no post id: {str(data)[:200]}")
        return {"remote_id": str(data["id"]), "remote_url": data.get("url")}


def build_publisher(conn):
    """Which adapter to use, from settings. Defaults to dry-run so nothing
    can go live by accident before the site is wired up."""
    kind = db.get_setting(conn, "publisher", "dryrun")
    if kind == "laravel":
        endpoint = db.get_setting(conn, "laravel_endpoint", "")
        token = db.get_setting(conn, "laravel_token", "")
        if not endpoint or not token:
            raise PublishError("laravel_endpoint and laravel_token must both be set")
        return LaravelApiPublisher(endpoint, token)
    if kind == "wordpress":
        return WordPressPublisher(
            site_url=db.get_setting(conn, "wp_site_url", ""),
            username=db.get_setting(conn, "wp_username", ""),
            app_password=db.get_setting(conn, "wp_app_password", ""),
            category_id=db.get_setting(conn, "wp_category_id"),
            author_id=db.get_setting(conn, "wp_author_id"),
        )
    return DryRunPublisher()


# --------------------------------------------------------------------------
# social distribution hook (built, dormant)
# --------------------------------------------------------------------------

def social_blurb(post, limit=240):
    """One-line teaser + link placeholder. Channels format from this."""
    text = post["excerpt"] or post["title"]
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "…"
    return text


def fan_out(conn, post, delay_minutes=0):
    """Queue a distribution job per enabled channel. No channels = no-op."""
    channels = conn.execute(
        "SELECT * FROM distribution_channels WHERE enabled=1"
    ).fetchall()
    if not channels:
        return 0
    run_at = (datetime.utcnow() + timedelta(minutes=delay_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    payload = json.dumps({
        "text": social_blurb(post),
        "url": post.get("remote_url"),
        "title": post["title"],
    })
    for ch in channels:
        conn.execute(
            "INSERT INTO distribution_jobs (post_id, channel_id, status, run_at, payload, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (post["id"], ch["id"], "queued", run_at, payload, db.now()),
        )
    db.log_event(conn, post["id"], "distribution_queued", f"{len(channels)} channel(s)")
    conn.commit()
    return len(channels)


# --------------------------------------------------------------------------
# the publish step
# --------------------------------------------------------------------------

def publish_post(conn, post_id, publisher=None):
    row = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if row is None:
        raise ValueError(f"no post {post_id}")
    post = dict(row)
    if post["status"] == db.PUBLISHED:
        return post

    publisher = publisher or build_publisher(conn)
    try:
        result = publisher.publish(post)
    except PublishError as exc:
        db.log_event(conn, post_id, "publish_failed", str(exc))
        conn.commit()
        raise

    conn.execute(
        "UPDATE posts SET status=?, published_at=?, remote_id=?, remote_url=?, updated_at=? "
        "WHERE id=?",
        (db.PUBLISHED, db.now(), result.get("remote_id"), result.get("remote_url"),
         db.now(), post_id),
    )
    db.log_event(conn, post_id, "published", f"{publisher.name} {result.get('remote_url')}")
    conn.commit()

    post.update(result)
    fan_out(conn, post)          # dormant until channels exist
    return post


def run_due(conn, now=None):
    """Publish everything whose slot has arrived. This is the cron entry point."""
    from . import scheduler
    published, failed = [], []
    for post in scheduler.due_posts(conn, now=now):
        try:
            published.append(publish_post(conn, post["id"]))
        except PublishError as exc:
            failed.append((post["id"], str(exc)))
    return published, failed
