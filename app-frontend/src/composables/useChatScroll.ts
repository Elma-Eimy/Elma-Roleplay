import { ref, nextTick, onMounted, onUnmounted } from "vue";
import { isNearBottom, type ScrollMetrics } from "@/utils/chatDisplay";

export function useChatScroll() {
  const scrollTop = ref(0);
  const scrollIntoViewId = ref("");
  const scrollWithAnimation = ref(false);
  const keyboardHeight = ref(0);
  // 用户停留在底部时自动跟随新内容；上翻阅读时只提示，不强制拉回。
  const isPinnedToBottom = ref(true);
  const hasUnreadBelow = ref(false);
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

  /** 用户主动行为（发送、点击浮标）：恢复跟随并置底。 */
  const pinToBottom = () => {
    isPinnedToBottom.value = true;
    hasUnreadBelow.value = false;
    scrollToBottom();
  };

  /** 新内容到达：停留在底部时跟随，否则只标记有未读。 */
  const followNewContent = (throttled = false) => {
    if (!isPinnedToBottom.value) {
      hasUnreadBelow.value = true;
      return;
    }
    if (throttled) scrollToBottomThrottled();
    else scrollToBottom();
  };

  const updateScrollMetrics = (metrics: ScrollMetrics) => {
    const pinned = isNearBottom(metrics);
    isPinnedToBottom.value = pinned;
    if (pinned) hasUnreadBelow.value = false;
  };

  /** 切换故事或重新进入时重置跟随状态。 */
  const resetPinState = () => {
    isPinnedToBottom.value = true;
    hasUnreadBelow.value = false;
  };

  const scrollToBottomThrottled = () => {
    if (throttleTimer !== null) return;
    throttleTimer = schedule(() => {
      throttleTimer = null;
      scrollToBottom();
    }, 64);
  };

  const triggerPhasedScroll = () => {
    resetPinState();
    scrollToBottom();
    // 覆盖键盘动画的中段与结束阶段，避免每次焦点变化创建大量定时器。
    schedule(scrollToBottom, 120);
    schedule(scrollToBottom, 260);
  };

  // #ifdef APP-PLUS || MP-WEIXIN
  const onKeyboardChange = (res: { height: number }) => {
    // Android 配置 adjustResize，WebView 会自动调整大小，无需占位
    // iOS WebView 高度固定，必须通过占位来推起输入区
    const height = Math.max(0, Number(res.height) || 0);
    keyboardHeight.value = isAndroid ? 0 : height;
    if (height > 0) {
      triggerPhasedScroll();
    }
  };
  // #endif

  // #ifdef H5
  let visualViewport: VisualViewport | null = null;
  const onVisualViewportChange = () => {
    const tag = document.activeElement?.tagName;
    const focused = tag === 'TEXTAREA' || tag === 'INPUT';
    const height = focused && visualViewport && visualViewport.scale === 1
      ? Math.max(0, document.documentElement.clientHeight - visualViewport.height - visualViewport.offsetTop) : 0;
    if (keyboardHeight.value === height) return;
    keyboardHeight.value = height;
    if (height > 0) triggerPhasedScroll();
  };
  // #endif

  onMounted(() => {
    // #ifdef APP-PLUS || MP-WEIXIN
    uni.onKeyboardHeightChange(onKeyboardChange);
    // #endif
    // #ifdef H5
    visualViewport = window.visualViewport;
    visualViewport?.addEventListener('resize', onVisualViewportChange);
    visualViewport?.addEventListener('scroll', onVisualViewportChange);
    document.addEventListener('focusin', onVisualViewportChange);
    document.addEventListener('focusout', onVisualViewportChange);
    // #endif
  });

  onUnmounted(() => {
    isUnmounted = true;
    timers.forEach((timer) => clearTimeout(timer));
    timers.clear();
    bottomTimer = null;
    throttleTimer = null;
    // #ifdef APP-PLUS || MP-WEIXIN
    uni.offKeyboardHeightChange(onKeyboardChange);
    // #endif
    // #ifdef H5
    visualViewport?.removeEventListener('resize', onVisualViewportChange);
    visualViewport?.removeEventListener('scroll', onVisualViewportChange);
    document.removeEventListener('focusin', onVisualViewportChange);
    document.removeEventListener('focusout', onVisualViewportChange);
    visualViewport = null;
    // #endif
  });

  // 处理分页历史记录加载后的位置维持，避免视窗乱闪
  const maintainScrollPosition = async (oldestClientId: string, isCurrent = () => true) => {
    if (!isCurrent()) return;
    scrollWithAnimation.value = false;
    await nextTick();
    if (isUnmounted || !isCurrent()) return;
    schedule(() => {
      if (!isCurrent()) return;
      scrollIntoViewId.value = oldestClientId;
      schedule(() => {
        if (isCurrent() && scrollIntoViewId.value === oldestClientId) scrollIntoViewId.value = "";
      }, 100);
    }, 50);
  };

  return {
    scrollTop,
    scrollIntoViewId,
    scrollWithAnimation,
    keyboardHeight,
    isAndroid,
    isPinnedToBottom,
    hasUnreadBelow,
    scrollToBottom,
    scrollToBottomThrottled,
    pinToBottom,
    followNewContent,
    updateScrollMetrics,
    resetPinState,
    triggerPhasedScroll,
    maintainScrollPosition,
  };
}
