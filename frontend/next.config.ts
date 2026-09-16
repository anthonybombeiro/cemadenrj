import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Site 100% client-side (busca tudo da API do Django depois de carregar) —
  // exportar como estático evita ter que rodar um processo Node no
  // HostGator, que só suporta apps Python via Passenger.
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;
