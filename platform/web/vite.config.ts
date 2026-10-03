import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** Matches a module under node_modules belonging to any of the given packages (scoped names allowed). */
function packages(...names: string[]): RegExp {
  const escaped = names.map(name => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace("/", "[\\\\/]"));
  return new RegExp(`node_modules[\\\\/](?:${escaped.join("|")})[\\\\/]`);
}

export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      output: {
        // entriesAware subgroups are named after every entry that shares them; keep only the group name.
        chunkFileNames: chunk =>
          chunk.name.startsWith("vendor-") ? `assets/${chunk.name.split("~")[0]}-[hash].js` : "assets/[name]-[hash].js",
        // Long-lived vendor chunks keep every chunk under the 500 kB warning and cache across app releases.
        // entriesAware keeps vendor code that only lazy pages use out of the initial download.
        // Markdown rendering is left to the lazy Help page chunk.
        codeSplitting: {
          groups: [
            {
              name: "vendor-react",
              test: packages("react", "react-dom", "scheduler", "react-router", "react-router-dom", "cookie"),
              priority: 40,
              entriesAware: true,
              entriesAwareMergeThreshold: 20_000,
            },
            {
              name: "vendor-mui-icons",
              test: packages("@mui/icons-material"),
              priority: 35,
              entriesAware: true,
              entriesAwareMergeThreshold: 20_000,
            },
            {
              name: "vendor-mui",
              test: /node_modules[\\/](?:@mui|@emotion|@popperjs|react-transition-group|react-is|clsx|stylis|hoist-non-react-statics|@babel[\\/]runtime)[\\/]/,
              priority: 30,
              entriesAware: true,
              entriesAwareMergeThreshold: 20_000,
            },
            {
              name: "vendor-react-admin",
              test: /node_modules[\\/](?:react-admin|ra-[^\\/]+|@tanstack|react-hook-form|lodash|inflection|query-string|node-polyglot|eventemitter3|jsonexport|react-dropzone|react-error-boundary|papaparse|date-fns|dompurify|clsx)[\\/]/,
              priority: 20,
              entriesAware: true,
              entriesAwareMergeThreshold: 20_000,
            },
          ],
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
});
