<script setup lang="ts">
import { onLaunch, onShow, onHide } from "@dcloudio/uni-app";
onLaunch(() => {
  console.log("App Launch");
  // #ifndef H5
  // 在 App/小程序平台，启动时立刻隐藏原生 tabBar
  // H5 平台通过 CSS uni-tabbar { display:none } 统一隐藏
  uni.hideTabBar({ animation: false });
  // #endif
});
onShow(() => {
  console.log("App Show");
});
onHide(() => {
  console.log("App Hide");
});
</script>

<style>
/* ===== 在 H5 平台中全局隐藏原生的 Uni-App TabBar 导航栏 ===== */
uni-tabbar {
  display: none !important;
}

/* ===== 全局布局约束 ===== */
html,
body,
#app {
  height: 100vh;
  margin: 0;
  padding: 0;
  overflow: hidden;
  background-color: #ffffff; /* Clean white background */
  color: #111827; /* Dark text */
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

/* ===== 移动端安全区域变量定义 ===== */
:root {
  --safe-area-top: env(safe-area-inset-top);
  --safe-area-bottom: env(safe-area-inset-bottom);
  --safe-area-left: env(safe-area-inset-left);
  --safe-area-right: env(safe-area-inset-right);
}

/* ===== 安全区域属性在页面整体的应用 ===== */
page {
  width: 100%;
  height: 100vh;
  overflow: hidden;
  box-sizing: border-box;
  background-color: #ffffff;
}

/* ===== 全局样式重置 ===== */
* {
  box-sizing: border-box;
  -webkit-tap-highlight-color: transparent;
}

/* ===== 滚动条外观样式定制 ===== */
::-webkit-scrollbar {
  width: 4px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: #d1d5db; /* Light gray thumb */
  border-radius: 2px;
}
</style>
