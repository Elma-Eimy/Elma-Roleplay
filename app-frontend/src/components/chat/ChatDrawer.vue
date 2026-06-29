<template>
  <!-- 记忆与微观认知状态右侧抽屉面板 -->
  <view v-if="isOpen" class="status-panel-backdrop" :class="{ 'is-android': isAndroid }" @tap="emit('close')">
    <view class="status-panel" @tap.stop>

      <!-- 面板头部：仅包含关闭按钮 -->
      <view class="panel-header">
        <view class="close-btn" @tap="emit('close')">
          <image class="close-icon" src="/static/icons/drawer_close.svg" mode="aspectFit" />
        </view>
      </view>

      <scroll-view scroll-y class="panel-content">

        <!-- ① 角色卡片面板 -->
        <view class="char-card">
          <image
            class="char-card-avatar"
            :src="getAvatarUrl(personaStore.activeCharacter?.avatar_path || '')"
            mode="aspectFill"
          />
          <view class="char-card-info">
            <text class="char-card-name">{{ personaStore.characterName }}</text>
            <view class="mood-badge">
              <view class="mood-dot"></view>
              <text class="mood-text">{{ personaStore.currentMood || '在线' }}</text>
            </view>
          </view>
        </view>

        <!-- ② 好感度数值与进度条 -->
        <view class="panel-section">
          <view class="section-title-row">
            <text class="section-title">好感度</text>
            <view class="affection-value-wrapper">
              <image class="affection-heart-icon-drawer" :src="affectionIcon" mode="aspectFit" />
              <text class="affection-value">{{ personaStore.affectionScore }} / 100</text>
            </view>
          </view>
          <view class="progress-bg">
            <view class="progress-bar-gradient" :style="{ width: personaStore.affectionPercent + '%' }"></view>
          </view>
        </view>

        <!-- ③ 微观认知状态显示区 -->
        <view class="panel-section">
          <text class="section-title">微观认知</text>
          <view class="cognition-box">
            <text class="cognition-text">{{ personaStore.cognitionState || '暂无认知记录。' }}</text>
          </view>
        </view>

        <!-- 👤 我的设定区域 -->
        <view class="panel-section">
          <text class="section-title">我的设定</text>
          <view class="setting-row">
            <view class="setting-row-left">
              <image 
                class="setting-row-icon" 
                src="/static/icons/menu_user_plus.svg" 
                mode="aspectFit" 
              />
              <text class="setting-row-label">我的昵称</text>
            </view>
            <input 
              class="drawer-nickname-input" 
              v-model="userNicknameInput" 
              @blur="saveUserNickname"
              confirm-type="done"
              @confirm="saveUserNickname"
              placeholder="请输入你的昵称..."
            />
          </view>
        </view>

        <!-- ④ 对话配置开关项 -->
        <view class="panel-section">
          <text class="section-title">对话设置</text>
          <view class="setting-row">
            <view class="setting-row-left">
              <image 
                class="setting-row-icon" 
                :src="chatSettingsStore.useReasoning ? '/static/icons/chat_sparkle_active.svg' : '/static/icons/chat_sparkle.svg'" 
                mode="aspectFit" 
              />
              <text class="setting-row-label">深度思考模式</text>
            </view>
            <view
              class="custom-toggle"
              :class="{ 'is-on': chatSettingsStore.useReasoning }"
              @tap="chatSettingsStore.useReasoning = !chatSettingsStore.useReasoning"
            >
              <view class="toggle-thumb"></view>
            </view>
          </view>

          <view class="setting-row cursor-pointer" style="margin-top: 20rpx;" @tap="showAdvancedParams = !showAdvancedParams">
            <view class="setting-row-left">
              <image 
                class="setting-row-icon" 
                :src="showAdvancedParams ? '/static/icons/settings_sliders_active.svg' : '/static/icons/settings_sliders.svg'" 
                mode="aspectFit" 
              />
              <text class="setting-row-label">高级采样参数</text>
            </view>
            <image 
              class="advanced-chevron" 
              :class="{ 'is-active': showAdvancedParams }" 
              src="/static/icons/settings_chevron.svg" 
              mode="aspectFit" 
            />
          </view>

          <!-- 当展开高级采样参数时展示 -->
          <view class="drawer-sliders-container" v-if="showAdvancedParams">
            <!-- Temperature -->
            <view class="drawer-slider-row">
              <view class="drawer-slider-header">
                <text class="drawer-slider-label">创意温度 (Temperature)</text>
                <view class="drawer-slider-value-wrapper">
                  <text class="drawer-slider-value" :class="{ 'is-default': chatSettingsStore.temperature === null }">
                    {{ chatSettingsStore.temperature !== null ? chatSettingsStore.temperature.toFixed(1) : '默认 (1.0)' }}
                  </text>
                  <text 
                    v-if="chatSettingsStore.temperature !== null" 
                    class="drawer-slider-reset" 
                    @tap.stop="chatSettingsStore.temperature = null"
                  >重置</text>
                </view>
              </view>
              <slider
                class="drawer-slider-component"
                :value="Math.round((chatSettingsStore.temperature ?? 1.0) * 10)"
                :min="1" :max="20" :step="1"
                activeColor="#1c1c1e"
                backgroundColor="rgba(0,0,0,0.07)"
                block-color="#ffffff"
                block-size="18"
                @change="(e: any) => chatSettingsStore.temperature = e.detail.value / 10"
              />
            </view>

            <!-- Top P -->
            <view class="drawer-slider-row">
              <view class="drawer-slider-header">
                <text class="drawer-slider-label">核采样比例 (Top P)</text>
                <view class="drawer-slider-value-wrapper">
                  <text class="drawer-slider-value" :class="{ 'is-default': chatSettingsStore.top_p === null }">
                    {{ chatSettingsStore.top_p !== null ? chatSettingsStore.top_p.toFixed(2) : '默认 (1.00)' }}
                  </text>
                  <text 
                    v-if="chatSettingsStore.top_p !== null" 
                    class="drawer-slider-reset" 
                    @tap.stop="chatSettingsStore.top_p = null"
                  >重置</text>
                </view>
              </view>
              <slider
                class="drawer-slider-component"
                :value="Math.round((chatSettingsStore.top_p ?? 1.0) * 100)"
                :min="10" :max="100" :step="5"
                activeColor="#1c1c1e"
                backgroundColor="rgba(0,0,0,0.07)"
                block-color="#ffffff"
                block-size="18"
                @change="(e: any) => chatSettingsStore.top_p = e.detail.value / 100"
              />
            </view>

            <!-- Presence Penalty -->
            <view class="drawer-slider-row">
              <view class="drawer-slider-header">
                <text class="drawer-slider-label">存在惩罚 (Presence Penalty)</text>
                <view class="drawer-slider-value-wrapper">
                  <text class="drawer-slider-value" :class="{ 'is-default': chatSettingsStore.presence_penalty === null }">
                    {{ chatSettingsStore.presence_penalty !== null ? chatSettingsStore.presence_penalty.toFixed(1) : '默认 (0.0)' }}
                  </text>
                  <text 
                    v-if="chatSettingsStore.presence_penalty !== null" 
                    class="drawer-slider-reset" 
                    @tap.stop="chatSettingsStore.presence_penalty = null"
                  >重置</text>
                </view>
              </view>
              <slider
                class="drawer-slider-component"
                :value="Math.round(((chatSettingsStore.presence_penalty ?? 0.0) + 2) * 10)"
                :min="0" :max="40" :step="1"
                activeColor="#1c1c1e"
                backgroundColor="rgba(0,0,0,0.07)"
                block-color="#ffffff"
                block-size="18"
                @change="(e: any) => chatSettingsStore.presence_penalty = (e.detail.value / 10) - 2"
              />
            </view>

            <!-- Frequency Penalty -->
            <view class="drawer-slider-row">
              <view class="drawer-slider-header">
                <text class="drawer-slider-label">频率惩罚 (Frequency Penalty)</text>
                <view class="drawer-slider-value-wrapper">
                  <text class="drawer-slider-value" :class="{ 'is-default': chatSettingsStore.frequency_penalty === null }">
                    {{ chatSettingsStore.frequency_penalty !== null ? chatSettingsStore.frequency_penalty.toFixed(1) : '默认 (0.0)' }}
                  </text>
                  <text 
                    v-if="chatSettingsStore.frequency_penalty !== null" 
                    class="drawer-slider-reset" 
                    @tap.stop="chatSettingsStore.frequency_penalty = null"
                  >重置</text>
                </view>
              </view>
              <slider
                class="drawer-slider-component"
                :value="Math.round(((chatSettingsStore.frequency_penalty ?? 0.0) + 2) * 10)"
                :min="0" :max="40" :step="1"
                activeColor="#1c1c1e"
                backgroundColor="rgba(0,0,0,0.07)"
                block-color="#ffffff"
                block-size="18"
                @change="(e: any) => chatSettingsStore.frequency_penalty = (e.detail.value / 10) - 2"
              />
            </view>

            <!-- Repetition Penalty -->
            <view class="drawer-slider-row">
              <view class="drawer-slider-header">
                <text class="drawer-slider-label">重复度惩罚 (Repetition Penalty)</text>
                <view class="drawer-slider-value-wrapper">
                  <text class="drawer-slider-value" :class="{ 'is-default': chatSettingsStore.repetition_penalty === null }">
                    {{ chatSettingsStore.repetition_penalty !== null ? chatSettingsStore.repetition_penalty.toFixed(2) : '默认 (1.00)' }}
                  </text>
                  <text 
                    v-if="chatSettingsStore.repetition_penalty !== null" 
                    class="drawer-slider-reset" 
                    @tap.stop="chatSettingsStore.repetition_penalty = null"
                  >重置</text>
                </view>
              </view>
              <slider
                class="drawer-slider-component"
                :value="Math.round((chatSettingsStore.repetition_penalty ?? 1.0) * 100)"
                :min="50" :max="200" :step="5"
                activeColor="#1c1c1e"
                backgroundColor="rgba(0,0,0,0.07)"
                block-color="#ffffff"
                block-size="18"
                @change="(e: any) => chatSettingsStore.repetition_penalty = e.detail.value / 100"
              />
            </view>
          </view>
        </view>

        <!-- ④-2 平行时空分支树 -->
        <view class="panel-section">
          <text class="section-title">平行宇宙</text>
          <view class="action-btn outline" @tap="emit('open-branch-tree')">
            <image class="btn-icon" src="/static/icons/char_branch.svg" mode="aspectFit" />
            <text class="btn-text">查看分支时空树</text>
          </view>
        </view>

        <!-- ⑤ 记忆管理手动操作区 -->
        <view class="panel-section">
          <text class="section-title">记忆管理</text>
          <view class="action-btn outline" @tap="emit('open-memory-view')">
            <image class="btn-icon" src="/static/icons/settings_database.svg" mode="aspectFit" />
            <text class="btn-text">查看向量记忆库</text>
          </view>
          <view class="action-btn outline" @tap="forceMemoryExtract">
            <image class="btn-icon" src="/static/icons/drawer_brain.svg" mode="aspectFit" />
            <text class="btn-text">手动提取记忆元</text>
          </view>
          <view class="action-btn outline" @tap="updateCognition">
            <image class="btn-icon" src="/static/icons/drawer_sync.svg" mode="aspectFit" />
            <text class="btn-text">更新微观认知</text>
          </view>
        </view>

        <!-- 调试工具区域 -->
        <view class="panel-section">
          <text class="section-title">系统调试</text>
          <view class="action-btn outline" @tap="emit('open-prompt-preview')">
            <image class="btn-icon" src="/static/icons/chat_sparkle.svg" mode="aspectFit" />
            <text class="btn-text">查看当前 Prompt 组装</text>
          </view>
        </view>

        <!-- ⑥ 危险操作区域（删除会话） -->
        <view class="panel-section danger-section">
          <text class="section-title danger-title">危险操作</text>
          <view class="action-btn danger-btn" @tap="deleteCurrentSession">
            <image class="danger-icon" src="/static/icons/drawer_trash.svg" mode="aspectFit" />
            <text class="danger-btn-text">删除本次会话</text>
          </view>
        </view>

      </scroll-view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import { useChatStore } from "@/store/chatStore";
