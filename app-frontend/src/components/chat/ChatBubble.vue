<template>
  <view 
    v-if="message"
    class="chat-bubble-wrapper" 
    :class="{
      'is-user': isUser,
      'is-ai-continuation': !isUser && !showAvatar,
    }"
  >
    <AvatarImage
      v-if="!isUser && showAvatar"
      class="avatar" 
      :src="avatarUrl"
    />
    <view v-else-if="!isUser" class="avatar-spacer"></view>

    <view class="bubble-content-area">
      <!-- AI 姓名标签 -->
      <text v-if="!isUser && showName" class="name-tag">{{ characterName }}</text>

      <!-- 消息气泡 -->
      <view 
        class="bubble" 
        :class="[isUser ? 'user-bubble' : 'ai-bubble']"
        @touchstart="handleTouchStart"
        @touchend="handleTouchEnd"
        @longpress.stop="handleLongPress"
        @contextmenu.prevent.stop="handleLongPress"
      >
        
        <!-- AI 的深度思考过程容器 -->
        <view v-if="!isUser && hasThought" class="thought-container" :class="{ 'is-expanded': isThoughtExpanded }">
          <view class="thought-header" @tap="isThoughtExpanded = !isThoughtExpanded">
            <view class="thought-header-left">
              <view class="brain-spark"></view>
              <text class="thought-title">{{ thoughtTitle }}</text>
            </view>
            <view class="thought-arrow" :class="{ 'is-up': isThoughtExpanded }">▾</view>
          </view>
          <view v-if="isThoughtExpanded" class="thought-body">
            <rich-text class="thought-markdown-content" :nodes="renderedThought" />
          </view>
        </view>

        <!-- 渲染为 Markdown 的 AI 回复内容 -->
        <rich-text 
          v-if="!isUser" 
          class="markdown-content" 
          :nodes="renderedMarkdown"
        />

        <!-- 用户的纯文本内容 -->
        <text v-else class="plain-text">{{ message.content }}</text>

        <!-- 状态指示器（发送中、流式输出中） -->
        <view v-if="message.status === 'sending'" class="status-indicator">
          <view class="dot-typing"></view>
        </view>
        <!-- 流式传输指示器：内容为空时显示思考动画（AI 正在思考），正在生成时显示闪烁光标 -->
        <view v-if="message.status === 'streaming'" class="streaming-indicator">
          <view v-if="!message.content" class="ai-thinking">
            <view class="ai-dot"></view>
            <view class="ai-dot delay-1"></view>
            <view class="ai-dot delay-2"></view>
          </view>
          <view v-else class="cursor-blink"></view>
        </view>
        <view v-if="message.status === 'error'" class="error-text">
          发送失败
        </view>

      </view>

      <!-- AI 候选版本切换器 (Swipe Multi-Replies) -->
      <view 
        v-if="!isUser && message.candidates && message.candidates.length > 1" 
        class="candidate-pager"
        @longpress.stop=""
        @contextmenu.prevent.stop=""
      >
        <view class="pager-btn prev" @tap.stop="switchCandidateVersion(-1)">
          <text class="pager-arrow">‹</text>
        </view>
        <view class="pager-dots">
          <view
            v-for="(_, index) in message.candidates"
            :key="index"
            class="pager-dot"
            :class="{ 'is-active': index === (message.active_index ?? 0) }"
          ></view>
        </view>
        <text class="pager-text">{{ (message.active_index ?? 0) + 1 }}/{{ message.candidates.length }}</text>
        <view class="pager-btn next" @tap.stop="switchCandidateVersion(1)">
          <text class="pager-arrow">›</text>
        </view>
      </view>

      <!-- 元数据信息（情绪标签、好感度变动与所使用的模型、语音播报） -->
      <view v-if="!isUser" class="meta-area">
        <!-- 语音播报按钮 -->
        <view 
          v-if="message.status === 'done'"
          class="meta-tag tts-btn" 
          :class="{ 'is-playing': activeAudioMessageId === message.id }"
          @tap="playTTS"
        >
          <view v-if="activeAudioMessageId === message.id" class="waveform">
            <view class="wave-bar bar-1"></view>
            <view class="wave-bar bar-2"></view>
            <view class="wave-bar bar-3"></view>
          </view>
          <image v-else class="tts-icon" src="/static/icons/tts_play.svg" mode="aspectFit" />
          <text class="tts-text">{{ activeAudioMessageId === message.id ? '播放中' : '朗读' }}</text>
        </view>
        <view v-if="message.emotion_tag" class="meta-tag emotion">
          {{ message.emotion_tag }}
        </view>
        <view v-if="message.affection_change" class="meta-tag affection" :class="{ positive: message.affection_change > 0, negative: message.affection_change < 0 }">
          <text>{{ message.affection_change > 0 ? '+' : '' }}{{ message.affection_change }}</text>
          <image class="affection-heart-icon-bubble" :src="message.affection_change >= 0 ? '/static/icons/meta_heart.svg' : '/static/icons/meta_heart_broken.svg'" mode="aspectFit" />
        </view>
        <view v-if="message.model_used" class="meta-tag model-used">
          {{ message.model_used }}
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from "vue";
import type { ChatMessage } from "@/store/chatStore";
import { useChatStore } from "@/store/chatStore";
import { usePersonaStore } from "@/store/personaStore";
import { useAudioPlayer } from "@/composables/useAudioPlayer";
import MarkdownIt from "markdown-it";
import AvatarImage from "@/components/common/AvatarImage.vue";

