import type { NextConfig } from "next";

const API = process.env.CIVICSIGNAL_API ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  devIndicators: false, // keep the projector demo clean
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
