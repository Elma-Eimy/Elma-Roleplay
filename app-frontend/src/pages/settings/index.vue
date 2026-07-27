<template>
  <view class="page-container app-motion-enter">
    <!-- 自定义导航栏 -->
    <view class="nav-bar">
      <text class="nav-title">设置</text>
    </view>

    <scroll-view scroll-y class="settings-scroll">
      <view class="settings-list">
        <view class="settings-hero">
          <text class="hero-eyebrow">APP PREFERENCES</text>
          <text class="hero-title">让故事按你的方式运行</text>
          <text class="hero-description">从分类入口调整体验。主页面只保留当前状态，需要时再展开具体参数。</text>
          <view class="hero-status-row">
            <view class="hero-status">
              <view class="status-dot" :class="{ 'is-mock': isMock }"></view>
              <text>{{ isMock ? 'Mock 模式' : 'API 已连接' }}</text>
            </view>
            <view class="hero-status">
              <view class="status-dot" :class="{ 'is-ready': apiKeyConfigured || isMock }"></view>
              <text>{{ apiKeyConfigured ? '密钥已配置' : (isMock ? '本地免密' : '密钥未配置') }}</text>
            </view>
          </view>
        </view>

        <view class="category-grid">
          <view class="category-card" :class="{ 'is-active': activeCategory === 'appearance' }" @tap="toggleCategory('appearance')">
            <view class="category-icon-wrap mint">
              <image class="category-icon" src="/static/icons/settings_font.svg" mode="aspectFit" />
            </view>
            <text class="category-name">外观与沉浸</text>
            <text class="category-status">文字 {{ fontSize }}px</text>
          </view>

          <view class="category-card" :class="{ 'is-active': activeCategory === 'engine' }" @tap="toggleCategory('engine')">
            <view class="category-icon-wrap blue">
              <image class="category-icon" src="/static/icons/settings_database.svg" mode="aspectFit" />
            </view>
            <text class="category-name">模型与生成</text>
            <text class="category-status">温度 {{ engineSettings.temperature.toFixed(1) }}</text>
          </view>

          <view class="category-card" :class="{ 'is-active': activeCategory === 'memory' }" @tap="toggleCategory('memory')">
            <view class="category-icon-wrap gold">
              <image class="category-icon" src="/static/icons/modal_book_gray.svg" mode="aspectFit" />
            </view>
            <text class="category-name">记忆与世界</text>
            <text class="category-status">管理世界书库</text>
          </view>

          <view class="category-card" :class="{ 'is-active': activeCategory === 'connection' }" @tap="toggleCategory('connection')">
            <view class="category-icon-wrap lilac">
              <image class="category-icon" src="/static/icons/settings_globe.svg" mode="aspectFit" />
            </view>
            <text class="category-name">连接与安全</text>
            <text class="category-status">{{ isMock ? 'Mock 模拟' : 'API 联调' }}</text>
          </view>

          <view class="category-card category-card-wide" :class="{ 'is-active': activeCategory === 'data' }" @tap="toggleCategory('data')">
            <view class="category-icon-wrap neutral">
              <image class="category-icon" src="/static/icons/drawer_trash.svg" mode="aspectFit" />
            </view>
            <view class="category-wide-copy">
              <text class="category-name">数据管理</text>
              <text class="category-status">本地 Mock 数据与恢复操作</text>
            </view>
            <image class="category-chevron" src="/static/icons/settings_chevron.svg" mode="aspectFit" />
          </view>
        </view>

        <view v-show="activeCategory" class="category-detail">
          <view class="detail-header">
            <view class="detail-heading-copy">
              <text class="detail-eyebrow">当前分类</text>
              <text class="detail-title">{{ activeCategoryTitle }}</text>
            </view>
            <view class="detail-close" @tap="activeCategory = null">×</view>
          </view>

          <view v-show="activeCategory === 'appearance'" class="setting-group">
            <view class="setting-item">
              <view class="setting-item-left">
                <image class="item-icon" src="/static/icons/settings_font.svg" mode="aspectFit" />
                <view class="setting-info">
                  <text class="setting-name">文字大小</text>
                  <text class="setting-desc">调整整个应用内的字体显示大小</text>
                </view>
              </view>
              <view class="setting-action">
                <view class="stepper">
                  <view class="step-btn" @tap="changeFontSize(-1)">−</view>
                  <text class="step-value">{{ fontSize }}</text>
                  <view class="step-btn" @tap="changeFontSize(1)">＋</view>
                </view>
              </view>
            </view>
          </view>

          <view v-show="activeCategory === 'engine'" class="setting-group">
            <text class="group-desc">参数会影响对话生成与记忆检索，修改后请在本区底部保存。</text>
            <EngineSettingsCard
              :settings="engineSettings"
              :isLoading="isLoadingSettings"
              @save="saveEngineSettings"
            />
          </view>

          <view v-show="activeCategory === 'memory'" class="setting-group">
            <view class="setting-item" @tap="goToLorebooks">
              <view class="setting-item-left">
                <image class="item-icon" src="/static/icons/modal_book_gray.svg" mode="aspectFit" />
                <view class="setting-info">
                  <text class="setting-name">独立世界书库</text>
                  <text class="setting-desc">导入、编辑并管理公共世界设定集</text>
                </view>
              </view>
              <image class="chevron" src="/static/icons/settings_chevron.svg" mode="aspectFit" />
            </view>
          </view>

          <view v-show="activeCategory === 'connection'" class="setting-group">
            <AppStatusState
              v-if="isOffline"
              kind="offline"
              title="当前处于离线状态"
              description="本地内容仍可使用，恢复网络后再连接服务器。"
              action-label="重新检查"
              compact
              @action="refreshNetworkStatus"
            />
            <view class="setting-item">
              <view class="setting-item-left">
                <image class="item-icon" src="/static/icons/settings_database.svg" mode="aspectFit" />
                <view class="setting-info">
                  <text class="setting-name">运行模式</text>
                  <text class="setting-desc">当前应用使用的数据来源</text>
                </view>
              </view>
              <text class="status-tag" :class="{ 'is-mock': isMock }">{{ isMock ? 'Mock 模拟' : 'API 联调' }}</text>
            </view>
            <view class="setting-item" @tap="openUrlModal">
              <view class="setting-item-left">
                <image class="item-icon" src="/static/icons/settings_globe.svg" mode="aspectFit" />
                <view class="setting-info">
                  <text class="setting-name">服务器连接地址</text>
                  <text class="setting-desc">{{ currentBaseUrl }}</text>
                </view>
              </view>
              <image class="chevron" src="/static/icons/settings_chevron.svg" mode="aspectFit" />
            </view>
            <view class="setting-item" @tap="openKeyModal">
              <view class="setting-item-left">
                <image class="item-icon" src="/static/icons/settings_key.svg" mode="aspectFit" />
                <view class="setting-info">
                  <text class="setting-name">API 访问密钥</text>
                  <text class="setting-desc">{{ apiKeyConfigured ? '已配置安全密钥' : '未配置密钥（本地免密）' }}</text>
                </view>
              </view>
              <image class="chevron" src="/static/icons/settings_chevron.svg" mode="aspectFit" />
            </view>
          </view>

          <view v-show="activeCategory === 'data'" class="danger-zone">
            <text class="danger-zone-label">危险操作</text>
            <view class="setting-item danger-item" @tap="handleResetDatabase">
              <view class="setting-item-left">
                <image class="item-icon danger-icon" src="/static/icons/drawer_trash.svg" mode="aspectFit" />
                <view class="setting-info">
                  <text class="setting-name danger-text">重置本地数据库</text>
                  <text class="setting-desc">清空新建角色与会话，并恢复默认 Mock 数据</text>
                </view>
              </view>
              <image class="chevron" src="/static/icons/settings_chevron.svg" mode="aspectFit" />
            </view>
          </view>
        </view>

        <view class="about-card">
          <view class="about-copy">
            <text class="about-title">AI 角色扮演</text>
            <text class="about-description">测试中ing</text>
          </view>
          <text class="version-text">v1.1.0</text>
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
import { ref, reactive, computed, onUnmounted } from "vue";
import { onShow } from "@dcloudio/uni-app";
import TabBar from "@/components/common/TabBar.vue";
import { USE_MOCK, getSavedBaseUrl, setSavedBaseUrl, setSavedApiKey } from "@/api/config";
import { getSettings, updateSettings, DEFAULT_SETTINGS } from "@/api/settings";
import type { AppSettings } from "@/api/settings";

