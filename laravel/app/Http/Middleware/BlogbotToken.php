<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/**
 * Guards the import endpoint. Anything without the right bearer token gets a
 * 401 and never reaches the controller.
 */
class BlogbotToken
{
    public function handle(Request $request, Closure $next): Response
    {
        $expected = config('blogbot.token');

        // A missing/blank configured token must never mean "let everyone in".
        if (! is_string($expected) || $expected === '') {
            return response()->json(['message' => 'Blogbot token is not configured.'], 503);
        }

        $sent = (string) $request->bearerToken();

        // hash_equals is constant time — a plain === leaks the token by timing.
        if ($sent === '' || ! hash_equals($expected, $sent)) {
            return response()->json(['message' => 'Unauthorized.'], 401);
        }

        return $next($request);
    }
}
