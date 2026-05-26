<template>
  <view 
    class="chat-bubble-wrapper" 
    :class="{ 'is-user': isUser }" 
    @touchstart="onTouchStart"
    @touchmove="onTouchMove"
    @touchend="onTouchEnd"
    @touchcancel="onTouchCancel"
    @contextmenu.prevent="handleLongPress"
  >
    <!-- AI 头像（仅对 AI 显示） -->
    <image 
      v-if="!isUser" 
      class="avatar" 
      :src="avatarUrl || defaultAvatar" 
      mode="aspectFill"
    />

    <view class="bubble-content-area">
      <!-- AI 姓名标签 -->
      <text v-if="!isUser && showName" class="name-tag">{{ characterName }}</text>

      <!-- 消息气泡 -->
      <view class="bubble" :class="[isUser ? 'user-bubble' : 'ai-bubble']">
        
        <!-- AI 的深度思考过程容器 -->
        <view v-if="!isUser && hasThought" class="thought-container" :class="{ 'is-expanded': isThoughtExpanded }">
          <view class="thought-header" @tap="isThoughtExpanded = !isThoughtExpanded">
            <view class="thought-header-left">
              <view class="brain-spark"></view>
              <text class="thought-title">{{ isThoughtExpanded ? '深度思考过程' : 'AI 已完成思考 (点击展开)' }}</text>
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

      <!-- 元数据信息（情绪标签、好感度变动与所使用的模型） -->
      <view v-if="!isUser && hasMeta" class="meta-area">
        <view v-if="message.emotion_tag" class="meta-tag emotion">
          {{ message.emotion_tag }}
        </view>
        <view v-if="message.affection_change" class="meta-tag affection" :class="{ positive: message.affection_change > 0, negative: message.affection_change < 0 }">
          {{ message.affection_change > 0 ? '+' : '' }}{{ message.affection_change }} 💖
        </view>
        <view v-if="message.model_used" class="meta-tag model-used">
          {{ message.model_used }}
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import type { ChatMessage } from "@/store/chatStore";
import MarkdownIt from "markdown-it";

const props = defineProps<{
  message: ChatMessage;
  avatarUrl?: string;
  characterName?: string;
  showName?: boolean;
}>();

const emit = defineEmits<{
  (e: "longpress", message: ChatMessage): void;
}>();

let touchTimer: any = null;
let startX = 0;
let startY = 0;
let isTriggered = false;

const onTouchStart = (e: TouchEvent) => {
  if (props.message.status === 'sending' || props.message.status === 'streaming') return;
  
  isTriggered = false;
  const touch = e.touches[0];
  startX = touch.clientX;
  startY = touch.clientY;
  
  if (touchTimer) clearTimeout(touchTimer);
  
  // 设置 800ms 的长按阈值，避免轻触或上下滑动滚动列表时误触
  touchTimer = setTimeout(() => {
    isTriggered = true;
    handleLongPress();
  }, 800);
};

const onTouchMove = (e: TouchEvent) => {
  if (!touchTimer || isTriggered) return;
  
  const touch = e.touches[0];
  const deltaX = Math.abs(touch.clientX - startX);
  const deltaY = Math.abs(touch.clientY - startY);
  
  // 如果手指位移超过 10 像素（表明用户在滚动列表），立即取消长按判定
  if (deltaX > 10 || deltaY > 10) {
    clearTimeout(touchTimer);
    touchTimer = null;
  }
};

const onTouchEnd = () => {
  if (touchTimer) {
    clearTimeout(touchTimer);
    touchTimer = null;
  }
};

const onTouchCancel = () => {
  if (touchTimer) {
    clearTimeout(touchTimer);
    touchTimer = null;
  }
};

const handleLongPress = (e?: Event) => {
  // 阻止 H5 平台上浏览器原生的右键菜单
  if (e) e.preventDefault?.();
  // 仅允许在发送完成或发送失败的消息上执行操作
  if (props.message.status !== 'sending' && props.message.status !== 'streaming') {
    // vibrateShort（短震动）仅在原生 App 平台可用，H5 平台下直接忽略该调用
    try {
      uni.vibrateShort({
        success: function () {
            console.log('vibrate short success');
        }
      });
    } catch (_) {}
    emit("longpress", props.message);
  }
};

