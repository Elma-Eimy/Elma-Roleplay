<template>
  <view class="page-container">
    <!-- 自定义导航栏 -->
    <view class="nav-bar">
      <text class="nav-title">设置</text>
    </view>

    <scroll-view scroll-y class="settings-scroll">
      <view class="settings-list">

        <!-- 显示与交互设置组 -->
        <view class="setting-group">
          <text class="group-title">显示与交互</text>

          <view class="setting-item">
            <view class="setting-item-left">
              <image class="item-icon" style="width: 42rpx; height: 42rpx; flex-shrink: 0;" src="/static/icons/settings_font.svg" mode="aspectFit" />
              <view class="setting-info">
                <text class="setting-name">文字大小</text>
                <text class="setting-desc">调整整个应用内的字体显示大小</text>
              </view>
            </view>
            <view class="setting-action">
              <view class="stepper">
                <view class="step-btn" @tap="changeFontSize(-1)">-</view>
                <text class="step-value">{{ fontSize }}</text>
                <view class="step-btn" @tap="changeFontSize(1)">+</view>
              </view>
            </view>
          </view>
        </view>

        <!-- AI 引擎配置组 -->
        <view class="setting-group">
          <text class="group-title">AI 引擎参数</text>
          <text class="group-desc">以下参数实时影响后端对话生成与记忆检索行为，修改后点击保存生效。</text>

          <EngineSettingsCard
            :settings="engineSettings"
            :isLoading="isLoadingSettings"
            @save="saveEngineSettings"
          />
        </view>

        <!-- 数据源模式与连接认证配置组 -->
        <view class="setting-group">
          <text class="group-title">数据与连接</text>

          <view class="setting-item">
            <view class="setting-item-left">
              <image class="item-icon" style="width: 42rpx; height: 42rpx; flex-shrink: 0;" src="/static/icons/settings_database.svg" mode="aspectFit" />
              <view class="setting-info">
                <text class="setting-name">运行模式</text>
                <text class="setting-desc">当前系统的API data源模式</text>
              </view>
            </view>
            <view class="setting-action">
              <text class="status-tag" :class="{ 'is-mock': isMock }">
                {{ isMock ? 'Mock 模拟' : 'API 联调' }}
              </text>
            </view>
          </view>

          <view class="setting-item" @tap="openUrlModal">
            <view class="setting-item-left">
              <image class="item-icon" style="width: 42rpx; height: 42rpx; flex-shrink: 0;" src="/static/icons/settings_globe.svg" mode="aspectFit" />
              <view class="setting-info">
                <text class="setting-name">服务器连接地址</text>
                <text class="setting-desc">{{ currentBaseUrl }}</text>
              </view>
            </view>
            <view class="setting-action">
              <image class="chevron" src="/static/icons/settings_chevron.svg" mode="aspectFit" />
            </view>
          </view>

          <view class="setting-item" @tap="openKeyModal">
            <view class="setting-item-left">
              <image class="item-icon" style="width: 42rpx; height: 42rpx; flex-shrink: 0;" src="/static/icons/settings_key.svg" mode="aspectFit" />
              <view class="setting-info">
                <text class="setting-name">API 访问密钥</text>
                <text class="setting-desc">{{ apiKeyConfigured ? '已配置安全密钥' : '未配置密钥 (本地免密)' }}</text>
              </view>
            </view>
            <view class="setting-action">
              <image class="chevron" src="/static/icons/settings_chevron.svg" mode="aspectFit" />
            </view>
          </view>

          <view class="setting-item" @tap="goToLorebooks">
            <view class="setting-item-left">
              <image class="item-icon" style="width: 42rpx; height: 42rpx; flex-shrink: 0;" src="/static/icons/modal_book_gray.svg" mode="aspectFit" />
              <view class="setting-info">
                <text class="setting-name">独立世界书库</text>
                <text class="setting-desc">导入、编辑并管理公共世界书设定集</text>
              </view>
            </view>
            <view class="setting-action">
              <image class="chevron" src="/static/icons/settings_chevron.svg" mode="aspectFit" />
            </view>
          </view>

          <view class="setting-item" @tap="handleResetDatabase">
            <view class="setting-item-left">
              <image class="item-icon danger-icon" style="width: 42rpx; height: 42rpx; flex-shrink: 0;" src="/static/icons/drawer_trash.svg" mode="aspectFit" />
              <view class="setting-info">
                <text class="setting-name danger-text">重置本地数据库</text>
                <text class="setting-desc">清空并恢复默认的Mock角色及会话</text>
              </view>
            </view>
            <view class="setting-action">
              <image class="chevron" src="/static/icons/settings_chevron.svg" mode="aspectFit" />
            </view>
          </view>
        </view>

        <!-- 关于应用组 -->
        <view class="setting-group">
          <text class="group-title">关于</text>

          <view class="setting-item">
            <view class="setting-item-left">
              <image class="item-icon" style="width: 42rpx; height: 42rpx; flex-shrink: 0;" src="/static/icons/header_info.svg" mode="aspectFit" />
              <view class="setting-info">
                <text class="setting-name">应用版本</text>
                <text class="setting-desc">AI 角色扮演 Uni-app 客户端</text>
              </view>
            </view>
            <view class="setting-action">
              <text class="version-text">v1.1.0</text>
            </view>
          </view>
        </view>

      </view>
    </scroll-view>

    <!-- API 密钥配置模态框 -->
    <ApiKeyModal
      :isOpen="isKeyModalOpen"
      :value="apiKeyInput"
      @close="closeKeyModal"
      @save="saveApiKey"
    />

    <!-- API 连接地址配置模态框 -->
    <ServerUrlModal
      :isOpen="isUrlModalOpen"
      :value="currentBaseUrl"
      @close="closeUrlModal"
      @save="saveBaseUrl"
    />

    <!-- 自定义底部导航栏 -->
    <TabBar activeTab="settings" />
  </view>
