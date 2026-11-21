const dev = process.env.NODE_ENV === "development";

/** @type {import('next').NextConfig} */
const config = {
  output: dev ? undefined : "export",
  trailingSlash: true,
  images: { unoptimized: true },
  ...(dev && {
    async rewrites() {
      return [{ source: "/api/:path*", destination: "http://127.0.0.1:8765/api/:path*" }];
    },
  }),
};

export default config;
