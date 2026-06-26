import { createMDX } from "fumadocs-mdx/next";

const withMDX = createMDX();

/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  output: "export",
  reactStrictMode: true,
  trailingSlash: true,
};

export default withMDX(nextConfig);
