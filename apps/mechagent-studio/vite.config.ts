import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  base: "/",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765"
    }
  },
  build: {
    outDir: "../../packages/mechagent/src/mechagent/ui/static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 650,
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          markdown: ["react-markdown"]
        }
      }
    }
  }
});
