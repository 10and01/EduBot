/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ["react-markdown", "remark-gfm", "remark-parse", "unified", "vfile", "vfile-message"],
};

export default nextConfig;