const isUser = computed(() => props.message.role === "user");

const defaultAvatar = "/static/default-avatar.png";

const hasMeta = computed(() => {
  return props.message.emotion_tag || props.message.affection_change || props.message.model_used;
});

const md = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
});

// 推理思维链内容解析
const isThoughtExpanded = ref(false);

const parsedContent = computed(() => {
  const content = props.message.content || "";
  if (isUser.value) {
    return { thought: "", reply: content };
  }
  
  // 用于提取 <thought>...</thought> 推理内容的正则表达式
  const thoughtRegex = /<thought>([\s\S]*?)<\/thought>/i;
  const match = content.match(thoughtRegex);
  
  if (match) {
    const thought = match[1].trim();
    const reply = content.replace(thoughtRegex, "").trim();
    return { thought, reply };
  }
  
  return { thought: "", reply: content };
});

const hasThought = computed(() => !!parsedContent.value.thought);

const renderedMarkdown = computed(() => {
  const replyContent = parsedContent.value.reply;
  if (isUser.value || !replyContent) return "";
  let html = md.render(replyContent);
  html = html.replace(/<p>/g, '<p class="md-p">');
  html = html.replace(/<em>/g, '<em class="md-em">');
  html = html.replace(/<strong>/g, '<strong class="md-strong">');
  return html;
});

const renderedThought = computed(() => {
  const thoughtContent = parsedContent.value.thought;
  if (!thoughtContent) return "";
  let html = md.render(thoughtContent);
  html = html.replace(/<p>/g, '<p class="md-p">');
  html = html.replace(/<em>/g, '<em class="md-em">');
  html = html.replace(/<strong>/g, '<strong class="md-strong">');
  return html;
});
</script>

<style scoped>
.chat-bubble-wrapper {
  display: flex;
  width: 100%;
  padding: 16rpx 36rpx;
  margin-bottom: 8rpx;
  gap: 16rpx;
  align-items: flex-start;
}

.chat-bubble-wrapper.is-user {
  flex-direction: row-reverse;
}

/* ===== 头像样式 ===== */
.avatar {
  width: 76rpx;
  height: 76rpx;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.05);
  flex-shrink: 0;
}

/* ===== 内容区域 ===== */
.bubble-content-area {
  display: flex;
  flex-direction: column;
  max-width: 72%;
}

.is-user .bubble-content-area {
  align-items: flex-end;
}

/* ===== 名字标签 ===== */
.name-tag {
  font-size: 22rpx;
  color: #8e8e93;
  margin-bottom: 6rpx;
  margin-left: 8rpx;
  font-weight: 500;
}

/* ===== 气泡基础样式 ===== */
.bubble {
  padding: 20rpx 28rpx;
  border-radius: 28rpx;
  position: relative;
  word-break: break-word;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.01);
}

/* ===== AI 气泡（高级白） ===== */
.ai-bubble {
  background-color: #ffffff;
  color: #1c1c1e;
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-top-left-radius: 4rpx;
}

/* ===== 用户气泡（高级黑） ===== */
.user-bubble {
  background-color: #1c1c1e;
  color: #ffffff;
  border-top-right-radius: 4rpx;
}

/* ===== 文本渲染样式 ===== */
.plain-text {
  font-size: 28rpx;
  line-height: 1.5;
}

.markdown-content {
  font-size: 28rpx;
  line-height: 1.6;
}

.markdown-content :deep(.md-p) {
  margin: 10rpx 0;
  line-height: 1.6;
}

.markdown-content :deep(.md-strong) {
  font-weight: 600;
  color: #000000;
  padding: 0 4rpx;
}

.markdown-content :deep(.md-em) {
  font-style: italic;
  color: #3a3a3c;
  padding: 0 4rpx;
}

/* ===== 元数据区域 ===== */
.meta-area {
  display: flex;
  gap: 12rpx;
  margin-top: 10rpx;
  margin-left: 6rpx;
}

