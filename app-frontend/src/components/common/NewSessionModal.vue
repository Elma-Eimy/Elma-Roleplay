<template>
  <view class="modal-container" :class="{ 'is-open': isOpen }">
    <view class="backdrop" @tap="closeModal"></view>
    
    <view class="modal-panel" :class="{ 'has-routes': alternateGreetings && alternateGreetings.length > 0 }">
      <view class="modal-header">
        <view class="title-area">
          <text class="modal-title">开启新故事会话</text>
          <text class="modal-subtitle">为当前故事线设置主题并选择切入世界线</text>
        </view>
        <view class="close-btn-wrapper" @tap="closeModal">
          <image class="close-icon" src="/static/icons/modal_close_gray.svg" mode="aspectFit" />
        </view>
      </view>

      <view class="modal-body">
        <view class="input-section">
          <text class="input-label">会话故事主题</text>
          <view class="input-wrapper">
            <image class="input-icon" src="/static/icons/modal_book_gray.svg" mode="aspectFit" />
            <input 
              class="title-input" 
              v-model="sessionTitle" 
              placeholder="为这篇平行世界故事起一个名字..."
              :focus="isOpen"
            />
          </view>
          <text class="input-hint">留空将默认命名为 “新故事会话”</text>
        </view>

        <!-- 路线选择区域 (仅在有多重开场白时展示) -->
        <view v-if="alternateGreetings && alternateGreetings.length > 0" class="route-selection-section">
          <text class="input-label margin-top">选择剧情起点世界线 / Route</text>
          <view class="route-scroll-container">
            <scroll-view scroll-y class="route-scroll" :show-scrollbar="false">
              <view class="route-grid">
                <view 
                  class="route-card" 
                  v-for="opt in routeOptions" 
                  :key="opt.index"
                  :class="{ 'is-active': selectedRouteIndex === opt.index }"
                  @tap="selectedRouteIndex = opt.index"
                >
                  <!-- 侧边彩色指示条 -->
                  <view class="card-accent" :class="opt.routeType.toLowerCase()"></view>
                  
                  <view class="card-content-area">
                    <view class="route-card-header">
                      <text class="route-card-title">{{ opt.title }}</text>
                      <text class="route-badge" :class="opt.routeType.toLowerCase()">
                        {{ opt.routeType }}
                      </text>
                    </view>
                    <view class="route-meta">
                      <image class="loc-icon" :src="getPinIconUrl(opt.routeType)" mode="aspectFit" />
                      <text class="route-loc">{{ opt.location }}</text>
                    </view>
                    <text class="route-preview">“{{ opt.preview }}”</text>
                  </view>
                </view>
              </view>
            </scroll-view>
            <!-- 顶部与底部边缘渐变淡出，防止被硬性切断 -->
            <view class="scroll-fade fade-top"></view>
            <view class="scroll-fade fade-bottom"></view>
          </view>
        </view>
      </view>

      <view class="modal-footer">
        <view class="btn cancel-btn" @tap="closeModal">取消</view>
        <view class="btn confirm-btn" @tap="onConfirm">
          <image class="confirm-icon" src="/static/icons/modal_sparkle_gold.svg" mode="aspectFit" />
          <text class="confirm-text">开启世界线</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch, computed } from "vue";
import { usePersonaStore } from "@/store/personaStore";

const personaStore = usePersonaStore();

const props = defineProps<{
  isOpen: boolean;
  alternateGreetings?: string[];
  characterName?: string;
}>();

const emit = defineEmits<{
  (e: "update:isOpen", value: boolean): void;
  (e: "confirm", payload: { title: string; greeting_index: number | null }): void;
}>();

const sessionTitle = ref("");
const selectedRouteIndex = ref<number>(-1); // -1 代表默认开场

interface RouteOption {
  index: number;
  title: string;
  location: string;
  routeType: string;
  preview: string;
}

// 当模态框打开时清空并重置状态
watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    sessionTitle.value = "";
    selectedRouteIndex.value = -1;
  }
});

const replacePlaceholders = (text: string) => {
  if (!text) return "";
  const charName = props.characterName || "角色";
  const userName = personaStore.userNickname;
  return text
    .replace(/\{\{char\}\}/gi, charName)
    .replace(/\{\{user\}\}/gi, userName);
};

// 动态匹配不同分支路线类型的彩色 Pin 图标路径
const getPinIconUrl = (routeType: string) => {
  const type = (routeType || "standard").toLowerCase();
  const validTypes = ["standard", "teammate", "police", "enemy", "blank", "scenario"];
  return `/static/icons/modal_pin_${validTypes.includes(type) ? type : "standard"}.svg`;
};

