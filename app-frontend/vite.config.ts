import { defineConfig } from "vite";
import uni from "@dcloudio/vite-plugin-uni";
import { resolve } from "path";

export default defineConfig({
  plugins: [uni()],
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
