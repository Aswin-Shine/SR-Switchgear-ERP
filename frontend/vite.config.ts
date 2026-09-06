import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Django serves the built index.html as a template out of frontend/dist, and the
// hashed assets out of /static/spa/ (WhiteNoise). Anything that changes `base`
// has to change `STATICFILES_DIRS` with it.
const DJANGO_ORIGIN = process.env.DJANGO_ORIGIN ?? "http://127.0.0.1:8000";

// Paths Django owns. In dev they are proxied so cookies stay same-origin and the
// session the SPA reads from /api/v1/me is the one /login/ set.
const DJANGO_PATHS = ["/api", "/admin", "/static", "/media", "/login", "/logout", "/password", "/print", "/healthz"];

export default defineConfig({
  base: "/static/spa/",
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    manifest: true,
    sourcemap: true,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(
      DJANGO_PATHS.map((path) => [path, { target: DJANGO_ORIGIN, changeOrigin: false }]),
    ),
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    css: false,
    include: ["src/**/*.test.{ts,tsx}", "tests/unit/**/*.test.{ts,tsx}"],
  },
});
