# The Laravel side — what goes into dxbproperty.ae

Your site is Laravel (PHP 8.4, LiteSpeed) with its own blog at `/blog` and
`/ar/blog`, so there is no WordPress involved anywhere. This folder is the
entire server-side footprint: **one route, one controller, two middlewares, one
new table, one artisan command.** Nothing existing is modified.

> **Honest caveat:** I have not seen your `blogs` table or run this inside your
> app. Every file here parses cleanly (`php -l`) and the engine side is tested
> against a stub that behaves like this route (`test_laravel_adapter.py`, 14
> checks), but the column names in `config/blogbot.php` are my best guess from
> what the live site renders. Send me the migration or `SHOW CREATE TABLE` and
> I will correct them — it is one config file, not a rewrite.

## Files

| File | Goes to | What it does |
|---|---|---|
| `config/blogbot.php` | `config/blogbot.php` | **The only file you should need to edit.** Column mapping + token. |
| `app/Http/Controllers/BlogbotImportController.php` | same path | Receives a finished article, saves it as a post. |
| `app/Http/Middleware/BlogbotToken.php` | same path | Rejects anything without the bearer token. |
| `app/Http/Middleware/RedirectLegacyBlogSlugs.php` | same path | 301s the old placeholder URLs after the slug repair. |
| `app/Console/Commands/FixBlogSlugs.php` | same path | Rebuilds the Latin slugs from the real titles. |
| `database/migrations/2026_09_20_000000_create_blog_slug_redirects_table.php` | same path | One new table. Touches nothing existing. |
| `routes/blogbot.php` | `routes/blogbot.php` | Import endpoint + sitemap. |

## Install

1. Copy the files in.

2. Add the token to `.env`:

   ```
   BLOGBOT_TOKEN=paste-a-long-random-string-here
   ```

   Generate one with `php -r "echo bin2hex(random_bytes(32));"`.

3. Load the routes — at the bottom of `routes/web.php`:

   ```php
   require __DIR__ . '/blogbot.php';
   ```

4. Register the middlewares.

   **Laravel 11 / 12** — in `bootstrap/app.php`:

   ```php
   ->withMiddleware(function (Middleware $middleware) {
       $middleware->alias([
           'blogbot.token' => \App\Http\Middleware\BlogbotToken::class,
       ]);
       $middleware->appendToGroup('web', \App\Http\Middleware\RedirectLegacyBlogSlugs::class);
   })
   ```

   **Laravel 10 or below** — in `app/Http/Kernel.php`:

   ```php
   protected $middlewareAliases = [
       // ...
       'blogbot.token' => \App\Http\Middleware\BlogbotToken::class,
   ];

   protected $middlewareGroups = [
       'web' => [
           // ... your existing entries, then:
           \App\Http\Middleware\RedirectLegacyBlogSlugs::class,
       ],
   ];
   ```

5. Run the migration:

   ```bash
   php artisan migrate
   ```

6. Check the column names in `config/blogbot.php` against your real table.

## The slug repair

Every blog URL on the live site is seeder output. The titles and bodies are
real; only the slugs were never replaced:

```
/blog/sapiente-quo-quod-vitae-eligendi        "Complete Guide to Buying Property in Dubai"
/blog/minus-corrupti-ex-error-libero-quos     "Dubai Real Estate Laws and Regulations"
/ar/blog/quod-ad-provident-dolorem            (same story on the Arabic side)
```

Fix it:

```bash
php artisan blog:fix-slugs           # dry run — prints the full list, writes nothing
php artisan blog:fix-slugs --apply   # writes, inside a transaction
```

The dry run is the default on purpose: read the list first, then apply. Every
old slug is recorded in `blog_slug_redirects`, and `RedirectLegacyBlogSlugs`
301s the old URL to the new one, so anything Google has already indexed keeps
working.

That middleware only inspects responses that were **already going to be a 404**
— if your blog controller finds the post, it does nothing at all. It cannot
shadow a working page. (A `/blog/{slug}` route would have, which is why this
isn't one.)

## Why a token endpoint rather than a module

You can have it either way. The endpoint means the engine can run anywhere, the
change to your codebase is one route, and I never need a login to your server,
your database, or SSH. If you would rather I built it as a module inside your
repo, that is the other option — cleaner long term, but it means working inside
your code.

## Still missing on the site, worth adding while we're here

- **No `sitemap.xml`.** `routes/blogbot.php` adds one and it updates itself as
  posts publish.
- **No `Article` structured data** on posts — that is what produces the author,
  date and image in a Google result. Snippet in `views/article-jsonld.blade.php`.
- **Homepage has no meta description**, so Google writes its own snippet.
- **Footer social link points at `twitter.com/example`.**
