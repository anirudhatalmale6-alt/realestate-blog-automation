"""Proves the Laravel publisher adapter works before anything is installed on
his server.

Runs a stub HTTP endpoint that behaves the way the Laravel route does — checks
the bearer token, validates the payload, returns {id, url} — and drives the
real adapter against it.

    python3 test_laravel_adapter.py
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["BLOGBOT_DB"] = os.path.join(tempfile.mkdtemp(), "laravel-test.db")

from core import db, keywords as kw, generator, publisher  # noqa: E402

TOKEN = "test-token-" + "a" * 20
REQUIRED = ["title", "slug", "body_html", "locale", "status"]

received = []
PASS = FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok    {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")


class Stub(BaseHTTPRequestHandler):
    """Mimics routes/blogbot.php + BlogbotImportController."""

    def log_message(self, *a):
        pass

    def _json(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {TOKEN}":
            return self._json(401, {"message": "Unauthorized."})

        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode())
        missing = [f for f in REQUIRED if not payload.get(f)]
        if missing:
            return self._json(422, {"message": "validation failed", "missing": missing})

        received.append(payload)
        locale = payload["locale"]
        prefix = "" if locale == "en" else f"/{locale}"
        self._json(201, {
            "id": 900 + len(received),
            "url": f"https://dxbproperty.ae{prefix}/blog/{payload['slug']}",
        })


server = HTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=server.serve_forever, daemon=True).start()
ENDPOINT = f"http://127.0.0.1:{server.server_port}/blogbot/import"

conn = db.init()
kw.ingest(conn, "how to buy property in dubai\noff-plan vs ready property dubai")
ids = generator.run_batch(conn, 2, provider="template")

print("\nauth")
bad = publisher.LaravelApiPublisher(ENDPOINT, "wrong-token")
post = dict(conn.execute("SELECT * FROM posts WHERE id=?", (ids[0],)).fetchone())
try:
    bad.publish(post)
    check("wrong token is rejected", False, "it published anyway")
except publisher.PublishError as e:
    check("wrong token is rejected", "401" in str(e), str(e))

print("\npublishing")
pub = publisher.LaravelApiPublisher(ENDPOINT, TOKEN)
result = pub.publish(post)
check("returns the remote id", result["remote_id"] == "901", result)
check("returns the live url", result["remote_url"].startswith("https://dxbproperty.ae/blog/"), result)

sent = received[-1]
check("sends every field the route requires", all(sent.get(f) for f in REQUIRED), sent)
check("defaults to the english locale", sent["locale"] == "en", sent["locale"])
check("sends published status", sent["status"] == "published", sent["status"])
check("slug matches the post", sent["slug"] == post["slug"], (sent["slug"], post["slug"]))
check("meta_title falls back to the title when unset",
      sent["meta_title"], sent.get("meta_title"))

print("\narabic half of a pair")
ar = publisher.LaravelApiPublisher(ENDPOINT, TOKEN, locale="ar")
post_ar = dict(conn.execute("SELECT * FROM posts WHERE id=?", (ids[1],)).fetchone())
post_ar["slug"] = "دليل-شراء-العقارات-في-دبي"
post_ar["translation_remote_id"] = result["remote_id"]
res_ar = ar.publish(post_ar)
sent_ar = received[-1]
check("arabic post goes to the /ar url", "/ar/blog/" in res_ar["remote_url"], res_ar)
check("utf-8 slug survives the round trip", sent_ar["slug"] == "دليل-شراء-العقارات-في-دبي", sent_ar["slug"])
check("links back to the english post", sent_ar["translation_of"] == result["remote_id"], sent_ar)

print("\nfull publish path through the pipeline")
db.set_setting(conn, "publisher", "laravel")
db.set_setting(conn, "laravel_endpoint", ENDPOINT)
db.set_setting(conn, "laravel_token", TOKEN)
conn.commit()
built = publisher.build_publisher(conn)
check("settings select the laravel adapter", built.name == "laravel", built.name)

db.set_setting(conn, "laravel_token", "")
conn.commit()
try:
    publisher.build_publisher(conn)
    check("missing token refuses to build", False, "built anyway")
except publisher.PublishError:
    check("missing token refuses to build", True)

print("\nunreachable endpoint")
dead = publisher.LaravelApiPublisher("http://127.0.0.1:9/nope", TOKEN)
try:
    dead.publish(post)
    check("unreachable endpoint raises PublishError", False)
except publisher.PublishError:
    check("unreachable endpoint raises PublishError", True)

server.shutdown()
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