// 所有消息共享一个解析器。关闭原始 HTML，模型输出只按 Markdown 文本解析。
const md = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
});

const STREAM_MARKDOWN_RENDER_DELAY = 48;

const chatStore = useChatStore();
const personaStore = usePersonaStore();
const { activeAudioMessageId, playMessageTTS } = useAudioPlayer();

const props = withDefaults(
  defineProps<{
    message: ChatMessage;
    avatarUrl?: string;
    characterName?: string;
    showName?: boolean;
    showAvatar?: boolean;
  }>(),
  {
    avatarUrl: "",
    characterName: "",
    showName: false,
    showAvatar: true,
  }
);

const emit = defineEmits<{
  (e: "longpress-message", message: ChatMessage): void;
}>();

const handleLongPress = (e?: Event) => {
  // 阻止 H5 平台上浏览器原生的右键菜单
  if (e) e.preventDefault?.();
  // 仅允许在发送完成或发送失败的消息上执行操作
  if (props.message?.status !== 'sending' && props.message?.status !== 'streaming') {
    // vibrateShort（短震动）仅在原生 App 平台可用，H5 平台下直接忽略该调用
    try {
      uni.vibrateShort({
        success: function () {
            console.log('vibrate short success');
        }
      });
    } catch (_) {}
    emit("longpress-message", props.message);
  }
};

// ── Swipe Multi-Replies 逻辑 ──
const touchStartX = ref(0);
const touchStartY = ref(0);

const handleTouchStart = (e: TouchEvent) => {
  if (isUser.value || !props.message?.candidates || props.message.candidates.length <= 1) return;
  touchStartX.value = e.touches[0].clientX;
  touchStartY.value = e.touches[0].clientY;
};

const handleTouchEnd = (e: TouchEvent) => {
  if (isUser.value || !props.message?.candidates || props.message.candidates.length <= 1) return;
  const deltaX = e.changedTouches[0].clientX - touchStartX.value;
  const deltaY = e.changedTouches[0].clientY - touchStartY.value;
  
  if (Math.abs(deltaX) > 60 && Math.abs(deltaY) < 40) {
    if (deltaX > 0) {
      switchCandidateVersion(-1);
    } else {
      switchCandidateVersion(1);
    }
  }
};

const switchCandidateVersion = async (direction: number) => {
  if (chatStore.isLoading || !props.message?.candidates || props.message.status === 'streaming') return;
  const len = props.message.candidates.length;
  const currentIdx = props.message.active_index ?? 0;
  let targetIdx = currentIdx + direction;
  
  if (targetIdx < 0) {
    targetIdx = len - 1;
  } else if (targetIdx >= len) {
    targetIdx = 0;
  }
  
  const targetCandidate = props.message.candidates[targetIdx];
  if (targetCandidate) {
    try {
      uni.vibrateShort({ success: () => {} });
    } catch (_) {}
    await chatStore.switchActiveCandidate(props.message.id, targetCandidate.id);
  }
};

const playTTS = () => {
  if (props.message?.id) {
    playMessageTTS(props.message);
  }
};

