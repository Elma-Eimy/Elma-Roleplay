import { createSSRApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";

export function createApp() {
  const app = createSSRApp(App);

  // 安装 Pinia 全局状态管理库
  const pinia = createPinia();
  app.use(pinia);

  return {
    app,
  };
}
