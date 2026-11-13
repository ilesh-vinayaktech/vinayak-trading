// the browser only ever talks to this origin; /api is proxied to the backend (so the session cookie stays same-site)
const backend = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
const dev = process.env.NODE_ENV !== "production";

// Security headers for every page. The console is read-only and has no authentication of its own:
// it must run on loopback (the dev/start scripts bind 127.0.0.1) or behind an authenticating proxy.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // the screener's first run after a data change builds its table in ~30-50 s; Next's default proxy timeout is 30 s
  experimental: { proxyTimeout: 180_000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};
export default nextConfig;
