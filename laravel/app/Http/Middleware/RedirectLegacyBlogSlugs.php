<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Symfony\Component\HttpFoundation\Response;

/**
 * Keeps the old placeholder blog URLs alive after the slug repair.
 *
 * This runs AFTER your own routing. It only looks at a response that is
 * already a 404, so it can never shadow a working post — if your blog
 * controller found the post, this middleware does nothing at all.
 *
 * Matches /blog/{slug} and /ar/blog/{slug}.
 */
class RedirectLegacyBlogSlugs
{
    public function handle(Request $request, Closure $next): Response
    {
        $response = $next($request);

        if ($response->getStatusCode() !== 404 || ! $request->isMethod('GET')) {
            return $response;
        }

        if (! preg_match('#^/(?:(\w{2})/)?blog/(.+?)/?$#', '/' . ltrim($request->path(), '/'), $m)) {
            return $response;
        }

        [, $locale, $slug] = $m + [null, null, null];
        $locale = $locale ?: 'en';

        $hit = DB::table('blog_slug_redirects')
            ->where('old_slug', $slug)
            ->where(function ($q) use ($locale) {
                $q->where('locale', $locale);
                if ($locale === 'en') {
                    $q->orWhereNull('locale')->orWhere('locale', '');
                }
            })
            ->first();

        if (! $hit) {
            return $response;
        }

        $prefix = $locale === config('blogbot.permalink.default_locale') ? '' : "/$locale";

        return redirect($prefix . '/blog/' . $hit->new_slug, 301);
    }
}