</template>

<script setup lang="ts">
import { ref, reactive } from "vue";
import { onShow } from "@dcloudio/uni-app";
import TabBar from "@/components/common/TabBar.vue";
import { USE_MOCK, getSavedBaseUrl, setSavedBaseUrl, setSavedApiKey } from "@/api/config";
import { getSettings, updateSettings, DEFAULT_SETTINGS } from "@/api/settings";
import type { AppSettings } from "@/api/settings";

// 引入拆分的子组件
import EngineSettingsCard from "./EngineSettingsCard.vue";
import ApiKeyModal from "./ApiKeyModal.vue";
import ServerUrlModal from "./ServerUrlModal.vue";

const fontSize = ref(16);
const isMock = ref(USE_MOCK);
const isLoadingSettings = ref(false);

// 引擎设置的状态变量（从后端加载的响应式副本）
const engineSettings = reactive<AppSettings>({ ...DEFAULT_SETTINGS });

// 页面显示时从后端加载自定义引擎配置
onShow(async () => {
  uni.hideTabBar({ animation: false });
  if (USE_MOCK) return; // 如果处于 mock 模式则跳过 API 加载
  isLoadingSettings.value = true;
  try {
    const res = await getSettings();
    Object.assign(engineSettings, res);
  } catch (e) {
    console.error("Failed to load settings", e);
    uni.showToast({ title: '加载引擎配置失败', icon: 'none' });
  } finally {
    isLoadingSettings.value = false;
  }
});

// 保存自定义 AI 引擎配置到后端
const saveEngineSettings = async (updatedSettings: AppSettings) => {
  try {
    uni.showLoading({ title: '正在保存...' });
    await updateSettings({ ...updatedSettings });
    // 同步本地的 engineSettings 状态
    Object.assign(engineSettings, updatedSettings);
    uni.hideLoading();
    uni.showToast({ title: '引擎设置已保存', icon: 'success' });
  } catch (e) {
    uni.hideLoading();
    uni.showToast({ title: '保存失败，请检查连接', icon: 'none' });
    console.error("Failed to save settings", e);
  }
};

// API 访问密钥配置管理逻辑
const isKeyModalOpen = ref(false);
const apiKeyInput = ref("");
const apiKeyConfigured = ref(!!uni.getStorageSync("api_access_key"));

const openKeyModal = () => {
  apiKeyInput.value = uni.getStorageSync("api_access_key") || "";
  isKeyModalOpen.value = true;
};

const closeKeyModal = () => {
  isKeyModalOpen.value = false;
  apiKeyInput.value = "";
};

const saveApiKey = (val: string) => {
  try {
    uni.setStorageSync("api_access_key", val);
    setSavedApiKey(val); // 更新内存缓存
    apiKeyConfigured.value = !!val;
    uni.showToast({ title: "密钥保存成功", icon: "success" });
  } catch (e) {
    uni.showToast({ title: "保存失败", icon: "none" });
  } finally {
    closeKeyModal();
  }
};

// 服务器连接地址配置管理逻辑
const currentBaseUrl = ref(getSavedBaseUrl());
const isUrlModalOpen = ref(false);

const openUrlModal = () => {
  isUrlModalOpen.value = true;
};

const closeUrlModal = () => {
  isUrlModalOpen.value = false;
};

const saveBaseUrl = (url: string) => {
  try {
    setSavedBaseUrl(url);
    currentBaseUrl.value = url;
    uni.showToast({ title: "连接地址保存成功", icon: "success" });
  } catch (e) {
    uni.showToast({ title: "保存失败", icon: "none" });
  } finally {
    closeUrlModal();
  }
};

const changeFontSize = (delta: number) => {
  const newSize = fontSize.value + delta;
  if (newSize >= 12 && newSize <= 24) {
    fontSize.value = newSize;
  }
};

const handleResetDatabase = () => {
  uni.showModal({
    title: "重置本地数据",
    content: "确定要重置本地数据库吗？所有新创建的角色和会话记录将被清空，并恢复为初始默认示例数据。",
    confirmColor: "#ff3b30",
    cancelColor: "#8e8e93",
    success: (res) => {
      if (res.confirm) {
        try {
          uni.removeStorageSync("ai_roleplay_mock_db");
          uni.showToast({ title: "重置成功", icon: "success", duration: 1500 });
        } catch (e) {
          uni.showToast({ title: "重置失败", icon: "none" });
        }
      }
    }
  });
};

const goToLorebooks = () => {
  uni.navigateTo({
    url: "/pages/settings/lorebooks/index"
  });
};
</script>

<style scoped src="./index.css"></style>
