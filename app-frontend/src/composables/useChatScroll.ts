import { ref, nextTick, onMounted, onUnmounted } from "vue";

export function useChatScroll() {
  const scrollTop = ref(0);
  const scrollIntoViewId = ref("");
  const scrollWithAnimation = ref(false);
  const keyboardHeight = ref(0);

  let isAndroid = false;
  // #ifdef APP-PLUS
  isAndroid = uni.getSystemInfoSync().platform === "android";
  // #endif

  const scrollToBottom = async () => {
    await nextTick();
    // 延迟 80ms 确保 DOM 挂载和渲染高度更新后再滚动置底
    setTimeout(() => {
      // 强行用随机微调值唤醒 Vue 属性更新，防止计算滞后导致无法置底
      scrollTop.value = 999999 - Math.random();
    }, 80);
  };

  let isScrollThrottled = false;
  const scrollToBottomThrottled = () => {
    if (isScrollThrottled) return;
    isScrollThrottled = true;
    setTimeout(() => {
      scrollToBottom();
      isScrollThrottled = false;
    }, 120);
  };

  const triggerPhasedScroll = () => {
    scrollToBottom();
    // 阶段式定时置底，在键盘弹动中平滑触底
    setTimeout(scrollToBottom, 60);
    setTimeout(scrollToBottom, 120);
    setTimeout(scrollToBottom, 200);
    setTimeout(scrollToBottom, 300);
    setTimeout(scrollToBottom, 400);
  };

  // #ifdef APP-PLUS
  const onKeyboardChange = (res: any) => {
    // Android 配置 adjustResize，WebView 会自动调整大小，无需占位
    // iOS WebView 高度固定，必须通过占位来推起输入区
    keyboardHeight.value = isAndroid ? 0 : res.keyboardHeight;
    if (res.keyboardHeight > 0) {
      triggerPhasedScroll();
    }
  };
  // #endif

  onMounted(() => {
    // #ifdef APP-PLUS
    uni.onKeyboardHeightChange(onKeyboardChange);
    // #endif
  });

  onUnmounted(() => {
    // #ifdef APP-PLUS
    uni.offKeyboardHeightChange(onKeyboardChange);
    // #endif
  });

  // 处理分页历史记录加载后的位置维持，避免视窗乱闪
  const maintainScrollPosition = async (oldestClientId: string) => {
    scrollWithAnimation.value = false;
    await nextTick();
    setTimeout(() => {
      scrollIntoViewId.value = oldestClientId;
      setTimeout(() => {
        scrollIntoViewId.value = "";
      }, 100);
    }, 50);
  };

  return {
    scrollTop,
    scrollIntoViewId,
    scrollWithAnimation,
    keyboardHeight,
    isAndroid,
    scrollToBottom,
    scrollToBottomThrottled,
    triggerPhasedScroll,
    maintainScrollPosition,
  };
}