import { usePersonaStore } from "@/store/personaStore";
import { useChatSettingsStore } from "@/store/chatSettingsStore";
import { getAvatarUrl } from "@/api/characters";
import { triggerSummary, triggerCognition } from "@/api/sessions";

const props = defineProps<{
  isOpen: boolean;
  sessionId: number | null;
}>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "delete-session"): void;
  (e: "open-branch-tree"): void;
  (e: "open-memory-view"): void;
  (e: "open-prompt-preview"): void;
}>();

const chatStore = useChatStore();
const personaStore = usePersonaStore();
const chatSettingsStore = useChatSettingsStore();

const showAdvancedParams = ref(false);
const userNicknameInput = ref(personaStore.userNickname);

// 监听昵称的变化进行双向绑定
watch(() => personaStore.userNickname, (newVal) => {
  userNicknameInput.value = newVal;
});

const saveUserNickname = () => {
  const name = userNicknameInput.value.trim();
  if (name) {
    personaStore.updateUserNickname(name);
  } else {
    userNicknameInput.value = personaStore.userNickname;
  }
};

const forceMemoryExtract = async () => {
  if (props.sessionId === null) return;
  try {
    uni.showLoading({ title: "正在提取记忆元..." });
    const res = await triggerSummary(props.sessionId);
    uni.hideLoading();
    uni.showToast({ title: res.message || "记忆提取完成", icon: "success" });
  } catch (e) {
    uni.hideLoading();
    uni.showToast({ title: "记忆提取失败", icon: "none" });
    console.error(e);
  }
};

