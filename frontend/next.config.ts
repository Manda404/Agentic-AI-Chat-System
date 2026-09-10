import type { NextConfig } from "next";
import { networkInterfaces } from "node:os";

const localNetworkOrigins = Object.values(networkInterfaces())
  .flatMap((interfaces) => interfaces ?? [])
  .filter((network) => network.family === "IPv4" && !network.internal)
  .map((network) => network.address);

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Detect current LAN addresses for development resource access.
  // Avoid hardcoding addresses that may change with the network or DHCP.
  allowedDevOrigins: localNetworkOrigins,
};

export default nextConfig;

