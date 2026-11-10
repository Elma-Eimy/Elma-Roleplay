<template>
<view class="reading-setting">
            <view
              class="setting-row cursor-pointer reading-collapse-trigger"
              role="button"
              :aria-expanded="showReadingPrefs"
              @tap="showReadingPrefs = !showReadingPrefs"
            >
              <view class="setting-row-copy">
                <text class="setting-row-label">阅读偏好</text>
                <text class="setting-row-hint">本机全局保存</text>
              </view>
              <view class="reading-collapse-right">
                <text class="reading-collapse-summary">{{ readingPrefsSummary }}</text>
                <image
                  class="advanced-chevron"
                  :class="{ 'is-active': showReadingPrefs }"
                  src="/static/icons/settings_chevron.svg"
                  mode="aspectFit"
                />
              </view>
            </view>

            <view v-if="showReadingPrefs" class="reading-collapse-body">
              <view class="reading-row">
                <text class="reading-row-label">字号</text>
                <view class="reading-pills">
                  <view
                    v-for="item in FONT_SCALE_OPTIONS"
                    :key="item.value"
                    class="reading-pill"
                    :class="{ 'is-active': chatSettingsStore.readingPrefs.fontScale === item.value }"
                    @tap="chatSettingsStore.updateReadingPrefs({ fontScale: item.value })"
                  >{{ item.label }}</view>
                </view>
              </view>
              <view class="reading-row">
                <text class="reading-row-label">行距</text>
                <view class="reading-pills">
                  <view
                    v-for="item in LINE_SPACING_OPTIONS"
                    :key="item.value"
                    class="reading-pill"
                    :class="{ 'is-active': chatSettingsStore.readingPrefs.lineSpacing === item.value }"
                    @tap="chatSettingsStore.updateReadingPrefs({ lineSpacing: item.value })"
                  >{{ item.label }}</view>
                </view>
              </view>
              <view class="reading-row">
                <text class="reading-row-label">排版</text>
                <view class="reading-pills">
                  <view
                    v-for="item in BUBBLE_STYLE_OPTIONS"
                    :key="item.value"
                    class="reading-pill"
                    :class="{ 'is-active': chatSettingsStore.readingPrefs.bubbleStyle === item.value }"
                    @tap="chatSettingsStore.updateReadingPrefs({ bubbleStyle: item.value })"
                  >{{ item.label }}</view>
                </view>
              </view>
              <view class="reading-row">
                <text class="reading-row-label">色调</text>
                <view class="reading-pills">
                  <view
                    v-for="item in COLOR_THEME_OPTIONS"
                    :key="item.value"
                    class="reading-pill"
                    :class="{ 'is-active': chatSettingsStore.readingPrefs.colorTheme === item.value }"
                    @tap="chatSettingsStore.updateReadingPrefs({ colorTheme: item.value })"
                  >{{ item.label }}</view>
                </view>
              </view>
            </view>
          </view>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { useChatSettingsStore } from "@/store/chatSettingsStore";
import {
  FONT_SCALE_OPTIONS,
  LINE_SPACING_OPTIONS,
  BUBBLE_STYLE_OPTIONS,
  COLOR_THEME_OPTIONS,
} from "@/utils/chatDisplay";
const chatSettingsStore = useChatSettingsStore();
const showReadingPrefs = ref(false);
const readingPrefsSummary = computed(() => {
  const prefs = chatSettingsStore.readingPrefs;
  const fontLabel = FONT_SCALE_OPTIONS.find(i => i.value === prefs.fontScale)?.label || "标准";
  const spacingLabel = LINE_SPACING_OPTIONS.find(i => i.value === prefs.lineSpacing)?.label || "舒适";
  const styleLabel = BUBBLE_STYLE_OPTIONS.find(i => i.value === prefs.bubbleStyle)?.label || "气泡";
  const themeLabel = COLOR_THEME_OPTIONS.find(i => i.value === prefs.colorTheme)?.label || "跟随系统";
  return `${fontLabel} · ${spacingLabel} · ${styleLabel} · ${themeLabel}`;
});
</script>

<style scoped>
@import "./chatDrawer.css";
</style>
