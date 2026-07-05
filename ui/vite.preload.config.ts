import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";

export default defineConfig({
  build: {
    outDir: "dist-electron/electron",
    emptyOutDir: false,
    minify: false,
    lib: {
      entry: fileURLToPath(new URL("./electron/preload.ts", import.meta.url)),
      formats: ["cjs"],
      fileName: () => "preload.cjs",
    },
    rollupOptions: {
      external: ["electron"],
    },
  },
});
