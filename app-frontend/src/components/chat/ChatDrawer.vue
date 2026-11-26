<template>
  <!-- 聊天右侧共享抽屉骨架 -->
  <view v-if="isOpen" class="status-panel-backdrop" :class="{ 'is-android': isAndroid }" @tap="emit('close')">
    <view class="status-panel" @tap.stop>

      <view class="panel-header">
        <view class="close-btn" @tap="emit('close')">
          <image class="close-icon" src="/static/icons/drawer_close.svg" mode="aspectFit" />
        </view>
      </view>

      <scroll-view scroll-y class="panel-content">
        <slot name="top" />

        <!-- ① 角色卡片面板 -->
        <view class="char-card" @tap="openCharacterProfile">
          <button
            class="char-card-avatar-link"
            :aria-label="`查看${drawerName}的人物档案`"
            :disabled="!drawerCharacter?.id || isOpeningProfile"
            @tap.stop="openCharacterProfile"
          >
            <AvatarImage
              class="char-card-avatar"
              :src="getAvatarUrl(drawerCharacter?.avatar_path || '')"
              :lazy-load="false"
            />
          </button>
          <view class="char-card-info">
            <view class="char-card-name-row">
              <text class="char-card-name">{{ drawerName }}</text>
              <text v-if="drawerCharacter?.id" class="char-card-profile-hint">档案 ›</text>
            </view>
            <view class="mood-badge">
              <view class="mood-dot"></view>
              <text class="mood-text">{{ drawerMood || '在线' }}</text>
            </view>
          </view>
        </view>

        <!-- ② 好感度数值与进度条 -->
        <view class="panel-section">
          <AffectionMeter :score="drawerAffection" />
        </view>

        <slot name="role-state" />
        <slot name="portraits" />

        <!-- ③ 微观认知状态显示区 -->
        <view class="panel-section">
          <view
            class="section-collapse-header cursor-pointer"
            role="button"
            :aria-expanded="showCognition"
            @tap="showCognition = !showCognition"
          >
            <text class="section-title">微观认知</text>
            <view class="section-collapse-right">
              <text v-if="!showCognition" class="section-collapse-summary">{{ (drawerCognition || '暂无认知记录').slice(0, 14) }}{{ (drawerCognition || '').length > 14 ? '…' : '' }}</text>
              <image
                class="advanced-chevron"
                :class="{ 'is-active': showCognition }"
                src="/static/icons/settings_chevron.svg"
                mode="aspectFit"
              />
            </view>
          </view>
          <view v-if="showCognition" class="cognition-box">
            <text class="cognition-text">{{ drawerCognition || '暂无认知记录。' }}</text>
          </view>
        </view>

        <slot name="after-cognition" />
        <slot name="before-settings" />

        <!-- ④ 共享对话设置 -->
        <slot name="settings">
          <view class="panel-section">
            <text class="section-title">对话设置</text>
            <text class="generation-scope">模型选择仅用于当前故事，在本机保存。</text>
            <text v-if="chatSettingsStore.isLoadingModels" class="generation-scope">正在加载模型配置…</text>
            <text v-if="chatSettingsStore.settingsError" class="generation-scope">{{ chatSettingsStore.settingsError }}</text>
            <GenerationPicker
              v-if="!chatSettingsStore.isLoadingModels && chatSettingsStore.modelId"
              v-model:model="chatSettingsStore.modelId"
              v-model:thinkingMode="chatSettingsStore.thinkingMode"
              v-model:effort="chatSettingsStore.reasoningEffort"
              :catalog="chatSettingsStore.catalog"
              :default-model="chatSettingsStore.defaults.default_chat_model"
              :default-thinking="chatSettingsStore.defaults.chat_thinking_mode === 'enabled'"
              :default-effort="chatSettingsStore.defaults.reasoning_effort"
            />
            <slot name="model-meta" />
            <ChatReadingPreferences />

            <view class="background-setting">
              <view class="background-setting-header">
                <text class="setting-row-label">聊天背景</text>
                <text class="background-setting-hint">仅此会话 · 本机保存</text>
              </view>
              <view class="background-mode-picker">
                <view
                  class="background-mode-option"
                  :class="{ 'is-active': backgroundMode === 'clean' }"
                  @tap="emit('update:background-mode', 'clean')"
                >
                  <view class="background-mode-preview preview-clean"></view>
                  <text class="background-mode-label">纯净背景</text>
                </view>
                <view
                  class="background-mode-option"
                  :class="{ 'is-active': backgroundMode === 'character' }"
                  @tap="emit('update:background-mode', 'character')"
                >
                  <view class="background-mode-preview preview-character">
                    <AvatarImage
                      class="background-mode-avatar"
                      :src="backgroundAvatarUrl || getAvatarUrl(drawerCharacter?.avatar_path || '')"
                      :lazy-load="false"
                    />
                  </view>
                  <text class="background-mode-label">角色立绘</text>
                </view>
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

            <SamplingParamsPanel v-if="showAdvancedParams" />
          </view>
        </slot>

        <slot name="after-settings" />

        <!-- ⑤ 记忆管理入口 -->
        <view class="panel-section">
          <text class="section-title">记忆管理</text>
          <view class="action-btn outline" @tap="emit('open-memory-view')">
            <image class="btn-icon" src="/static/icons/settings_database.svg" mode="aspectFit" />
            <text class="btn-text">查看向量记忆库</text>
          </view>
          <slot name="memory-extra" />
        </view>

        <!-- 调试工具区域 -->
        <view class="panel-section">
          <text class="section-title">系统调试</text>
          <view class="action-btn outline" @tap="emit('open-prompt-preview')">
            <image class="btn-icon" src="/static/icons/chat_sparkle.svg" mode="aspectFit" />
            <text class="btn-text">查看当前 Prompt 组装</text>
          </view>
        </view>

        <slot name="extra-tools" />

        <!-- ⑥ 危险操作区域（删除会话） -->
        <view v-if="!hideDelete" class="panel-section danger-section">
          <text class="section-title danger-title">危险操作</text>
          <view class="action-btn danger-btn" @tap="emit('delete-session')">
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
import { useChatSettingsStore } from "@/store/chatSettingsStore";
import { getBaseUrl } from "@/api/config";
import { getAvatarUrl } from "@/api/characters";
import GenerationPicker from "./GenerationPicker.vue";
import AffectionMeter from "./AffectionMeter.vue";
import AvatarImage from "@/components/common/AvatarImage.vue";
import ChatReadingPreferences from "./ChatReadingPreferences.vue";
import SamplingParamsPanel from "./SamplingParamsPanel.vue";