const updateCognition = async () => {
  if (props.sessionId === null) return;
  try {
    uni.showLoading({ title: "正在更新认知..." });
    const res = await triggerCognition(props.sessionId);
    await personaStore.loadSessionDetail(props.sessionId);
    uni.hideLoading();
    uni.showToast({ title: res.message || "认知更新完成", icon: "success" });
  } catch (e) {
    uni.hideLoading();
    uni.showToast({ title: "认知更新失败", icon: "none" });
    console.error(e);
  }
};

const deleteCurrentSession = () => {
  emit("delete-session");
};

// 好感度 SVG 图标映射
const affectionIcon = computed(() => {
  const s = personaStore.affectionScore;
  return s >= 50 ? '/static/icons/meta_heart.svg' : '/static/icons/meta_heart_broken.svg';
});

// 安卓端性能回退检查 (禁用毛玻璃效果)
let isAndroid = false;
// #ifdef APP-PLUS
isAndroid = uni.getSystemInfoSync().platform === "android";
// #endif
</script>

<style scoped>
/* ===== 状态属性右侧抽屉面板 ===== */
.status-panel-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(12px);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}

.status-panel {
  width: 82vw;
  max-width: 600rpx;
  height: 100%;
  background-color: #f8f8fa;
  display: flex;
  flex-direction: column;
  animation: slideInRight 0.35s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: -12px 0 48px rgba(0, 0, 0, 0.1);
}

