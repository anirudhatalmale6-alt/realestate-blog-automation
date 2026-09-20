<?php

/*
|--------------------------------------------------------------------------
| Blogbot routes — paste into routes/web.php (or require this file from it)
|--------------------------------------------------------------------------
|
| Two things:
|   1. the import endpoint the Python engine posts finished articles to
|   2. a sitemap, because the site currently has none
|
| The old-slug 301s are deliberately NOT routes. A route for /blog/{slug} here
| would shadow your existing one and 404 every real post. They live in
| RedirectLegacyBlogSlugs middleware instead, which only acts on a response
| that was already going to be a 404.
|
*/

use App\Http\Controllers\BlogbotImportController;
use Illuminate\Support\Facades\Route;

// 1. Import endpoint -------------------------------------------------------

Route::post('/blogbot/import', [BlogbotImportController::class, 'store'])
    ->middleware('blogbot.token')
    ->withoutMiddleware([\Illuminate\Foundation\Http\Middleware\VerifyCsrfToken::class]);

// 2. Sitemap ---------------------------------------------------------------

Route::get('/sitemap.xml', function () {
    $columns = config('blogbot.columns');
    $model   = config('blogbot.model');

    $posts = $model::query()
        ->when($columns['status'], fn ($q) => $q->where($columns['status'], config('blogbot.status_values.published')))
        ->get();

    $urls = [
        ['loc' => url('/'), 'priority' => '1.0'],
        ['loc' => url('/projects'), 'priority' => '0.9'],
        ['loc' => url('/blog'), 'priority' => '0.8'],
        ['loc' => url('/page/about-us'), 'priority' => '0.5'],
        ['loc' => url('/contact'), 'priority' => '0.5'],
    ];

    foreach ($posts as $post) {
        $locale = $columns['locale'] ? ($post->{$columns['locale']} ?? 'en') : 'en';
        $prefix = $locale === config('blogbot.permalink.default_locale') ? '' : "/$locale";

        $urls[] = [
            'loc'      => url($prefix . '/blog/' . $post->{$columns['slug']}),
            'lastmod'  => optional($post->updated_at)->toAtomString(),
            'priority' => '0.7',
        ];
    }

    $xml = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
         . "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n";

    foreach ($urls as $u) {
        $xml .= "  <url>\n    <loc>" . htmlspecialchars($u['loc'], ENT_XML1) . "</loc>\n";
        if (! empty($u['lastmod'])) {
            $xml .= "    <lastmod>{$u['lastmod']}</lastmod>\n";
        }
        $xml .= "    <priority>{$u['priority']}</priority>\n  </url>\n";
    }

    $xml .= "</urlset>\n";

    return response($xml, 200, ['Content-Type' => 'application/xml']);
});
