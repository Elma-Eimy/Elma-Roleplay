import {
  defineConfig,
  presetUno,
  presetAttributify,
  transformerDirectives,
  transformerVariantGroup,
} from "unocss";

export default defineConfig({
  presets: [
    presetUno({
      dark: "class",
    }),
    presetAttributify(),
  ],
  transformers: [
    transformerDirectives(),
    transformerVariantGroup(),
  ],
  shortcuts: {
    // Flex 布局快捷组合样式
    "flex-center": "flex items-center justify-center",
    "flex-col-center": "flex flex-col items-center justify-center",
    // 占满全屏的便捷样式
    "full-screen": "w-full h-screen",
    // 极简扁平化卡片样式
    "minimal-card": "bg-white border border-gray-200 rounded-xl shadow-sm",
  },
  theme: {
    colors: {
      // 极简黑白主题调色盘
      primary: {
        DEFAULT: "#000000",
        light: "#333333",
      },
      surface: {
        DEFAULT: "#FFFFFF",
        card: "#F9FAFB",
        elevated: "#F3F4F6",
      },
      text: {
        main: "#111827",
        muted: "#6B7280",
        inverse: "#FFFFFF",
      },
      border: {
        light: "#E5E7EB",
        DEFAULT: "#D1D5DB",
      }
    },
    breakpoints: {
      sm: "375px",
      md: "768px",
      lg: "1024px",
    },
  },
  rules: [
    [/^rpx-(.+)$/, ([, d]) => ({ "font-size": `${d}rpx` })],
  ],
});