const isUser = computed(() => {
  try {
    return props.message?.role === "user";
  } catch (err) {
    console.error("[ChatBubble] isUser error:", err);
    return false;
  }
});


const hasMeta = computed(() => {
  try {
    return !!(props.message?.emotion_tag || props.message?.affection_change || props.message?.model_used);
  } catch (err) {
    console.error("[ChatBubble] hasMeta error:", err);
    return false;
  }
});

// 推理思维链内容解析
const isThoughtExpanded = ref(false);

// 替换 {{char}} / {{user}} 占位符
const replacePlaceholders = (text: string) => {
  try {
    if (!text) return "";
    const str = String(text);
    const charName = props.characterName || "角色";
    const userName = personaStore.userNickname || "用户";
    return str
      .replace(/\{\{char\}\}/gi, charName)
      .replace(/\{\{user\}\}/gi, userName);
  } catch (err) {
    console.error("[ChatBubble] replacePlaceholders error:", err, "text:", text);
    return String(text || "");
  }
};

const parsedContent = computed(() => {
  try {
    let content = props.message?.content;
    if (content === null || content === undefined) {
      content = "";
    } else {
      content = String(content);
    }
    
    // 1. 过滤掉 <status ...> 自定义标签，防止 rich-text 渲染自定义 XML 标签导致原生端崩溃
    content = content.replace(/<status[^>]*\/?>/gi, "");
    
    content = replacePlaceholders(content);
    
    if (isUser.value) {
      return { thought: "", reply: content };
    }
    
    // 优先采用独立的 reasoning_content 字段（API 标准格式）
    let thought = props.message?.reasoning_content ? String(props.message.reasoning_content) : "";
    let reply = content;
    
    // 如果独立的 reasoning_content 为空，再尝试 fallback 从 content 中解析 <thought> 标签
    if (!thought) {
      const thoughtRegex = /<thought>([\s\S]*?)<\/thought>/i;
      const match = content.match(thoughtRegex);
      if (match) {
        thought = match[1].trim();
        reply = content.replace(thoughtRegex, "").trim();
      }
    } else {
      // 如果是用独立的 reasoning_content，仍要清理 content 中残留的 <thought> 标签
      reply = reply.replace(/<\/?thought[^>]*>/gi, "");
    }
    
    thought = replacePlaceholders(thought);
    
    // 3. 额外清理并移除任何残留或未闭合的 <thought> / </thought> 标签，防止 rich-text 解析时崩溃
    thought = thought.replace(/<\/?thought[^>]*>/gi, "");
    reply = reply.replace(/<\/?thought[^>]*>/gi, "");
    
    return { thought, reply };
  } catch (err) {
    console.error("[ChatBubble] parsedContent error:", err, "message:", props.message);
    const fallback = String(props.message?.content || "")
      .replace(/<status[^>]*\/?>/gi, "")
      .replace(/<\/?thought[^>]*>/gi, "");
    return { thought: "", reply: fallback };
  }
});

const hasThought = computed(() => {
  try {
    return !!parsedContent.value.thought;
  } catch (err) {
    console.error("[ChatBubble] hasThought error:", err);
    return false;
  }
});

const renderMarkdown = (content: string) => {
  let html = md.render(content);
  html = html.replace(/<p>/g, '<p class="md-p">');
  html = html.replace(/<em>/g, '<em class="md-em">');
  html = html.replace(/<strong>/g, '<strong class="md-strong">');
  // 识别中文引号和直角引号并包裹，用于做对话单独排版渲染
  html = html.replace(/“([^”]+)”/g, '<span class="md-dialogue">“$1”</span>');
  html = html.replace(/「([^」]+)」/g, '<span class="md-dialogue">「$1」</span>');
  return html;
};

const renderedMarkdown = ref("");
const renderedThought = ref("");
let markdownRenderTimer: ReturnType<typeof setTimeout> | null = null;

const updateRenderedMarkdown = () => {
  if (markdownRenderTimer !== null) {
    clearTimeout(markdownRenderTimer);
    markdownRenderTimer = null;
  }

  try {
    const replyContent = parsedContent.value.reply;
    renderedMarkdown.value =
      !isUser.value && replyContent ? renderMarkdown(String(replyContent)) : "";

    const thoughtContent = parsedContent.value.thought;
    renderedThought.value = thoughtContent
      ? renderMarkdown(String(thoughtContent))
      : "";
  } catch (err) {
    console.error("[ChatBubble] renderedMarkdown error:", err, "message:", props.message);
    renderedMarkdown.value = "";
    renderedThought.value = "";
  }
};

