import type { NextConfig } from "next";
import { networkInterfaces } from "node:os";

const localNetworkOrigins = Object.values(networkInterfaces())
  .flatMap((interfaces) => interfaces ?? [])
  .filter((network) => network.family === "IPv4" && !network.internal)
  .map((network) => network.address);

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Next protège progressivement ses ressources de développement contre les
  // requêtes cross-origin. Les adresses LAN courantes sont détectées plutôt
  // que codées en dur, car elles peuvent changer avec le réseau/DHCP.
  allowedDevOrigins: localNetworkOrigins,
};

export default nextConfig;

