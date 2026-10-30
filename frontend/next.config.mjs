/**
 * Next.js configuration for the RAG-USTHB frontend.
 *
 * The browser never talks to Django on a different origin. `/api/*` is proxied
 * to the backend, which means:
 *
 *   * the Django **session** and **CSRF** cookies are first-party, so they work
 *     with `SameSite=Lax` and there is no CORS layer to configure or misconfigure;
 *   * the frontend can use relative URLs, so nothing has to be baked in at
 *     build time;
 *   * `ALLOWED_HOSTS` on the backend sees whichever Host header the proxy
 *     forwards (both are accepted in development - see backend/config/settings.py).
 *
 * The target defaults to the local Django dev server and can be overridden with
 * `NEXT_PUBLIC_API_URL`. That variable is only ever read here - it is a public
 * address, never a secret.
 */
const API_TARGET = (process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:8000').replace(/\/+$/, '')

/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    unoptimized: true,
  },
  // Let `/api/.../` reach Django unchanged.
  //
  // Next normalises a trailing slash into a 308 *before* rewrites run, while
  // Django's `APPEND_SLASH` redirects the slash-less form back to the slashed
  // one. Left alone those two rules chase each other and every API call loops
  // between 308 and 301 without ever being served. Turning the client-side
  // normalisation off hands the decision to the backend that owns the routes.
  //
  // The cost is that a request for `/chat/` is no longer redirected to `/chat`;
  // the App Router serves both, so nothing in this app depends on it.
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        // The trailing slash is pinned rather than derived from `:path*`.
        //
        // `/api/:path*` matches `/api/auth/csrf/` with `path` = `auth/csrf`,
        // so the slash is *dropped* when the destination is built. Django then
        // answers `301` (its `APPEND_SLASH` rule) back to the slashed URL, and
        // the browser returns to the same unslashed request - an endless
        // 301/308 loop that never serves a single response. Every route the
        // backend mounts is slash-terminated (Django's convention, and DRF's
        // router default), so restoring it here is exact rather than a guess.
        //
        // Pinning it also means a `301` can never turn a `POST` into a `GET`,
        // which is how this loop would otherwise corrupt a login attempt.
        destination: `${API_TARGET}/api/:path*/`,
      },
    ]
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'Strict-Transport-Security', value: 'max-age=63072000' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
        ],
      },
    ]
  },
}

export default nextConfig
