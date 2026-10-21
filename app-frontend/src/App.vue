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
  height: 100dvh;
  margin: 0;
  padding: 0;
  overflow: hidden;
  background-color: #f7f9f7;
  color: #26332e;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

/* ===== 移动端安全区域变量定义 ===== */
:root,
page {
  --safe-area-top: env(safe-area-inset-top);
  --safe-area-bottom: env(safe-area-inset-bottom);
  --safe-area-left: env(safe-area-inset-left);
  --safe-area-right: env(safe-area-inset-right);

  --app-color-background: #f7f9f7;
  --app-color-surface: #ffffff;
  --app-color-surface-soft: rgba(255, 255, 255, 0.78);
  --app-color-surface-translucent: rgba(255, 255, 255, 0.88);
  --app-color-text-primary: #26332e;
  --app-color-text-secondary: #64716b;
  --app-color-text-muted: #89958f;
  --app-color-primary: #70ae9b;
  --app-color-primary-strong: #4f8e7c;
  --app-color-primary-soft: rgba(112, 174, 155, 0.14);
  --app-color-secondary: #8bb8dc;
  --app-color-warm: #f1c98d;
  --app-color-border: rgba(38, 51, 46, 0.08);
  --app-color-border-strong: rgba(38, 51, 46, 0.14);
  --app-color-success: #5e9f76;
  --app-color-warning: #d69c4a;
  --app-color-danger: #d9655d;
  --app-color-mask: rgba(25, 37, 32, 0.42);

  --app-font-size-caption: 22rpx;
  --app-font-size-body-sm: 24rpx;
  --app-font-size-body: 28rpx;
  --app-font-size-title-sm: 32rpx;
  --app-font-size-title: 40rpx;
  --app-font-size-display: 52rpx;

  --app-radius-xs: 10rpx;
  --app-radius-sm: 16rpx;
  --app-radius-md: 24rpx;
  --app-radius-lg: 36rpx;
  --app-radius-pill: 999rpx;

  --app-space-xs: 8rpx;
  --app-space-sm: 12rpx;
  --app-space-md: 20rpx;
  --app-space-lg: 28rpx;
  --app-space-xl: 36rpx;
  --app-space-2xl: 48rpx;

  --app-page-gutter: 36rpx;
  --app-control-height: 88rpx;
  --app-touch-target: 88rpx;
  --app-header-height: 112rpx;

  --app-shadow-soft: 0 12rpx 36rpx rgba(45, 72, 62, 0.08);
  --app-shadow-raised: 0 20rpx 52rpx rgba(45, 72, 62, 0.12);

  --app-motion-fast: 160ms;
  --app-motion-normal: 240ms;
  --app-motion-slow: 360ms;
}

/* ===== 安全区域属性在页面整体的应用 ===== */
page {
  width: 100%;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  box-sizing: border-box;
  background-color: var(--app-color-background);
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
  background: rgba(124, 137, 131, 0.36);
  border-radius: 2px;
}

/* ===== 跨页面基础样式 ===== */
.app-page {
  position: relative;
  width: 100%;
  min-height: 100%;
  background-color: var(--app-color-background);
  color: var(--app-color-text-primary);
}

.app-card {
  background-color: var(--app-color-surface);
  border: 1px solid var(--app-color-border);
  border-radius: var(--app-radius-md);
  box-shadow: var(--app-shadow-soft);
}

.app-label {
  display: inline-flex;
  align-items: center;
  min-height: 44rpx;
  padding: 0 16rpx;
  border-radius: var(--app-radius-pill);
  background-color: var(--app-color-primary-soft);
  color: var(--app-color-primary-strong);
  font-size: var(--app-font-size-caption);
  font-weight: 600;
}

.app-icon-button {
  display: flex;
  width: var(--app-touch-target);
  height: var(--app-touch-target);
  align-items: center;
  justify-content: center;
  border-radius: var(--app-radius-pill);
  transition:
    transform var(--app-motion-fast) ease,
    background-color var(--app-motion-fast) ease;
}

.app-icon-button:active {
  background-color: var(--app-color-primary-soft);
  transform: scale(0.94);
}

/* ===== 页面进入与状态切换 ===== */
.app-motion-enter {
  animation: app-page-enter var(--app-motion-slow) cubic-bezier(0.16, 1, 0.3, 1) both;
}

@keyframes app-page-enter {
  from {
    opacity: 0;
    transform: translateY(10rpx);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 遵循系统的“减少动态效果”偏好，并避免流式输出时产生额外跳动。 */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    scroll-behavior: auto !important;
    animation-duration: 1ms !important;
    animation-delay: 0ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 1ms !important;
  }
}
</style>
