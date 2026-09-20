<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

/**
 * One new table. Nothing existing is altered.
 *
 * Holds the old placeholder slug -> new slug map so every URL Google has
 * already indexed keeps resolving after the slug repair runs.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('blog_slug_redirects', function (Blueprint $table) {
            $table->id();
            $table->string('locale', 5)->nullable();
            $table->string('old_slug');
            $table->string('new_slug');
            $table->timestamps();

            $table->index(['locale', 'old_slug']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('blog_slug_redirects');
    }
};
