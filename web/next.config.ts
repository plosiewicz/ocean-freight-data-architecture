import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Server-only assets (sql/aql/golden) are copied into ./server-assets at
  // prebuild time and read by Node-runtime route handlers in later phases.
  // They live OUTSIDE web/public/ so they never enter the client bundle.
};

export default nextConfig;
