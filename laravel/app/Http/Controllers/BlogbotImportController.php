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
        // Prefer a normalised Latin slug. Str::slug() empties Arabic titles, so
        // when that happens keep the UTF-8 slug we were sent — Google indexes
        // those fine, and a random string would be worse than the Latin we are
        // replacing. Random is the last resort only.
        $base = trim($slug);
        $latin = Str::slug($base);

        if ($latin !== '') {
            $base = $latin;
        } elseif ($base === '') {
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