const routeOptions = computed<RouteOption[]>(() => {
  const options: RouteOption[] = [];
  
  // 1. 加入默认选项
  options.push({
    index: -1,
    title: "默认开场 (Default)",
    location: "初始场景",
    routeType: "Standard",
    preview: "使用角色的预设标准开场白启动对话。"
  });

  // 2. 遍历解析 alternate_greetings
  if (props.alternateGreetings && props.alternateGreetings.length > 0) {
    props.alternateGreetings.forEach((greeting, idx) => {
      let title = `故事场景 #${idx + 2}`;
      let location = "未知地点";
      let routeType = "Scenario";
      
      // 提取 ✦ 标题 ✦
      const titleMatch = greeting.match(/✦\s*(.*?)\s*✦/);
      if (titleMatch) {
        title = titleMatch[1].replace(/SCENARIO \d+:\s*/i, '').trim();
      }
      
      // 提取 📍 地点
      const locMatch = greeting.match(/###\s*📍\s*([^\n|#]+)/);
      if (locMatch) {
        location = locMatch[1].trim();
      }
      
      // 提取 Route: 分支
      const routeMatch = greeting.match(/Route:\s*([^\n|#]+)/i);
      if (routeMatch) {
        routeType = routeMatch[1].trim();
      }
      
      // 提取正文预览，去掉动作描写（*...*），仅保留干净口语或前句，看起来清爽
      let bodyText = "";
      const textParts = greeting.split('---');
      if (textParts.length > 1) {
        bodyText = textParts[1].replace(/\*.*?\*/g, '').trim();
      } else {
        bodyText = greeting;
      }
      bodyText = replacePlaceholders(bodyText);
      
      // 压缩多余空行，使预览清爽
      const cleanBody = bodyText.replace(/\n+/g, ' ').trim();
      const preview = cleanBody.substring(0, 95) + (cleanBody.length > 95 ? "..." : "");

      options.push({
        index: idx,
        title,
        location,
        routeType,
        preview
      });
    });
  }
  
  return options;
});

const closeModal = () => {
  emit("update:isOpen", false);
};

const onConfirm = () => {
  const finalIdx = selectedRouteIndex.value === -1 ? null : selectedRouteIndex.value;
  emit("confirm", {
    title: sessionTitle.value.trim() || "新故事会话",
    greeting_index: finalIdx
  });
  closeModal();
};
</script>

<style scoped>
.modal-container {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  z-index: 200;
  pointer-events: none;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-container.is-open {
  pointer-events: auto;
}

.backdrop {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.45);
  opacity: 0;
  transition: opacity 0.25s ease;
  backdrop-filter: blur(10px);
}

.is-open .backdrop {
  opacity: 1;
}

.modal-panel {
  position: relative;
  width: 85vw;
  max-width: 580rpx;
  max-height: 85vh;
  background-color: rgba(255, 255, 255, 0.96);
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 38rpx;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.18), 0 4px 16px rgba(0, 0, 0, 0.08);
  transform: translateY(40rpx) scale(0.95);
  opacity: 0;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-panel.has-routes {
  max-width: 680rpx;
  width: 90vw;
}

.is-open .modal-panel {
  transform: translateY(0) scale(1);
  opacity: 1;
}

.modal-header {
  padding: 36rpx 40rpx;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
  background-color: #ffffff;
  flex-shrink: 0;
}

.title-area {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.modal-title {
  font-size: 32rpx;
  font-weight: 700;
  color: #1c1c1e;
  letter-spacing: -0.5px;
}

.modal-subtitle {
  font-size: 20rpx;
  color: #8e8e93;
  font-weight: 500;
}

.close-btn-wrapper {
  width: 50rpx;
  height: 50rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.03);
  transition: background-color 0.2s;
}

.close-btn-wrapper:active {
  background-color: rgba(0, 0, 0, 0.08);
}

.close-icon {
  width: 32rpx;
  height: 32rpx;
}

.modal-body {
  padding: 36rpx 40rpx;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

.input-section {
  display: flex;
  flex-direction: column;
}

.input-label {
  font-size: 22rpx;
  font-weight: 700;
  color: #8e8e93;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12rpx;
}

.input-label.margin-top {
  margin-top: 32rpx;
}

.input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
  width: 100%;
  background-color: rgba(0, 0, 0, 0.025);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 20rpx;
  box-sizing: border-box;
  transition: all 0.2s ease;
}

.input-wrapper:focus-within {
  border-color: #007aff;
  background-color: #ffffff;
  box-shadow: 0 0 0 4px rgba(0, 122, 255, 0.1);
}

.input-icon {
  position: absolute;
  left: 28rpx;
  width: 36rpx;
  height: 36rpx;
  pointer-events: none;
}

.title-input {
  width: 100%;
  height: 84rpx;
  background: transparent;
  border: none;
  padding: 0 28rpx 0 76rpx;
  font-size: 28rpx;
  color: #1c1c1e;
  box-sizing: border-box;
}

.title-input:focus {
  outline: none;
}

.input-hint {
  font-size: 20rpx;
  color: #c7c7cc;
  margin-top: 10rpx;
  font-weight: 500;
  padding-left: 4rpx;
}

/* ===== 路线选择区布局与阴影融合 ===== */
.route-selection-section {
  display: flex;
  flex-direction: column;
  margin-top: 8rpx;
}

.route-scroll-container {
  position: relative;
  width: 100%;
  margin-top: 10rpx;
  border-radius: 24rpx;
  overflow: hidden;
}

.route-scroll {
  max-height: 480rpx;
  width: 100%;
}

.route-grid {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  padding: 8rpx 4rpx 16rpx 4rpx;
}

/* 渐变融合层 */
.scroll-fade {
  position: absolute;
  left: 0;
  right: 0;
  height: 16rpx;
  pointer-events: none;
  z-index: 10;
}

.fade-top {
  top: 0;
  background: linear-gradient(to bottom, rgba(255, 255, 255, 1), rgba(255, 255, 255, 0));
}

.fade-bottom {
  bottom: 0;
  background: linear-gradient(to top, rgba(255, 255, 255, 1), rgba(255, 255, 255, 0));
}

/* ===== 故事路线卡片精细重构 ===== */
.route-card {
  position: relative;
  background-color: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.05);
  border-radius: 24rpx;
  padding: 24rpx 28rpx 24rpx 36rpx; /* 左侧留出给指示条的空间 */
  display: flex;
  flex-direction: column;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.015);
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  cursor: pointer;
  overflow: hidden;
}

.route-card:active {
  transform: scale(0.985);
}

.route-card.is-active {
  background-color: #ffffff;
  border-color: #007aff;
  box-shadow: 0 8px 24px rgba(0, 122, 255, 0.08);
  transform: translateY(-2rpx);
}

/* 侧边彩色指示条 */
.card-accent {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 8rpx;
  background-color: #e5e5ea;
  transition: all 0.25s ease;
}

.card-accent.standard { background-color: #8e8e93; }
.card-accent.teammate { background-color: #ff2d55; }
.card-accent.police { background-color: #007aff; }
.card-accent.enemy { background-color: #ff9500; }
.card-accent.blank { background-color: #5856d6; }
.card-accent.scenario { background-color: #34c759; }

.card-content-area {
  display: flex;
  flex-direction: column;
  gap: 10rpx;
}

.route-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16rpx;
}

.route-card-title {
  font-size: 28rpx;
  font-weight: 700;
  color: #1c1c1e;
  letter-spacing: -0.2px;
}

.route-badge {
  font-size: 18rpx;
  font-weight: 700;
  padding: 6rpx 16rpx;
  border-radius: 40rpx;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* 路线标签配色系统 */
.route-badge.standard {
  background-color: rgba(142, 142, 147, 0.1);
  color: #8e8e93;
}

.route-badge.teammate {
  background-color: rgba(255, 45, 85, 0.08);
  color: #ff2d55;
  border: 1px solid rgba(255, 45, 85, 0.12);
}

.route-badge.police {
  background-color: rgba(0, 122, 255, 0.08);
  color: #007aff;
  border: 1px solid rgba(0, 122, 255, 0.12);
}

.route-badge.enemy {
  background-color: rgba(255, 149, 0, 0.08);
  color: #ff9500;
  border: 1px solid rgba(255, 149, 0, 0.12);
}

.route-badge.blank {
  background-color: rgba(88, 86, 214, 0.08);
  color: #5856d6;
  border: 1px solid rgba(88, 86, 214, 0.12);
}

.route-badge.scenario {
  background-color: rgba(52, 199, 89, 0.08);
  color: #34c759;
  border: 1px solid rgba(52, 199, 89, 0.12);
}

.route-meta {
  display: flex;
  align-items: center;
  gap: 8rpx;
}

.loc-icon {
  width: 24rpx;
  height: 24rpx;
}

.route-loc {
  font-size: 22rpx;
  font-weight: 600;
  color: #8e8e93;
}

.route-preview {
  font-size: 24rpx;
  color: #8e8e93;
  line-height: 1.45;
  font-style: italic;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  text-overflow: ellipsis;
}

.route-card.is-active .route-preview {
  color: #48484a;
}

/* ===== 底部操作按钮 ===== */
.modal-footer {
  padding: 28rpx 40rpx 40rpx 40rpx;
  display: flex;
  justify-content: flex-end;
  gap: 20rpx;
  border-top: 1px solid rgba(0, 0, 0, 0.04);
  background-color: #ffffff;
  flex-shrink: 0;
}

.btn {
  padding: 22rpx 48rpx;
  border-radius: 44rpx;
  font-size: 28rpx;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.cancel-btn {
  background-color: rgba(0, 0, 0, 0.03);
  color: #48484a;
}

.cancel-btn:active {
  background-color: rgba(0, 0, 0, 0.08);
  transform: scale(0.97);
}

.confirm-btn {
  background-color: #1c1c1e;
  color: #ffffff;
  box-shadow: 0 6px 16px rgba(28, 28, 30, 0.15);
}

.confirm-btn:active {
  background-color: #000000;
  transform: scale(0.97);
  box-shadow: 0 2px 6px rgba(28, 28, 30, 0.1);
}

.confirm-icon {
  width: 28rpx;
  height: 28rpx;
}
</style>
