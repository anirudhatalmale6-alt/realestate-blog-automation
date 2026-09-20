<?php

namespace Tests\Feature;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

/**
 * Drop this in tests/Feature/ and run:
 *
 *     php artisan test --filter=BlogbotTest
 *
 * It exercises the import endpoint, the slug repair and the legacy redirects
 * against your real app and your real blogs table. If your column names differ
 * from config/blogbot.php, these tests are where you will find out — that is
 * the point of them.
 *
 * RefreshDatabase means this runs against your test database and never touches
 * live data. Check phpunit.xml points DB_DATABASE somewhere disposable.
 */
class BlogbotTest extends TestCase
{
    use RefreshDatabase;

    private string $token = 'test-token-for-the-suite';

    protected function setUp(): void
    {
        parent::setUp();
        config(['blogbot.token' => $this->token]);
    }

    private function model(): string
    {
        return config('blogbot.model');
    }

    private function col(string $field): ?string
    {
        return config("blogbot.columns.$field");
    }

    private function makePost(array $overrides = []): object
    {
        $c = config('blogbot.columns');

        return $this->model()::create(array_merge(config('blogbot.defaults', []), array_filter([
            $c['title']        => 'Complete Guide to Buying Property in Dubai',
            $c['slug']         => 'sapiente-quo-quod-vitae-eligendi',
            $c['body_html']    => '<p>Real body.</p>',
            $c['excerpt']      => 'Real excerpt.',
            $c['status']       => config('blogbot.status_values.published'),
            $c['locale']       => 'en',
            $c['published_at'] => now(),
        ], fn ($v, $k) => $k !== null, ARRAY_FILTER_USE_BOTH), $overrides));
    }

    private function payload(array $overrides = []): array
    {
        return array_merge([
            'title'     => 'Dubai Land Department Fees Explained',
            'slug'      => 'dubai-land-department-fees-explained',
            'excerpt'   => 'What buyers actually pay.',
            'body_html' => '<h2>The headline number</h2><p>Real content.</p>',
            'locale'    => 'en',
            'status'    => 'published',
        ], $overrides);
    }

    private function import(array $payload, ?string $token = null)
    {
        $headers = $token === null ? [] : ['Authorization' => "Bearer $token"];

        return $this->postJson('/blogbot/import', $payload, $headers);
    }

    // -- the endpoint ------------------------------------------------------

    public function test_import_rejects_a_request_with_no_token(): void
    {
        $this->import($this->payload())->assertStatus(401);
        $this->assertSame(0, $this->model()::count());
    }

    public function test_import_rejects_a_wrong_token(): void
    {
        $this->import($this->payload(), 'not-the-token')->assertStatus(401);
        $this->assertSame(0, $this->model()::count());
    }

    /**
     * A blank configured token must not mean "let everyone in". This is the
     * failure mode that turns a missing .env line into an open endpoint.
     */
    public function test_import_refuses_to_run_when_no_token_is_configured(): void
    {
        config(['blogbot.token' => null]);

        $this->import($this->payload(), 'anything')->assertStatus(503);
        $this->assertSame(0, $this->model()::count());
    }

