/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@rsmm/ui', '@rsmm/api-client', '@rsmm/schemas'],
  typedRoutes: true,
  experimental: {
    // Next preloads every route's server bundle when a server starts. On
    // Vercel a function instance often serves one or two routes before it is
    // reclaimed, so that preload was mostly wasted cold-start CPU (Fluid
    // Active CPU is dominated by cold starts here). Routes now load on first
    // use instead.
    preloadEntriesOnStart: false,
  },
  async headers() {
    // Mod pages embed YouTube / Vimeo videos (lib/video-embed.ts), so those
    // players are the only third-party frames allowed.
    const csp =
      process.env.NODE_ENV === 'production'
        ? [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline'",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "connect-src 'self' https://api.rsmm.me https://cdn.rsmm.me https://s3-rsmm.me https://s3-ravenswatch.ovilli.de",
            "img-src 'self' data: https://api.rsmm.me https://cdn.rsmm.me https://s3-rsmm.me https://s3-ravenswatch.ovilli.de https://*.googleusercontent.com",
            "font-src 'self' https://fonts.gstatic.com",
            "frame-src 'self' https://www.youtube.com https://player.vimeo.com",
            "object-src 'none'",
            "form-action 'none'",
            // Belt and braces for the markdown sanitizer: an injected <base> can't
            // repoint relative script URLs, and framing is refused in CSP too.
            "base-uri 'self'",
            "frame-ancestors 'none'",
          ].join('; ')
        : '';
    return [
      {
        source: '/(.*)',
        headers: [
          ...(csp ? [{ key: 'Content-Security-Policy', value: csp }] : []),
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
          {
            key: 'X-Frame-Options',
            value: 'DENY',
          },
          {
            key: 'Referrer-Policy',
            value: 'strict-origin-when-cross-origin',
          },
        ],
      },
    ];
  },
};

export default nextConfig;
