<?php

/*
|--------------------------------------------------------------------------
| Blogbot — the only file you should need to edit
|--------------------------------------------------------------------------
|
| Drop this in config/blogbot.php.
|
| I have not seen your blogs table yet, so the column names below are my best
| guess from what the live site renders (title, slug, excerpt, body, meta,
| author, category, featured image, locale, published_at). Change the right
| hand side of each pair to whatever your table actually calls the column and
| everything else in this package keeps working.
|
| Set a column to null to skip it entirely — the importer will not touch it.
|
*/

return [

    // Bearer token the Python engine sends. Put the real value in .env:
    //   BLOGBOT_TOKEN=some-long-random-string
    // Generate one with:  php -r "echo bin2hex(random_bytes(32));"
    'token' => env('BLOGBOT_TOKEN'),

    // Eloquent model for your blog posts.
    'model' => \App\Models\Blog::class,

    // Table name — used by the slug repair command.
    'table' => 'blogs',

    // our field  =>  your column   (null = don't write this field)
    'columns' => [
        'title'          => 'title',
        'slug'           => 'slug',
        'excerpt'        => 'excerpt',
        'body_html'      => 'body',
        'meta_title'     => 'meta_title',
        'meta_desc'      => 'meta_description',
        'status'         => 'status',
        'published_at'   => 'published_at',
        'locale'         => 'locale',
        'translation_of' => 'translation_of',
    ],

    // Values written to the status column. If your table uses a boolean
    // `is_published` instead, set 'status' => 'is_published' above and change
    // these to true / false.
    'status_values' => [
        'published' => 'published',
        'draft'     => 'draft',
    ],

    // Columns the importer should always set to a fixed value — author id,
    // category id, whatever your schema requires but the engine has no opinion
    // about. Leave empty if there are none.
    'defaults' => [
        // 'author_id'   => 1,
        // 'category_id' => 2,
    ],

    // Where a published post lives, used to build the URL we hand back to the
    // engine. {locale} is dropped for the default locale, {slug} is filled in.
    'permalink' => [
        'default_locale' => 'en',
        'pattern'        => '/{locale}/blog/{slug}',
    ],
];
