import type { NextConfig } from "next";

// FastAPI engine base URL. Server-side only (never NEXT_PUBLIC_). Read at build time for the
// rewrites, so changing it on Vercel needs a redeploy. CIVICSIGNAL_API kept as a legacy alias.
const API = process.env.SNOWTECH_API_URL || process.env.CIVICSIGNAL_API || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  devIndicators: false, // keep the projector demo clean
  // Ship the prebuild copy of the replay data with every server function (lib/server.ts reads it
  // at request time via fs, which the tracer cannot see).
  outputFileTracingIncludes: {
    "/*": ["./data/results.json"],
  },
  async rewrites() {
    return [
      // Read-only proxy to the FastAPI engine (no CORS changes needed).
      // POST /tickets and /disruption are deliberately NOT proxied: tickets come only from the
      // ElevenLabs webhook, and disruptions go through /api-internal/disruption, which adds the
      // shared-secret header server-side.
      { source: "/api/:path((?!tickets|disruption).*)", destination: `${API}/:path` },
    ];
  },
};

export default nextConfig;
