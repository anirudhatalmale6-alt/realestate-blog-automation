<?php

namespace App\Http\Controllers;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Str;

/**
 * Receives a finished article from the blog engine and saves it as a normal
 * post. This is the entire server-side surface — one route, one controller.
 *
 * It never deletes, never overwrites a post it did not create in this request,
 * and never touches a column that is not named in config/blogbot.php.
 */
class BlogbotImportController extends Controller
{
    public function store(Request $request): JsonResponse
    {
        $data = $request->validate([
            'title'          => ['required', 'string', 'max:255'],
            'slug'           => ['required', 'string', 'max:255'],
            'excerpt'        => ['nullable', 'string'],
            'body_html'      => ['required', 'string'],
            'meta_title'     => ['nullable', 'string', 'max:255'],
            'meta_desc'      => ['nullable', 'string', 'max:500'],
            'locale'         => ['nullable', 'string', 'max:5'],
            'status'         => ['nullable', 'in:published,draft'],
            'published_at'   => ['nullable', 'date'],
            'translation_of' => ['nullable'],
        ]);

        $columns = config('blogbot.columns');
        $model   = config('blogbot.model');
        $locale  = $data['locale'] ?? config('blogbot.permalink.default_locale');

        // Never collide with an existing post: -2, -3, ... until the slug is free.
        $data['slug'] = $this->uniqueSlug($model, $columns['slug'], $data['slug'], $locale, $columns['locale']);

        // A published post with a null published_at sorts and renders wrongly on
        // most blog templates, so never let one through without a date.
        if (($data['status'] ?? 'published') === 'published' && empty($data['published_at'])) {
            $data['published_at'] = now();
        }

        $row = config('blogbot.defaults', []);

        foreach ($columns as $field => $column) {
            if ($column === null) {
                continue;
            }
            if ($field === 'status') {
                $key = $data['status'] ?? 'published';
                $row[$column] = config("blogbot.status_values.$key");
                continue;
            }
            if ($field === 'locale') {
                $row[$column] = $locale;
                continue;
            }
            if (array_key_exists($field, $data) && $data[$field] !== null) {
                $row[$column] = $data[$field];
            }
        }

        $post = $model::create($row);

        return response()->json([
            'id'  => $post->getKey(),
            'url' => url($this->permalink($locale, $data['slug'])),
        ], 201);
    }

    private function uniqueSlug(string $model, string $slugColumn, string $slug, string $locale, ?string $localeColumn): string
    {
        // Str::slug() transliterates a non-Latin slug into ASCII gibberish
        // rather than returning '' — "دليل-شراء" becomes "dlyl-shraaa". Keep
        // the UTF-8 slug in that case; Google indexes those fine.
        $base = trim($slug);

        if (preg_match('/\p{L}/u', $base) === 1 && preg_match('/[A-Za-z]/', $base) !== 1) {
            $base = trim(Str::lower(preg_replace('/[^\p{L}\p{N}]+/u', '-', $base)), '-');
        } else {
            $base = Str::slug($base);
        }

        if ($base === '') {
            $base = 'post-' . Str::lower(Str::random(6));
        }

        $candidate = $base;
        $n = 1;

        while (true) {
            $query = $model::where($slugColumn, $candidate);
            if ($localeColumn !== null) {
                $query->where($localeColumn, $locale);
            }
            if (! $query->exists()) {
                return $candidate;
            }
            $candidate = $base . '-' . (++$n);
        }
    }

    private function permalink(string $locale, string $slug): string
    {
        $pattern = config('blogbot.permalink.pattern');
        $default = config('blogbot.permalink.default_locale');

        $path = str_replace(
            ['{locale}', '{slug}'],
            [$locale === $default ? '' : $locale, $slug],
            $pattern
        );

        return '/' . ltrim(preg_replace('#/+#', '/', $path), '/');
    }
}
