/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@rsmm/ui', '@rsmm/api-client', '@rsmm/schemas'],
  experimental: {
    typedRoutes: true,
  },
  async headers() {
    const csp = process.env.NODE_ENV === 'production'
      ? "default-src 'self'; script-src 'self' 'unsafe-inline' https://pagead2.googlesyndication.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; connect-src 'self' https://api.ravenswatch.ovilli.de; img-src 'self' data: https://api.ravenswatch.ovilli.de https://cdn.rsmm.dev https://s3-ravenswatch.ovilli.de https://*.googleusercontent.com; font-src 'self' https://fonts.gstatic.com; frame-src 'none'; object-src 'none'; form-action 'none'"
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
