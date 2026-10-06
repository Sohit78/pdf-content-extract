import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Pin the workspace root: a stray package-lock.json in the home directory
  // otherwise wins the root inference and Turbopack warns on every build.
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