.meta-tag {
  font-size: 20rpx;
  padding: 4rpx 14rpx;
  border-radius: 40rpx;
  background-color: rgba(0, 0, 0, 0.02);
  color: #555558;
  border: 1px solid rgba(0, 0, 0, 0.04);
}

.meta-tag.emotion {
  font-weight: 500;
}

.meta-tag.affection.positive {
  color: #1c1c1e;
  background-color: #ffffff;
  border-color: rgba(0, 0, 0, 0.15);
  font-weight: 600;
}

.meta-tag.affection.negative {
  color: #ff3b30;
  background-color: rgba(255, 59, 48, 0.05);
  border-color: rgba(255, 59, 48, 0.15);
  font-weight: 600;
}

.meta-tag.model-used {
  color: #8e8e93;
  background-color: rgba(0, 0, 0, 0.01);
  border-color: rgba(0, 0, 0, 0.03);
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
  background-color: rgba(255, 255, 255, 0.6);
  box-shadow: 16rpx 0 0 0 rgba(255, 255, 255, 0.4), 32rpx 0 0 0 rgba(255, 255, 255, 0.2);
  animation: typing 1s infinite linear;
  margin-left: 4rpx;
}

@keyframes typing {
  0% { box-shadow: 16rpx 0 0 0 rgba(255, 255, 255, 0.4), 32rpx 0 0 0 rgba(255, 255, 255, 0.2); }
  33% { box-shadow: 16rpx 0 0 0 rgba(255, 255, 255, 0.6), 32rpx 0 0 0 rgba(255, 255, 255, 0.4); }
  66% { box-shadow: 16rpx 0 0 0 rgba(255, 255, 255, 0.2), 32rpx 0 0 0 rgba(255, 255, 255, 0.6); }
  100% { box-shadow: 16rpx 0 0 0 rgba(255, 255, 255, 0.4), 32rpx 0 0 0 rgba(255, 255, 255, 0.2); }
}

.cursor-blink {
  display: inline-block;
  width: 4rpx;
  height: 26rpx;
  background-color: #1c1c1e;
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
  background-color: rgba(0, 0, 0, 0.2);
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
  color: #ff3b30;
  margin-top: 8rpx;
}

/* ===== 推理思考容器 ===== */
.thought-container {
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 16rpx;
  margin-bottom: 20rpx;
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.thought-container.is-expanded {
  background-color: rgba(0, 0, 0, 0.03);
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
  background-color: #8e8e93;
  border-radius: 50%;
  position: relative;
}

.is-expanded .brain-spark {
  background-color: #10b981;
}

.is-expanded .brain-spark::after {
  content: "";
  position: absolute;
  top: -4rpx;
  left: -4rpx;
  width: 18rpx;
  height: 18rpx;
  border: 1px solid #10b981;
  border-radius: 50%;
  animation: pulse 1.6s infinite ease-out;
}

@keyframes pulse {
  0% { transform: scale(0.6); opacity: 1; }
  100% { transform: scale(1.4); opacity: 0; }
}

.thought-title {
  font-size: 22rpx;
  color: #8e8e93;
  font-weight: 500;
}

.is-expanded .thought-title {
  color: #1c1c1e;
  font-weight: 600;
}

.thought-arrow {
  font-size: 22rpx;
  color: #8e8e93;
  transition: transform 0.25s ease;
}

.thought-arrow.is-up {
  transform: rotate(180deg);
  color: #1c1c1e;
}

.thought-body {
  padding: 0 20rpx 20rpx 20rpx;
  border-top: 1px solid rgba(0, 0, 0, 0.02);
}

.thought-markdown-content {
  font-size: 24rpx;
  line-height: 1.5;
  color: #8e8e93;
}

.thought-markdown-content :deep(.md-p) {
  margin: 6rpx 0;
  line-height: 1.5;
}

.thought-markdown-content :deep(.md-strong) {
  font-weight: 600;
  color: #555558;
}

.thought-markdown-content :deep(.md-em) {
  font-style: italic;
}
</style>