@keyframes slideInRight {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

/* Panel header bar (close button only) */
.panel-header {
  padding-top: env(safe-area-inset-top, 40rpx);
  height: calc(env(safe-area-inset-top, 40rpx) + 80rpx);
  display: flex;
  justify-content: flex-end;
  align-items: flex-end;
  padding-right: 28rpx;
  padding-bottom: 12rpx;
  background-color: #f8f8fa;
}

.close-btn {
  width: 52rpx;
  height: 52rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.05);
  color: #8e8e93;
  transition: background-color 0.2s;
}

.close-btn:active {
  background-color: rgba(0, 0, 0, 0.1);
}

/* Scroll area */
.panel-content {
  flex: 1;
  height: 0;
  min-height: 0;
}

/* ===== ① 角色卡片展示 ===== */
.char-card {
  display: flex;
  align-items: center;
  gap: 24rpx;
  padding: 28rpx 32rpx 32rpx 32rpx;
  background: linear-gradient(135deg, #1c1c1e 0%, #3a3a3c 100%);
  margin: 0 20rpx 28rpx 20rpx;
  border-radius: 24rpx;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
}

.char-card-avatar {
  width: 100rpx;
  height: 100rpx;
  border-radius: 50%;
  border: 2.5px solid rgba(255, 255, 255, 0.25);
  flex-shrink: 0;
  background-color: rgba(255, 255, 255, 0.1);
}

.char-card-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10rpx;
}

