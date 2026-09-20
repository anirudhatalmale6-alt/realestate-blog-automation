<?php

namespace App\Console\Commands;

use Illuminate\Console\Command;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;

/**
 * Replaces the placeholder Latin slugs on the live blog with slugs built from
 * the real titles, and records every old -> new pair so the old URLs keep
 * working via a 301.
 *
 * Every blog URL on dxbproperty.ae is currently seeder output — e.g.
 *   /blog/sapiente-quo-quod-vitae-eligendi
 * is "Complete Guide to Buying Property in Dubai". The titles and bodies are
 * real; only the slugs were never replaced.
 *
 *   php artisan blog:fix-slugs              # dry run — prints, changes nothing
 *   php artisan blog:fix-slugs --apply      # writes
 *
 * Nothing is deleted and no column other than `slug` is touched.
 */
class FixBlogSlugs extends Command
{
    protected $signature = 'blog:fix-slugs {--apply : actually write the changes}';

    protected $description = 'Rebuild placeholder blog slugs from their titles, keeping the old URLs alive via 301s';

    public function handle(): int
    {
        $table   = config('blogbot.table');
        $columns = config('blogbot.columns');
        $slugCol = $columns['slug'];
        $titleCol = $columns['title'];
        $localeCol = $columns['locale'];

        $apply = (bool) $this->option('apply');

        $rows = DB::table($table)->get();
        $this->info(sprintf('%d posts found in `%s`.', $rows->count(), $table));

        $planned = [];   // new slug (per locale) => reserve so we don't collide within this run
        $changes = [];

        foreach ($rows as $row) {
            $old = (string) ($row->{$slugCol} ?? '');
            $title = (string) ($row->{$titleCol} ?? '');
            $locale = $localeCol ? (string) ($row->{$localeCol} ?? '') : '';

            if ($title === '') {
                $this->warn("  skip id={$row->id}: no title, cannot build a slug");
                continue;
            }

            $new = $this->slugFor($title);

            if ($new === $old) {
                continue;
            }

            $new = $this->makeUnique($table, $slugCol, $localeCol, $locale, $new, $row->id, $planned);
            $planned["$locale|$new"] = true;

            $changes[] = ['id' => $row->id, 'old' => $old, 'new' => $new, 'title' => $title, 'locale' => $locale];
        }

        if (! $changes) {
            $this->info('Nothing to change — every slug already matches its title.');
            return self::SUCCESS;
        }

        foreach ($changes as $c) {
            $this->line(sprintf(
                "  [%s] %s\n        %s  ->  %s",
                $c['locale'] ?: '-', Str::limit($c['title'], 70), $c['old'], $c['new']
            ));
        }

        if (! $apply) {
            $this->newLine();
            $this->warn(sprintf('DRY RUN — %d slugs would change. Nothing was written.', count($changes)));
            $this->line('Re-run with --apply once you are happy with the list above.');
            return self::SUCCESS;
        }

        DB::transaction(function () use ($changes, $table, $slugCol) {
            foreach ($changes as $c) {
                DB::table('blog_slug_redirects')->insert([
                    'locale'     => $c['locale'],
                    'old_slug'   => $c['old'],
                    'new_slug'   => $c['new'],
                    'created_at' => now(),
                    'updated_at' => now(),
                ]);

                DB::table($table)->where('id', $c['id'])->update([$slugCol => $c['new']]);
            }
        });

        $this->newLine();
        $this->info(sprintf('%d slugs updated. Old URLs now 301 to the new ones.', count($changes)));

        return self::SUCCESS;
    }

    private function slugFor(string $title): string
    {
        // Str::slug() does NOT return '' for Arabic — it transliterates, so
        // "دليل شراء العقارات" becomes "dlyl-shraaa-alaakarat", which is
        // gibberish to an Arabic reader and no better than the Latin we are
        // replacing. Decide by script, not by whether Str::slug() succeeded.
        $slug = $this->isNonLatin($title)
            ? trim(Str::lower(preg_replace('/[^\p{L}\p{N}]+/u', '-', $title)), '-')
            : Str::slug($title);

        $slug = $this->trimToWord($slug, 70);

        return $slug !== '' ? $slug : 'post-' . Str::lower(Str::random(6));
    }

    /** Has letters, but none of them Latin — Arabic, Cyrillic, CJK and so on. */
    private function isNonLatin(string $text): bool
    {
        return preg_match('/\p{L}/u', $text) === 1 && preg_match('/[A-Za-z]/', $text) !== 1;
    }

    /** Cut to a maximum length without slicing a word in half. */
    private function trimToWord(string $slug, int $max): string
    {
        if (mb_strlen($slug) <= $max) {
            return trim($slug, '-');
        }

        $cut = mb_substr($slug, 0, $max);
        $lastDash = mb_strrpos($cut, '-');

        return trim($lastDash !== false ? mb_substr($cut, 0, $lastDash) : $cut, '-');
    }

    private function makeUnique(string $table, string $slugCol, ?string $localeCol, string $locale, string $slug, $id, array $planned): string
    {
        $candidate = $slug;
        $n = 1;

        while (true) {
            if (! isset($planned["$locale|$candidate"])) {
                $query = DB::table($table)->where($slugCol, $candidate)->where('id', '!=', $id);
                if ($localeCol) {
                    $query->where($localeCol, $locale);
                }
                if (! $query->exists()) {
                    return $candidate;
                }
            }
            $candidate = $slug . '-' . (++$n);
        }
    }
}
