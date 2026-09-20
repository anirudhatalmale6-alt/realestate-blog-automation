{{--
    Article structured data — include this inside the <head> of your blog post
    view:

        @include('article-jsonld', ['post' => $post])

    This is what gives you the author, date and image in a Google result. The
    site currently outputs no JSON-LD on posts at all.

    Adjust the property accessors to match your model if they differ.
--}}
@php
    $columns = config('blogbot.columns');

    $title   = $post->{$columns['title']} ?? '';
    $slug    = $post->{$columns['slug']} ?? '';
    $excerpt = $columns['excerpt'] ? ($post->{$columns['excerpt']} ?? '') : '';
    $locale  = $columns['locale'] ? ($post->{$columns['locale']} ?? 'en') : 'en';
    $prefix  = $locale === config('blogbot.permalink.default_locale') ? '' : "/$locale";

    $published = $columns['published_at'] ? ($post->{$columns['published_at']} ?? null) : null;

    // Featured image: the live site stores these under /storage/blog/.
    $image = $post->featured_image ?? $post->image ?? null;

    $data = array_filter([
        '@context'      => 'https://schema.org',
        '@type'         => 'Article',
        'headline'      => \Illuminate\Support\Str::limit($title, 110, ''),
        'description'   => $excerpt ?: null,
        'inLanguage'    => $locale,
        'datePublished' => $published ? \Illuminate\Support\Carbon::parse($published)->toAtomString() : null,
        'dateModified'  => optional($post->updated_at)->toAtomString(),
        'image'         => $image ? url(\Illuminate\Support\Str::startsWith($image, ['http', '/']) ? $image : '/storage/' . $image) : null,
        'mainEntityOfPage' => [
            '@type' => 'WebPage',
            '@id'   => url($prefix . '/blog/' . $slug),
        ],
        'author' => [
            '@type' => 'Organization',
            'name'  => 'DXBProperty',
            'url'   => url('/'),
        ],
        'publisher' => [
            '@type' => 'Organization',
            'name'  => 'DXBProperty',
            'url'   => url('/'),
        ],
    ]);
@endphp

<script type="application/ld+json">
{!! json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT) !!}
</script>
