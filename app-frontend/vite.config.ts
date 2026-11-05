import { defineConfig } from "vite";
import uni from "@dcloudio/vite-plugin-uni";
import { resolve } from "path";

export default defineConfig({
  plugins: [uni(), {
    name: "group-preview-build",
    transformIndexHtml: () => process.env.VITE_GROUP_PREVIEW === "true"
      ? [{ tag: "meta", attrs: { name: "group-chat-preview", content: "true" } }] : [],
  }],
  define: { __GROUP_PREVIEW__: JSON.stringify(process.env.VITE_GROUP_PREVIEW === "true") },
  resolve: {
    alias: {
      "@": resolve(new URL("./src", import.meta.url).pathname),
    },
  },
  esbuild: {
    drop: (process.env.NODE_ENV === "production" ? ["console", "debugger"] : []) as (
      | "console"
      | "debugger"
    )[],
  },
});
