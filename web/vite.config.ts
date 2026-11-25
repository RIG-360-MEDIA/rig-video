import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  // dev: the API on trijya-7 answers /api, /files and /anchor-media (RIGVIDEO_API: another instance, e.g. the :8771 test one)
  server: { port: 5180, host: "127.0.0.1", proxy: Object.fromEntries(["/api", "/files", "/anchor-media"].map((p) => [p, process.env.RIGVIDEO_API ?? "http://100.72.225.89:8770"])) },
});