export interface ChatDrawerProfile {
  name: string;
  character?: { id: number; avatar_path?: string | null } | null;
  affection: number | null;
  mood: string | null;
  cognition: string | null;
  loading?: boolean;
}

const props = defineProps<{
  isOpen: boolean;
  sessionId: number | null;
  backgroundMode: "clean" | "character";
  hideDelete?: boolean;
  profile?: ChatDrawerProfile;
  backgroundAvatarUrl?: string;
}>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "delete-session"): void;
  (e: "open-memory-view"): void;
  (e: "open-prompt-preview"): void;
  (e: "update:background-mode", mode: "clean" | "character"): void;
}>();

const chatSettingsStore = useChatSettingsStore();
const isOpeningProfile = ref(false);
const drawerName = computed(() => props.profile?.name ?? "未选角色");
const drawerCharacter = computed(() => props.profile?.character ?? null);
const drawerMood = computed(() => props.profile?.mood ?? null);
const drawerAffection = computed(() => props.profile?.affection ?? null);
const drawerCognition = computed(() => props.profile?.cognition ?? null);

let profileVersion = 0;
watch(() => [props.isOpen, props.sessionId, drawerCharacter.value?.id], () => {
  profileVersion++;
  isOpeningProfile.value = false;
}, { flush: "sync" });

const openCharacterProfile = () => {
  const characterId = drawerCharacter.value?.id;
  if (!characterId || props.profile?.loading || isOpeningProfile.value) return;
  const version = ++profileVersion;
  const server = getBaseUrl();
  const valid = () => version === profileVersion && props.isOpen && getBaseUrl() === server;
  isOpeningProfile.value = true;
  uni.navigateTo({
    url: `/pages/character/detail?id=${characterId}`,
    success: () => { if (valid()) emit("close"); },
    fail: () => { if (valid()) uni.showToast({ title: "无法打开人物档案，请重试", icon: "none" }); },
    complete: () => { if (valid()) isOpeningProfile.value = false; },
  });
};

const showAdvancedParams = ref(false);
const showCognition = ref(true);

let isAndroid = false;
// #ifdef APP-PLUS
isAndroid = uni.getSystemInfoSync().platform === "android";
// #endif
</script>

<style scoped>
@import "./chatDrawer.css";
</style>
