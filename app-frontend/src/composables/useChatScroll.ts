import { ref, nextTick, onMounted, onUnmounted } from "vue";

export function useChatScroll() {
  const scrollTop = ref(0);
  const scrollIntoViewId = ref("");
  const scrollWithAnimation = ref(false);
  const keyboardHeight = ref(0);
  type TimerHandle = ReturnType<typeof setTimeout>;
  const timers = new Set<TimerHandle>();
  let bottomTimer: TimerHandle | null = null;
  let throttleTimer: TimerHandle | null = null;
  let isUnmounted = false;

  const schedule = (callback: () => void, delay: number) => {
    const timer = setTimeout(() => {
      timers.delete(timer);
      callback();
    }, delay);
    timers.add(timer);
    return timer;
  };

  const cancelTimer = (timer: TimerHandle | null) => {
    if (timer === null) return;
    clearTimeout(timer);
    timers.delete(timer);
  };

  let isAndroid = false;
  // #ifdef APP-PLUS
  isAndroid = uni.getSystemInfoSync().platform === "android";
  // #endif

  const scrollToBottom = async () => {
    await nextTick();
    if (isUnmounted) return;
    cancelTimer(bottomTimer);
    // 合并同一渲染帧中的多次滚动请求，并通过确定性切换强制更新 scroll-top。
    bottomTimer = schedule(() => {
      bottomTimer = null;
      scrollTop.value = scrollTop.value === 999999 ? 999998 : 999999;
    }, 16);
  };

  const scrollToBottomThrottled = () => {
    if (throttleTimer !== null) return;
    throttleTimer = schedule(() => {
      throttleTimer = null;
      scrollToBottom();
    }, 64);
  };

  const triggerPhasedScroll = () => {
    scrollToBottom();
    // 覆盖键盘动画的中段与结束阶段，避免每次焦点变化创建大量定时器。
    schedule(scrollToBottom, 120);
    schedule(scrollToBottom, 260);
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
    isUnmounted = true;
    timers.forEach((timer) => clearTimeout(timer));
    timers.clear();
    bottomTimer = null;
    throttleTimer = null;
    // #ifdef APP-PLUS
    uni.offKeyboardHeightChange(onKeyboardChange);
    // #endif
  });

  // 处理分页历史记录加载后的位置维持，避免视窗乱闪
  const maintainScrollPosition = async (oldestClientId: string) => {
    scrollWithAnimation.value = false;
    await nextTick();
    if (isUnmounted) return;
    schedule(() => {
      scrollIntoViewId.value = oldestClientId;
      schedule(() => {
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
