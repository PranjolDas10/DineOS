import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone", // small Docker image: server.js plus only the files it needs
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