    /**
     * The CSRF middleware has been renamed twice across Laravel versions
     * (VerifyCsrfToken -> ValidateCsrfToken -> PreventRequestForgery) and
     * withoutMiddleware() matches on the exact class string the web group
     * registered. Name the wrong one and it silently does nothing: every
     * import comes back 419 CSRF token mismatch.
     *
     * This cannot be caught by posting to the endpoint in a test — Laravel
     * disables CSRF verification in the testing environment, so the request
     * succeeds either way. (I checked: reintroducing the bug left a
     * status-201 assertion passing.) So assert on the wiring instead: whatever
     * CSRF class this Laravel version actually registers must be in the
     * route's excluded list.
     */
    public function test_the_import_route_excludes_the_csrf_class_this_version_uses(): void
    {
        $route = collect(app('router')->getRoutes()->getRoutes())
            ->first(fn ($r) => $r->uri() === 'blogbot/import');

        $this->assertNotNull($route, 'The /blogbot/import route is not registered.');

        // Reading the group off the router does not work — on Laravel 11+
        // getMiddlewareGroups() comes back empty and gatherRouteMiddleware()
        // returns the unexpanded name 'web'. So check it the other way round:
        // every CSRF class this installation ships must be excluded. That is
        // what makes the route correct regardless of which one the framework
        // actually wires up.
        $csrfClasses = array_values(array_filter([
            'Illuminate\Foundation\Http\Middleware\PreventRequestForgery',
            'Illuminate\Foundation\Http\Middleware\ValidateCsrfToken',
            'Illuminate\Foundation\Http\Middleware\VerifyCsrfToken',
        ], 'class_exists'));

        $this->assertNotEmpty($csrfClasses, 'No CSRF middleware class found to check against.');

        $excluded = $route->excludedMiddleware() ?? [];

        foreach ($csrfClasses as $class) {
            $this->assertContains(
                $class,
                $excluded,
                "The import route does not exclude $class. If that is the class your Laravel "
                . 'version wires into the web group, every live import returns 419 CSRF token mismatch.'
            );
        }
    }

    public function test_import_creates_a_post_and_returns_its_id_and_url(): void
    {
        $response = $this->import($this->payload(), $this->token)->assertStatus(201);

        $response->assertJsonStructure(['id', 'url']);
        $this->assertStringContainsString(
            '/blog/dubai-land-department-fees-explained',
            $response->json('url')
        );

        $post = $this->model()::find($response->json('id'));
        $this->assertSame('Dubai Land Department Fees Explained', $post->{$this->col('title')});
        $this->assertSame('<h2>The headline number</h2><p>Real content.</p>', $post->{$this->col('body_html')});
    }

    /**
     * A published post with a null published_at sorts and renders wrongly on
     * most blog templates.
     */
    public function test_import_always_dates_a_published_post(): void
    {
        $id = $this->import($this->payload(), $this->token)->json('id');

        $this->assertNotNull($this->model()::find($id)->{$this->col('published_at')});
    }

    public function test_import_leaves_a_draft_undated(): void
    {
        $id = $this->import($this->payload(['status' => 'draft']), $this->token)->json('id');

        $post = $this->model()::find($id);
        $this->assertSame(config('blogbot.status_values.draft'), $post->{$this->col('status')});
        $this->assertNull($post->{$this->col('published_at')});
    }

    public function test_import_never_overwrites_an_existing_slug(): void
    {
        $first  = $this->import($this->payload(), $this->token)->json('id');
        $second = $this->import($this->payload(), $this->token)->json('id');

        $this->assertNotSame($first, $second);
        $this->assertSame(
            'dubai-land-department-fees-explained-2',
            $this->model()::find($second)->{$this->col('slug')}
        );
    }

    public function test_import_validates_its_input(): void
    {
        $this->import(['title' => 'x', 'slug' => 'y'], $this->token)
            ->assertStatus(422)
            ->assertJsonValidationErrors('body_html');
    }

    // -- the slug repair ---------------------------------------------------

    public function test_dry_run_changes_nothing(): void
    {
        $post = $this->makePost();

        $this->artisan('blog:fix-slugs')->assertExitCode(0);

        $this->assertSame('sapiente-quo-quod-vitae-eligendi', $post->fresh()->{$this->col('slug')});
        $this->assertSame(0, DB::table('blog_slug_redirects')->count());
    }

    public function test_apply_rebuilds_the_slug_from_the_title(): void
    {
        $post = $this->makePost();

        $this->artisan('blog:fix-slugs --apply')->assertExitCode(0);

        $this->assertSame(
            'complete-guide-to-buying-property-in-dubai',
            $post->fresh()->{$this->col('slug')}
        );
    }

