/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@rsmm/ui', '@rsmm/api-client', '@rsmm/schemas'],
  experimental: {
    typedRoutes: true,
  },
  async headers() {
    // AdSense needs broad allowances: its loader + ad scripts come from
    // googlesyndication / googleadservices, ad creatives render in doubleclick
    // / googlesyndication iframes, and it beacons to google.com. The Funding
    // Choices CMP (GDPR consent prompt) loads + frames from
    // fundingchoicesmessages.google.com. Keep these in sync with the loader
    // added in layout.tsx — a missing directive shows up as blank ad slots (or
    // a missing consent prompt in the EEA), not an error. See ADSENSE.md.
    const csp =
      process.env.NODE_ENV === 'production'
        ? [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://pagead2.googlesyndication.com https://*.googlesyndication.com https://partner.googleadservices.com https://tpc.googlesyndication.com https://www.googletagservices.com https://adservice.google.com https://fundingchoicesmessages.google.com",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "connect-src 'self' https://api.rsmm.me https://cdn.rsmm.me https://s3-rsmm.me https://s3-ravenswatch.ovilli.de https://pagead2.googlesyndication.com https://*.googlesyndication.com https://*.g.doubleclick.net https://www.google.com https://fundingchoicesmessages.google.com",
            "img-src 'self' data: https://api.rsmm.me https://cdn.rsmm.me https://s3-rsmm.me https://s3-ravenswatch.ovilli.de https://*.googleusercontent.com https://*.googlesyndication.com https://*.g.doubleclick.net https://www.google.com",
            "font-src 'self' https://fonts.gstatic.com",
            "frame-src 'self' https://googleads.g.doubleclick.net https://tpc.googlesyndication.com https://www.google.com https://fundingchoicesmessages.google.com",
            "object-src 'none'",
            "form-action 'none'",
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