.char-card-name {
  font-size: 30rpx;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: -0.3px;
}

.mood-badge {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  background-color: rgba(255, 255, 255, 0.12);
  border-radius: 40rpx;
  padding: 5rpx 16rpx;
  align-self: flex-start;
}

.mood-dot {
  width: 8rpx;
  height: 8rpx;
  border-radius: 50%;
  background-color: #34c759;
  flex-shrink: 0;
}

.mood-text {
  font-size: 20rpx;
  color: rgba(255, 255, 255, 0.85);
  font-weight: 500;
}

/* ===== 各设定区块通用 ===== */
.panel-section {
  margin: 0 20rpx 24rpx 20rpx;
  background-color: #ffffff;
  border-radius: 20rpx;
  padding: 24rpx;
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.03);
}

.section-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.section-title {
  font-size: 20rpx;
  font-weight: 700;
  color: #8e8e93;
  text-transform: uppercase;
  letter-spacing: 0.8px;
}

/* ===== ② 好感度进度条 ===== */
.affection-value-wrapper {
  display: flex;
  align-items: center;
  gap: 8rpx;
}

.affection-heart-icon-drawer {
  width: 28rpx;
  height: 28rpx;
  flex-shrink: 0;
}

.affection-value {
  font-size: 24rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.progress-bg {
  width: 100%;
  height: 14rpx;
  background-color: rgba(0, 0, 0, 0.05);
  border-radius: 7rpx;
  overflow: hidden;
}

.progress-bar-gradient {
  height: 100%;
  background: linear-gradient(90deg, #ff6b9d 0%, #ff8c69 60%, #ffd93d 100%);
  border-radius: 7rpx;
  transition: width 0.5s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 2px 6px rgba(255, 107, 157, 0.4);
}

/* ===== ③ 认知信息展示框 ===== */
.cognition-box {
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 12rpx;
  padding: 20rpx;
  min-height: 120rpx;
}

.cognition-text {
  font-size: 25rpx;
  color: #3a3a3c;
  line-height: 1.65;
}

/* ===== ④ 自定义开关组件 ===== */
.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4rpx 0;
}

.setting-row-left {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.setting-row-icon {
  width: 40rpx;
  height: 40rpx;
  color: #8e8e93;
}

.setting-row-label {
  font-size: 27rpx;
  font-weight: 500;
  color: #1c1c1e;
}

.drawer-nickname-input {
  font-size: 26rpx;
  color: #1c1c1e;
  text-align: right;
  width: 260rpx;
  height: 64rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 16rpx;
  padding: 0 20rpx;
  box-sizing: border-box;
}

.drawer-nickname-input:focus {
  background-color: #ffffff;
  border-color: rgba(0, 0, 0, 0.1);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.02);
}

.custom-toggle {
  width: 88rpx;
  height: 48rpx;
  border-radius: 24rpx;
  background-color: rgba(0, 0, 0, 0.1);
  position: relative;
  transition: background-color 0.25s ease;
  flex-shrink: 0;
  cursor: pointer;
}

.custom-toggle.is-on {
  background-color: #1c1c1e;
}

.toggle-thumb {
  position: absolute;
  top: 4rpx;
  left: 4rpx;
  width: 40rpx;
  height: 40rpx;
  border-radius: 50%;
  background-color: #ffffff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.custom-toggle.is-on .toggle-thumb {
  transform: translateX(40rpx);
}

/* ===== Drawer Sliders styles ===== */
.drawer-sliders-container {
  display: flex;
  flex-direction: column;
  gap: 24rpx;
  margin-top: 24rpx;
  padding: 20rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 16rpx;
}

.drawer-slider-row {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.drawer-slider-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.drawer-slider-label {
  font-size: 24rpx;
  font-weight: 500;
  color: #3a3a3c;
}

.drawer-slider-value-wrapper {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.drawer-slider-value {
  font-size: 22rpx;
  font-weight: 600;
  color: #1c1c1e;
  background-color: rgba(0, 0, 0, 0.04);
  padding: 2rpx 10rpx;
  border-radius: 12rpx;
}

.drawer-slider-value.is-default {
  color: #8e8e93;
  font-weight: 500;
  background-color: rgba(0, 0, 0, 0.02);
}

.drawer-slider-reset {
  font-size: 22rpx;
  font-weight: 500;
  color: #8e8e93;
  cursor: pointer;
  padding: 2rpx 8rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 8rpx;
  transition: all 0.2s;
}

.drawer-slider-reset:active {
  color: #1c1c1e;
  background-color: rgba(0, 0, 0, 0.08);
}

.advanced-chevron {
  width: 28rpx;
  height: 28rpx;
  opacity: 0.6;
  transition: transform 0.25s ease;
}

.advanced-chevron.is-active {
  transform: rotate(180deg);
}

.cursor-pointer {
  cursor: pointer;
}

.drawer-slider-component {
  margin: 0;
  width: 100%;
}

/* ===== ⑤ 功能操作按钮 ===== */
.action-btn {
  height: 80rpx;
  border-radius: 14rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10rpx;
  transition: all 0.2s;
  cursor: pointer;
}

.action-btn.outline {
  border: 1px solid rgba(0, 0, 0, 0.07);
  background-color: rgba(0, 0, 0, 0.02);
}

.action-btn.outline:active {
  background-color: rgba(0, 0, 0, 0.05);
  transform: scale(0.985);
}

.btn-icon {
  width: 32rpx;
  height: 32rpx;
  color: #3a3a3c;
}

.btn-text {
  font-size: 26rpx;
  font-weight: 500;
  color: #3a3a3c;
}

/* ===== ⑥ 危险操作区域 ===== */
.danger-section {
  background-color: rgba(255, 59, 48, 0.04);
  border: 1px solid rgba(255, 59, 48, 0.1);
}

.danger-title {
  color: #ff3b30 !important;
}

.danger-btn {
  background-color: rgba(255, 59, 48, 0.06);
  border: 1px solid rgba(255, 59, 48, 0.15);
}

.danger-btn:active {
  background-color: rgba(255, 59, 48, 0.12);
  transform: scale(0.985);
}

.danger-icon {
  width: 32rpx;
  height: 32rpx;
  color: #ff3b30;
}

.danger-btn-text {
  font-size: 26rpx;
  font-weight: 500;
  color: #ff3b30;
}

.close-icon {
  width: 36rpx;
  height: 36rpx;
}

/* Android Performance Fallbacks (Disable Frosted Glass) */
.is-android.status-panel-backdrop {
  backdrop-filter: none !important;
  background-color: rgba(0, 0, 0, 0.55) !important;
}
</style>