    public function test_apply_records_the_old_slug_for_redirecting(): void
    {
        $this->makePost();

        $this->artisan('blog:fix-slugs --apply');

        $this->assertDatabaseHas('blog_slug_redirects', [
            'old_slug' => 'sapiente-quo-quod-vitae-eligendi',
            'new_slug' => 'complete-guide-to-buying-property-in-dubai',
        ]);
    }

    public function test_a_slug_is_never_cut_mid_word(): void
    {
        $post = $this->makePost([
            $this->col('title') => 'Complete Guide to Buying Property in Dubai: Step-by-Step Process for International Buyers',
        ]);

        $this->artisan('blog:fix-slugs --apply');
        $slug = $post->fresh()->{$this->col('slug')};

        $this->assertLessThanOrEqual(70, strlen($slug));
        $this->assertStringEndsWith('for', $slug);   // not "for-in"
    }

    /**
     * Str::slug() does not return '' for Arabic — it transliterates, turning
     * "دليل شراء" into "dlyl-shraaa", which is no more readable than the Latin
     * placeholder being replaced.
     */
    public function test_an_arabic_title_keeps_an_arabic_slug(): void
    {
        if ($this->col('locale') === null) {
            $this->markTestSkipped('No locale column configured.');
        }

        $post = $this->makePost([
            $this->col('title')  => 'دليل شراء العقارات في دبي',
            $this->col('slug')   => 'quod-ad-provident-dolorem',
            $this->col('locale') => 'ar',
        ]);

        $this->artisan('blog:fix-slugs --apply');

        $this->assertSame('دليل-شراء-العقارات-في-دبي', $post->fresh()->{$this->col('slug')});
    }

    public function test_repair_is_idempotent(): void
    {
        $this->makePost();

        $this->artisan('blog:fix-slugs --apply');
        $this->artisan('blog:fix-slugs --apply');

        $this->assertSame(1, DB::table('blog_slug_redirects')->count());
    }

    // -- the redirects -----------------------------------------------------

    public function test_an_old_url_redirects_permanently_to_the_new_one(): void
    {
        $this->makePost();
        $this->artisan('blog:fix-slugs --apply');

        $this->get('/blog/sapiente-quo-quod-vitae-eligendi')
            ->assertStatus(301)
            ->assertRedirect('/blog/complete-guide-to-buying-property-in-dubai');
    }

    /**
     * The redirect layer is middleware rather than a route precisely so it
     * cannot shadow the blog route the site already has. If this fails, every
     * real post on the site is 404ing.
     */
    public function test_the_redirect_layer_does_not_shadow_a_working_post(): void
    {
        $this->makePost();
        $this->artisan('blog:fix-slugs --apply');

        $this->get('/blog/complete-guide-to-buying-property-in-dubai')->assertStatus(200);
    }

    public function test_an_unknown_slug_still_404s(): void
    {
        $this->makePost();
        $this->artisan('blog:fix-slugs --apply');

        $this->get('/blog/no-such-post-anywhere')->assertStatus(404);
    }

    // -- the sitemap -------------------------------------------------------

    public function test_the_sitemap_lists_published_posts(): void
    {
        $this->makePost();

        $this->get('/sitemap.xml')
            ->assertStatus(200)
            ->assertHeader('Content-Type', 'application/xml')
            ->assertSee('sapiente-quo-quod-vitae-eligendi');
    }

    public function test_the_sitemap_hides_drafts(): void
    {
        if ($this->col('status') === null) {
            $this->markTestSkipped('No status column configured.');
        }

        $this->makePost([
            $this->col('slug')   => 'a-draft-that-should-stay-hidden',
            $this->col('status') => config('blogbot.status_values.draft'),
        ]);

        $this->get('/sitemap.xml')->assertDontSee('a-draft-that-should-stay-hidden');
    }
}