watch(
  [
    () => parsedContent.value.reply,
    () => parsedContent.value.thought,
    () => props.message?.status,
  ],
  () => {
    if (props.message?.status === "streaming") {
      if (markdownRenderTimer === null) {
        markdownRenderTimer = setTimeout(
          updateRenderedMarkdown,
          STREAM_MARKDOWN_RENDER_DELAY
        );
      }
      return;
    }
    updateRenderedMarkdown();
  },
  { immediate: true }
);

onUnmounted(() => {
  if (markdownRenderTimer !== null) {
    clearTimeout(markdownRenderTimer);
    markdownRenderTimer = null;
  }
});

const thoughtTitle = computed(() => {
  if (props.message?.status === "streaming") {
    if (!props.message.content) {
      return "AI 正在思考中...";
    }
  }
  return isThoughtExpanded.value ? "深度思考过程" : "AI 已完成思考 (点击展开)";
});

// 监听流式思考过程流入，在流式输出思考期间自动展开思考区
watch(() => props.message?.reasoning_content, (newVal) => {
  if (props.message?.status === "streaming" && newVal) {
    isThoughtExpanded.value = true;
  }
}, { immediate: true });
</script>

<style scoped>
.chat-bubble-wrapper {
  display: flex;
  width: 100%;
  padding: 14rpx 32rpx;
  margin-bottom: 2rpx;
  gap: 18rpx;
  align-items: flex-start;
  animation: bubble-fade-in var(--app-motion-slow, 360ms) cubic-bezier(0.16, 1, 0.3, 1) both;
}

.chat-bubble-wrapper.is-ai-continuation {
  padding-top: 4rpx;
}

