<template>
  <view class="modal-container" :class="{ 'is-open': isOpen }">
    <view class="backdrop" @tap="closeModal"></view>
    
    <view class="modal-panel" :class="{ 'has-routes': alternateGreetings && alternateGreetings.length > 0 }">
      <view class="modal-header">
        <text class="modal-title">开启新故事会话</text>
        <view class="close-btn-wrapper" @tap="closeModal">
          <PhX class="close-icon" :size="16" weight="regular" />
        </view>
      </view>

      <view class="modal-body">
        <text class="input-label">会话故事主题</text>
        <input 
          class="title-input" 
          v-model="sessionTitle" 
          placeholder="为这篇故事起一个名字..."
          :focus="isOpen"
        />
        <text class="input-hint">留空将使用默认标题 “新故事会话”。</text>

        <!-- 路线选择区域 (仅在有多重开场白时展示) -->
        <view v-if="alternateGreetings && alternateGreetings.length > 0" class="route-selection-section">
          <text class="input-label margin-top">选择剧情路线 (Route)</text>
          <scroll-view scroll-y class="route-scroll">
            <view class="route-grid">
              <view 
                class="route-card" 
                v-for="opt in routeOptions" 
                :key="opt.index"
                :class="{ 'is-active': selectedRouteIndex === opt.index }"
                @tap="selectedRouteIndex = opt.index"
              >
                <view class="route-card-header">
                  <text class="route-card-title">{{ opt.title }}</text>
                  <text class="route-badge" :class="opt.routeType.toLowerCase()">
                    {{ opt.routeType }}
                  </text>
                </view>
                <view class="route-meta">
                  <text class="route-loc">📍 {{ opt.location }}</text>
                </view>
                <text class="route-preview">{{ opt.preview }}</text>
              </view>
            </view>
          </scroll-view>
        </view>
      </view>

      <view class="modal-footer">
        <view class="btn cancel-btn" @tap="closeModal">取消</view>
        <view class="btn confirm-btn" @tap="onConfirm">开启</view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch, computed } from "vue";
import { PhX } from "@phosphor-icons/vue";

const props = defineProps<{
  isOpen: boolean;
  alternateGreetings?: string[];
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
      
      // 提取正文预览
      let bodyText = "";
      const textParts = greeting.split('---');
      if (textParts.length > 1) {
        bodyText = textParts[1].replace(/\*.*?\*/g, '').replace(/\{\{char\}\}/g, 'AI').trim();
      } else {
        bodyText = greeting;
      }
      const preview = bodyText.substring(0, 90) + (bodyText.length > 90 ? "..." : "");

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
  background-color: rgba(0, 0, 0, 0.3);
  opacity: 0;
  transition: opacity 0.25s ease;
  backdrop-filter: blur(4px);
}

.is-open .backdrop {
  opacity: 1;
}

.modal-panel {
  position: relative;
  width: 85vw;
  max-width: 580rpx;
  background-color: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.05);
  border-radius: 28rpx;
  box-shadow: 0 15px 40px rgba(0, 0, 0, 0.12);
  transform: translateY(30rpx) scale(0.96);
  opacity: 0;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  display: flex;
  flex-direction: column;
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
  padding: 32rpx 36rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(0, 0, 0, 0.03);
}

.modal-title {
  font-size: 30rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.close-btn-wrapper {
  width: 44rpx;
  height: 44rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.02);
}

.close-btn-wrapper:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.close-icon {
  color: #8e8e93;
}

.modal-body {
  padding: 36rpx;
  display: flex;
  flex-direction: column;
}

.input-label {
  font-size: 24rpx;
  font-weight: 600;
  color: #48484a;
  margin-bottom: 16rpx;
}

.input-label.margin-top {
  margin-top: 28rpx;
}

.title-input {
  width: 100%;
  height: 80rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 14rpx;
  padding: 0 20rpx;
  font-size: 28rpx;
  color: #1c1c1e;
  box-sizing: border-box;
}

.title-input:focus {
  border-color: #1c1c1e;
  background-color: #ffffff;
}

.input-hint {
  font-size: 22rpx;
  color: #8e8e93;
  margin-top: 14rpx;
}

/* ===== 路线选择布局 ===== */
.route-selection-section {
  display: flex;
  flex-direction: column;
  margin-top: 8rpx;
}

.route-scroll {
  max-height: 480rpx;
  width: 100%;
  margin-top: 8rpx;
}

.route-grid {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  padding: 4rpx;
}

.route-card {
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 20rpx;
  padding: 24rpx;
  display: flex;
  flex-direction: column;
  gap: 12rpx;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  cursor: pointer;
}

.route-card:active {
  transform: scale(0.985);
}

.route-card.is-active {
  background-color: #ffffff;
  border-color: #1c1c1e;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.04);
}

.route-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12rpx;
}

.route-card-title {
  font-size: 26rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.route-badge {
  font-size: 18rpx;
  font-weight: 600;
  padding: 4rpx 14rpx;
  border-radius: 40rpx;
  background-color: rgba(0, 0, 0, 0.05);
  color: #8e8e93;
  text-transform: uppercase;
}

/* 路线类型徽章配色 */
.route-badge.standard {
  background-color: rgba(0, 0, 0, 0.05);
  color: #1c1c1e;
}

.route-badge.teammate {
  background-color: rgba(196, 30, 58, 0.08);
  color: #c41e3a;
}

.route-badge.police {
  background-color: rgba(52, 152, 219, 0.08);
  color: #3498db;
}

.route-badge.enemy {
  background-color: rgba(230, 126, 34, 0.08);
  color: #e67e22;
}

.route-badge.blank {
  background-color: rgba(127, 140, 141, 0.08);
  color: #7f8c8d;
}

.route-meta {
  display: flex;
}

.route-loc {
  font-size: 20rpx;
  font-weight: 500;
  color: #8e8e93;
}

.route-preview {
  font-size: 22rpx;
  color: #8e8e93;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}

.route-card.is-active .route-preview {
  color: #48484a;
}

.modal-footer {
  padding: 24rpx 36rpx 36rpx 36rpx;
  display: flex;
  justify-content: flex-end;
  gap: 16rpx;
  border-top: 1px solid rgba(0, 0, 0, 0.03);
}

.btn {
  padding: 16rpx 36rpx;
  border-radius: 40rpx;
  font-size: 26rpx;
  font-weight: 600;
  text-align: center;
  transition: all 0.2s;
}

.cancel-btn {
  background-color: rgba(0, 0, 0, 0.03);
  color: #48484a;
}

.cancel-btn:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.confirm-btn {
  background-color: #1c1c1e;
  color: #ffffff;
}

.confirm-btn:active {
  background-color: #000000;
  transform: scale(0.96);
}
</style>
