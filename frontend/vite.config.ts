import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    css: false,
    clearMocks: true,
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