@keyframes bubble-fade-in {
  from {
    opacity: 0;
    transform: translateY(20rpx);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.chat-bubble-wrapper.is-user {
  flex-direction: row-reverse;
}

/* ===== 头像样式 ===== */
.avatar {
  width: 72rpx;
  height: 72rpx;
  border-radius: 28rpx;
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  border: 1px solid rgba(255, 255, 255, 0.72);
  box-shadow: 0 8rpx 22rpx rgba(45, 72, 62, 0.1);
  flex-shrink: 0;
}

.avatar-spacer {
  width: 72rpx;
  height: 1px;
  flex-shrink: 0;
}

/* ===== 内容区域 ===== */
.bubble-content-area {
  display: flex;
  flex-direction: column;
  max-width: calc(100% - 90rpx);
  min-width: 0;
}

.is-user .bubble-content-area {
  max-width: 78%;
  align-items: flex-end;
}

/* ===== 名字标签 ===== */
.name-tag {
  margin-bottom: 8rpx;
  margin-left: 10rpx;
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: var(--app-font-size-caption, 22rpx);
  font-weight: 650;
}

/* ===== 气泡基础样式 ===== */
.bubble {
  padding: 20rpx 26rpx;
  border-radius: 26rpx;
  position: relative;
  word-break: break-word;
  touch-action: pan-y; /* 限制垂直滚动，防止与手机端侧滑手势或返回冲突 */
}

/* ===== AI 轻纸片 ===== */
.ai-bubble {
  background-color: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  color: var(--app-color-text-primary, #26332e);
  border: 1px solid rgba(255, 255, 255, 0.74);
  border-top-left-radius: 10rpx;
  box-shadow: 0 10rpx 30rpx rgba(45, 72, 62, 0.055);
}

/* ===== 用户浅薄荷气泡 ===== */
.user-bubble {
  padding: 18rpx 24rpx;
  background-color: rgba(215, 236, 228, 0.9);
  color: var(--app-color-text-primary, #26332e);
  border: 1px solid rgba(112, 174, 155, 0.16);
  border-top-right-radius: 10rpx;
  box-shadow: 0 8rpx 24rpx rgba(79, 142, 124, 0.08);
}

/* ===== 文本渲染样式 ===== */
.plain-text {
  font-size: 28rpx;
  line-height: 1.58;
}

.markdown-content {
  font-size: 28rpx;
  line-height: 1.72;
}

.markdown-content :deep(.md-p) {
  margin: 12rpx 0;
  line-height: 1.72;
}

.markdown-content :deep(.md-strong) {
  font-weight: 680;
  color: var(--app-color-text-primary, #26332e);
  padding: 0 4rpx;
}

.markdown-content :deep(.md-em) {
  font-style: italic;
  color: var(--app-color-text-secondary, #7c8983);
  padding: 0 4rpx;
  font-weight: normal;
}

.markdown-content :deep(.md-dialogue) {
  color: var(--app-color-text-primary, #26332e);
  font-weight: 650;
}

/* ===== 元数据区域 ===== */
.meta-area {
  display: flex;
  flex-wrap: wrap;
  gap: 8rpx;
  margin-top: 8rpx;
  margin-left: 8rpx;
}

.meta-tag {
  font-size: 20rpx;
  padding: 3rpx 12rpx;
  border-radius: 40rpx;
  background-color: rgba(255, 255, 255, 0.5);
  color: var(--app-color-text-secondary, #7c8983);
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
}

.meta-tag.emotion {
  font-weight: 500;
}

.meta-tag.affection {
  display: inline-flex;
  align-items: center;
  gap: 6rpx;
}

.meta-tag.affection.positive {
  color: var(--app-color-primary-strong, #4f8e7c);
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  border-color: rgba(112, 174, 155, 0.18);
  font-weight: 600;
}

.meta-tag.affection.negative {
  color: var(--app-color-danger, #d9655d);
  background-color: rgba(217, 101, 93, 0.07);
  border-color: rgba(217, 101, 93, 0.16);
  font-weight: 600;
}

.affection-heart-icon-bubble {
  width: 20rpx;
  height: 20rpx;
  flex-shrink: 0;
}

.meta-tag.model-used {
  color: var(--app-color-text-muted, #a4aea9);
  background-color: transparent;
  border-color: transparent;
}

/* ===== TTS Button & Waveform Styles ===== */
.tts-btn {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tts-btn.is-playing {
  color: var(--app-color-primary-strong, #4f8e7c);
  border-color: rgba(112, 174, 155, 0.2);
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
}

.tts-icon {
  width: 20rpx;
  height: 20rpx;
  flex-shrink: 0;
}

.tts-text {
  font-size: 19rpx;
  font-weight: 500;
}

.waveform {
  display: flex;
  align-items: flex-end;
  gap: 3rpx;
  width: 20rpx;
  height: 20rpx;
}

.wave-bar {
  width: 3rpx;
  height: 6rpx;
  background-color: var(--app-color-primary, #70ae9b);
  border-radius: 2rpx;
  animation: bounce 0.8s ease-in-out infinite alternate;
}

.bar-1 {
  animation-delay: 0.1s;
}

.bar-2 {
  animation-delay: 0.3s;
  height: 12rpx;
}

.bar-3 {
  animation-delay: 0.5s;
}

@keyframes bounce {
  from {
    height: 6rpx;
  }
  to {
    height: 18rpx;
  }
}

/* ===== 状态指示器 ===== */
.status-indicator {
  height: 24rpx;
  display: flex;
  align-items: center;
}

.dot-typing {
  width: 8rpx;
  height: 8rpx;
  border-radius: 50%;
  background-color: rgba(79, 142, 124, 0.7);
  box-shadow:
    16rpx 0 0 0 rgba(79, 142, 124, 0.48),
    32rpx 0 0 0 rgba(79, 142, 124, 0.28);
  animation: typing 1s infinite linear;
  margin-left: 4rpx;
}

@keyframes typing {
  0% { box-shadow: 16rpx 0 0 0 rgba(79, 142, 124, 0.48), 32rpx 0 0 0 rgba(79, 142, 124, 0.28); }
  33% { box-shadow: 16rpx 0 0 0 rgba(79, 142, 124, 0.7), 32rpx 0 0 0 rgba(79, 142, 124, 0.48); }
  66% { box-shadow: 16rpx 0 0 0 rgba(79, 142, 124, 0.28), 32rpx 0 0 0 rgba(79, 142, 124, 0.7); }
  100% { box-shadow: 16rpx 0 0 0 rgba(79, 142, 124, 0.48), 32rpx 0 0 0 rgba(79, 142, 124, 0.28); }
}

.cursor-blink {
  display: inline-block;
  width: 4rpx;
  height: 26rpx;
  background-color: var(--app-color-primary-strong, #4f8e7c);
  vertical-align: middle;
  margin-left: 4rpx;
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* ===== AI 思考动态点（流式输出中且尚无内容） ===== */
.streaming-indicator {
  display: inline-flex;
  align-items: center;
}

.ai-thinking {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 6rpx 4rpx;
}

.ai-dot {
  width: 10rpx;
  height: 10rpx;
  border-radius: 50%;
  background-color: var(--app-color-primary, #70ae9b);
  animation: ai-bounce 1.4s ease-in-out infinite;
}

.ai-dot.delay-1 {
  animation-delay: 0.2s;
}

.ai-dot.delay-2 {
  animation-delay: 0.4s;
}

@keyframes ai-bounce {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.35;
  }
  30% {
    transform: translateY(-8rpx);
    opacity: 1;
  }
}

.error-text {
  font-size: 22rpx;
  color: var(--app-color-danger, #d9655d);
  margin-top: 8rpx;
}

/* ===== 推理思考容器 ===== */
.thought-container {
  background-color: rgba(247, 249, 247, 0.72);
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-left: 4rpx solid var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
  border-radius: 16rpx;
  margin-bottom: 20rpx;
  overflow: hidden;
  transition: all 0.2s linear;
}

.thought-container.is-expanded {
  background-color: rgba(238, 246, 241, 0.82);
  border-left-color: var(--app-color-primary, #70ae9b);
}

.thought-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16rpx 20rpx;
  cursor: pointer;
}

.thought-header-left {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.brain-spark {
  width: 10rpx;
  height: 10rpx;
  background-color: var(--app-color-text-muted, #a4aea9);
  border-radius: 50%;
}

.is-expanded .brain-spark {
  background-color: var(--app-color-primary, #70ae9b);
}

.thought-title {
  font-size: 22rpx;
  color: var(--app-color-text-secondary, #7c8983);
  font-weight: 500;
}

.is-expanded .thought-title {
  color: var(--app-color-primary-strong, #4f8e7c);
  font-weight: 600;
}

.thought-arrow {
  font-size: 22rpx;
  color: var(--app-color-text-secondary, #7c8983);
  transition: transform 0.25s ease;
}

.thought-arrow.is-up {
  transform: rotate(180deg);
  color: var(--app-color-primary-strong, #4f8e7c);
}

.thought-body {
  padding: 0 20rpx 20rpx 20rpx;
  border-top: 1px solid rgba(0, 0, 0, 0.02);
}

.thought-markdown-content {
  font-size: 24rpx;
  line-height: 1.5;
  color: var(--app-color-text-secondary, #7c8983);
}

.thought-markdown-content :deep(.md-p) {
  margin: 6rpx 0;
  line-height: 1.5;
}

.thought-markdown-content :deep(.md-strong) {
  font-weight: 600;
  color: var(--app-color-text-primary, #26332e);
}

.thought-markdown-content :deep(.md-em) {
  font-style: italic;
}

/* ===== AI 候选版本切换器 (Swipe Multi-Replies) ===== */
.candidate-pager {
  display: flex;
  align-items: center;
  justify-content: center;
  align-self: flex-start;
  gap: 8rpx;
  margin-top: 8rpx;
  margin-left: 8rpx;
  padding: 2rpx 4rpx;
  background-color: transparent;
  border: 0;
  transition: all 0.2s;
  z-index: 10;
}

.candidate-pager:active {
  background-color: transparent;
}

.pager-btn {
  width: 44rpx;
  height: 44rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: transform 0.1s ease;
}

.pager-btn:active {
  transform: scale(0.85);
}

.pager-arrow {
  font-size: 34rpx;
  color: var(--app-color-text-muted, #a4aea9);
  font-weight: 300;
}

.pager-dots {
  display: flex;
  align-items: center;
  gap: 7rpx;
}

.pager-dot {
  width: 8rpx;
  height: 8rpx;
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
  transition:
    width var(--app-motion-fast, 160ms) ease,
    background-color var(--app-motion-fast, 160ms) ease;
}

.pager-dot.is-active {
  width: 20rpx;
  background-color: var(--app-color-primary, #70ae9b);
}

.pager-text {
  font-size: 19rpx;
  color: var(--app-color-text-muted, #a4aea9);
  font-weight: 550;
  min-width: 42rpx;
  text-align: center;
  letter-spacing: 0.5px;
}
</style>