// 引入拆分的子组件
import EngineSettingsCard from "./EngineSettingsCard.vue";
import ApiKeyModal from "./ApiKeyModal.vue";
import ServerUrlModal from "./ServerUrlModal.vue";
import AppStatusState from "@/components/common/AppStatusState.vue";

const fontSize = ref(16);
const isMock = ref(USE_MOCK);
const isLoadingSettings = ref(false);
const isOffline = ref(false);
type SettingsCategory = "appearance" | "engine" | "memory" | "connection" | "data";
const activeCategory = ref<SettingsCategory | null>(null);

const categoryTitles: Record<SettingsCategory, string> = {
  appearance: "外观与沉浸",
  engine: "模型与生成",
  memory: "记忆与世界",
  connection: "连接与安全",
  data: "数据管理",
};

const activeCategoryTitle = computed(() => (
  activeCategory.value ? categoryTitles[activeCategory.value] : ""
));

const toggleCategory = (category: SettingsCategory) => {
  activeCategory.value = activeCategory.value === category ? null : category;
};

const refreshNetworkStatus = () => {
  uni.getNetworkType({
    success: (result) => {
      isOffline.value = result.networkType === "none";
    },
  });
};

const handleNetworkStatusChange = (result: UniApp.OnNetworkStatusChangeSuccess) => {
  isOffline.value = !result.isConnected;
};

refreshNetworkStatus();
uni.onNetworkStatusChange(handleNetworkStatusChange);
onUnmounted(() => {
  uni.offNetworkStatusChange(handleNetworkStatusChange);
});

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
