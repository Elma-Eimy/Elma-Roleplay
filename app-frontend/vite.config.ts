import { defineConfig } from "vite";
import uni from "@dcloudio/vite-plugin-uni";
import { resolve } from "path";

// 动态导入 UnoCSS 以规避与 uni-app vite 配置加载器的 ESM/CJS 模块冲突问题
export default defineConfig(async () => {
  const UnoCSS = (await import("unocss/vite")).default;
  return {
    plugins: [
      // UnoCSS 插件必须注册在 uni() 插件之前
      UnoCSS(),
      uni(),
    ],
    resolve: {
      alias: {
        "@": resolve(new URL("./src", import.meta.url).pathname),
      },
    },
    // 生产环境打包时自动剔除 console.log 和 debugger 以优化运行性能
    esbuild: {
      drop: (process.env.NODE_ENV === 'production' ? ['console', 'debugger'] : []) as ('console' | 'debugger')[],
    },
  };
});
