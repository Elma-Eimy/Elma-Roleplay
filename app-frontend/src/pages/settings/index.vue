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
              <text class="item-icon-fallback">🔤</text>
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

          <!-- 加载配置时的 Loading 卡片 -->
          <view v-if="isLoadingSettings" class="loading-card">
            <text class="loading-text">正在加载引擎配置...</text>
          </view>

          <view v-else class="engine-card">

            <!-- 推理模式开关行 -->
            <view class="engine-row border-bottom">
              <view class="engine-row-left">
                <text class="engine-param-name">默认推理模式</text>
                <text class="engine-param-desc">全局默认是否使用深度思考模型（聊天页的切换优先级更高）</text>
              </view>
              <view
                class="custom-toggle"
                :class="{ 'is-on': engineSettings.reasoning_mode }"
                @tap="engineSettings.reasoning_mode = !engineSettings.reasoning_mode"
              >
                <view class="toggle-thumb"></view>
              </view>
            </view>

            <!-- 温度参数滑块行 -->
            <view class="engine-row border-bottom">
              <view class="engine-row-left">
                <view class="engine-name-row">
                  <text class="engine-param-name">创意温度 (Temperature)</text>
                  <text class="engine-param-val">{{ engineSettings.temperature.toFixed(1) }}</text>
                </view>
                <text class="engine-param-desc">控制回复的随机性。值越高越有创意，越低越保守精确（范围 0.1 ~ 2.0）</text>
              </view>
              <slider
                class="engine-slider"
                :value="Math.round(engineSettings.temperature * 10)"
                :min="1" :max="20" :step="1"
                activeColor="#1c1c1e"
                backgroundColor="rgba(0,0,0,0.07)"
                block-color="#ffffff"
                block-size="20"
                @change="(e: any) => engineSettings.temperature = e.detail.value / 10"
              />
            </view>

            <!-- 上下文历史消息数步进器行 -->
            <view class="engine-row border-bottom">
              <view class="engine-row-left">
                <text class="engine-param-name">上下文消息数</text>
                <text class="engine-param-desc">每次请求携带的历史消息条数（范围 5 ~ 100）</text>
              </view>
              <view class="stepper">
                <view class="step-btn" @tap="stepInt('context_history_limit', -5, 5, 100)">-</view>
                <text class="step-value">{{ engineSettings.context_history_limit }}</text>
                <view class="step-btn" @tap="stepInt('context_history_limit', 5, 5, 100)">+</view>
              </view>
            </view>

            <!-- 记忆库检索上限步进器行 -->
            <view class="engine-row border-bottom">
              <view class="engine-row-left">
                <text class="engine-param-name">检索记忆数量</text>
                <text class="engine-param-desc">每次对话从记忆库中检索的最大条目数（范围 1 ~ 20）</text>
              </view>
              <view class="stepper">
                <view class="step-btn" @tap="stepInt('retrieval_top_k', -1, 1, 20)">-</view>
                <text class="step-value">{{ engineSettings.retrieval_top_k }}</text>
                <view class="step-btn" @tap="stepInt('retrieval_top_k', 1, 1, 20)">+</view>
              </view>
            </view>

            <!-- 高级设置折叠切换行 -->
            <view class="advanced-toggle-row" @tap="showAdvanced = !showAdvanced">
              <view class="advanced-toggle-btn">
                <text class="advanced-toggle-text">{{ showAdvanced ? '收起高级参数' : '展开高级参数' }}</text>
                <text class="advanced-toggle-subtext" v-if="!showAdvanced">（包括重要度、世界书、Token限制等 9 项）</text>
                <image 
                  class="advanced-chevron" 
                  :class="{ 'is-active': showAdvanced }" 
                  src="/static/icons/settings_chevron.svg" 
                  mode="aspectFit" 
                />
              </view>
            </view>

            <!-- 高级参数折叠部分 -->
            <view class="advanced-section" :class="{ 'is-show': showAdvanced }">
              <!-- 记忆过滤最低重要度滑块行 -->
              <view class="engine-row border-bottom">
                <view class="engine-row-left">
                  <view class="engine-name-row">
                    <text class="engine-param-name">记忆最低重要度</text>
                    <text class="engine-param-val">{{ engineSettings.retrieval_min_importance.toFixed(2) }}</text>
                  </view>
                  <text class="engine-param-desc">低于此阈值的记忆将被过滤（范围 0.00 ~ 1.00）</text>
                </view>
                <slider
                  class="engine-slider"
                  :value="Math.round(engineSettings.retrieval_min_importance * 100)"
                  :min="0" :max="100" :step="5"
                  activeColor="#1c1c1e"
                  backgroundColor="rgba(0,0,0,0.07)"
                  block-color="#ffffff"
                  block-size="20"
                  @change="(e: any) => engineSettings.retrieval_min_importance = e.detail.value / 100"
                />
              </view>

              <!-- 记忆检索最大容忍距离滑块行 -->
              <view class="engine-row border-bottom">
                <view class="engine-row-left">
                  <view class="engine-name-row">
                    <text class="engine-param-name">记忆最大向量距离</text>
                    <text class="engine-param-val">{{ engineSettings.retrieval_max_distance.toFixed(1) }}</text>
                  </view>
                  <text class="engine-param-desc">向量相似度的最大容忍距离，越小越严格（范围 0.5 ~ 3.0）</text>
                </view>
                <slider
                  class="engine-slider"
                  :value="Math.round(engineSettings.retrieval_max_distance * 10)"
                  :min="5" :max="30" :step="1"
                  activeColor="#1c1c1e"
                  backgroundColor="rgba(0,0,0,0.07)"
                  block-color="#ffffff"
                  block-size="20"
                  @change="(e: any) => engineSettings.retrieval_max_distance = e.detail.value / 10"
                />
              </view>

              <!-- 世界书历史扫描深度步进器行 -->
              <view class="engine-row border-bottom">
                <view class="engine-row-left">
                  <text class="engine-param-name">世界书扫描深度</text>
                  <text class="engine-param-desc">世界书扫描的对话历史消息条数（范围 1 ~ 20）</text>
                </view>
                <view class="stepper">
                  <view class="step-btn" @tap="stepInt('lorebook_scan_depth', -1, 1, 20)">-</view>
                  <text class="step-value">{{ engineSettings.lorebook_scan_depth }}</text>
                  <view class="step-btn" @tap="stepInt('lorebook_scan_depth', 1, 1, 20)">+</view>
                </view>
              </view>

              <!-- 世界书 Token 预算上限步进器行 -->
              <view class="engine-row border-bottom">
                <view class="engine-row-left">
                  <text class="engine-param-name">世界书 Token 预算</text>
                  <text class="engine-param-desc">世界书条目注入的最大 Token 数（范围 500 ~ 10000）</text>
                </view>
                <view class="stepper">
                  <view class="step-btn" @tap="stepInt('lorebook_token_budget', -500, 500, 10000)">-</view>
                  <text class="step-value">{{ engineSettings.lorebook_token_budget }}</text>
                  <view class="step-btn" @tap="stepInt('lorebook_token_budget', 500, 500, 10000)">+</view>
                </view>
              </view>

              <!-- 世界书最大递归级联次数行 -->
              <view class="engine-row border-bottom">
                <view class="engine-row-left">
                  <text class="engine-param-name">世界书递归扫描次数</text>
                  <text class="engine-param-desc">触发级联条目时的最大递归层数（范围 1 ~ 10）</text>
                </view>
                <view class="stepper">
                  <view class="step-btn" @tap="stepInt('lorebook_max_recursive_passes', -1, 1, 10)">-</view>
                  <text class="step-value">{{ engineSettings.lorebook_max_recursive_passes }}</text>
                  <view class="step-btn" @tap="stepInt('lorebook_max_recursive_passes', 1, 1, 10)">+</view>
                </view>
              </view>

              <!-- 认知摘要最大字数上限行 -->
              <view class="engine-row border-bottom">
                <view class="engine-row-left">
                  <text class="engine-param-name">认知摘要最大字数</text>
                  <text class="engine-param-desc">角色微观认知状态摘要的字数上限（范围 50 ~ 500）</text>
                </view>
                <view class="stepper">
                  <view class="step-btn" @tap="stepInt('cognition_max_words', -50, 50, 500)">-</view>
                  <text class="step-value">{{ engineSettings.cognition_max_words }}</text>
                  <view class="step-btn" @tap="stepInt('cognition_max_words', 50, 50, 500)">+</view>
                </view>
              </view>

              <!-- 最大输出 Token 数行 -->
              <view class="engine-row border-bottom">
                <view class="engine-row-left">
                  <text class="engine-param-name">最大输出 Token 数</text>
                  <text class="engine-param-desc">单次模型生成的最大 Token 上限（范围 256 ~ 16384）</text>
                </view>
                <view class="stepper">
                  <view class="step-btn" @tap="stepInt('max_tokens', -256, 256, 16384)">-</view>
                  <text class="step-value">{{ engineSettings.max_tokens }}</text>
                  <view class="step-btn" @tap="stepInt('max_tokens', 256, 256, 16384)">+</view>
                </view>
              </view>

              <!-- 时间衰减半衰期行 -->
              <view class="engine-row border-bottom">
                <view class="engine-row-left">
                  <text class="engine-param-name">记忆半衰期 (轮数)</text>
                  <text class="engine-param-desc">记忆随对话轮数增加而衰减的半衰期时间（范围 5 ~ 500）</text>
                </view>
                <view class="stepper">
                  <view class="step-btn" @tap="stepInt('retrieval_half_life_turns', -5, 5, 500)">-</view>
                  <text class="step-value">{{ engineSettings.retrieval_half_life_turns }}</text>
                  <view class="step-btn" @tap="stepInt('retrieval_half_life_turns', 5, 5, 500)">+</view>
                </view>
              </view>

              <!-- 检索候选池放大倍数行 -->
              <view class="engine-row">
                <view class="engine-row-left">
                  <text class="engine-param-name">检索候选池放大倍数</text>
                  <text class="engine-param-desc">最终提取数量乘以该倍数作为初始检索候选池（范围 1 ~ 20）</text>
                </view>
                <view class="stepper">
                  <view class="step-btn" @tap="stepInt('retrieval_candidate_multiplier', -1, 1, 20)">-</view>
                  <text class="step-value">{{ engineSettings.retrieval_candidate_multiplier }}</text>
                  <view class="step-btn" @tap="stepInt('retrieval_candidate_multiplier', 1, 1, 20)">+</view>
                </view>
              </view>
            </view>

          </view>

          <!-- 引擎参数保存按钮 -->
          <view class="save-engine-btn" @tap="saveEngineSettings" v-if="!isLoadingSettings">
            <text class="save-engine-text">保存引擎设置</text>
          </view>
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
    <view v-if="isKeyModalOpen" class="modal-backdrop">
      <view class="edit-modal">
        <text class="modal-title">API 访问密钥配置</text>
        <text class="modal-desc">当后端开启 ACCESS_API_KEY 访问控制时，请在此配置匹配的 X-API-Key 密钥。</text>
        <input
          class="key-input"
          v-model="apiKeyInput"
          placeholder="请输入密钥..."
          password
        />
        <view class="modal-actions">
          <view class="modal-btn cancel" @tap="closeKeyModal">取消</view>
          <view class="modal-btn save" @tap="saveApiKey">保存</view>
        </view>
      </view>
    </view>

    <!-- API 连接地址配置模态框 -->
    <view v-if="isUrlModalOpen" class="modal-backdrop">
      <view class="edit-modal">
        <text class="modal-title">服务器连接地址配置</text>
        <text class="modal-desc">请在此输入后端服务器的 API 访问地址（例如：http://127.0.0.1:8000）。修改后会实时生效并保存于本地缓存中。</text>
        <input
          class="key-input"
          v-model="baseUrlInput"
          placeholder="例如：http://127.0.0.1:8000"
          confirm-type="done"
          @confirm="saveBaseUrl"
        />
        <view class="modal-actions">
          <view class="modal-btn cancel" @tap="closeUrlModal">取消</view>
          <view class="modal-btn save" @tap="saveBaseUrl">保存</view>
        </view>
      </view>
    </view>

    <!-- 自定义底部导航栏 -->
    <TabBar activeTab="settings" />
  </view>
</template>

<script setup lang="ts">
import { ref, reactive } from "vue";
import { onShow } from "@dcloudio/uni-app";
import TabBar from "@/components/common/TabBar.vue";
import { USE_MOCK, getSavedBaseUrl, setSavedBaseUrl } from "@/api/config";
import { getSettings, updateSettings, DEFAULT_SETTINGS } from "@/api/settings";
import type { AppSettings } from "@/api/settings";

const fontSize = ref(16);
const isMock = ref(USE_MOCK);
const isLoadingSettings = ref(false);
const showAdvanced = ref(false);

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

// 整数类型字段的步进器助手函数，包含边界控制与步长
const stepInt = (
  key: keyof AppSettings,
  delta: number,
  min: number,
  max: number
) => {
  const cur = engineSettings[key] as number;
  const next = cur + delta;
  if (next >= min && next <= max) {
    (engineSettings as any)[key] = next;
  }
};

// 保存自定义 AI 引擎配置到后端
const saveEngineSettings = async () => {
  try {
    uni.showLoading({ title: '正在保存...' });
    await updateSettings({ ...engineSettings });
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

const saveApiKey = () => {
  try {
    uni.setStorageSync("api_access_key", apiKeyInput.value.trim());
    apiKeyConfigured.value = !!apiKeyInput.value.trim();
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
const baseUrlInput = ref("");

const openUrlModal = () => {
  baseUrlInput.value = currentBaseUrl.value;
  isUrlModalOpen.value = true;
};

const closeUrlModal = () => {
  isUrlModalOpen.value = false;
  baseUrlInput.value = "";
};

const saveBaseUrl = () => {
  let url = baseUrlInput.value.trim();
  if (!url) {
    uni.showToast({ title: "连接地址不能为空", icon: "none" });
    return;
  }
  // 如果输入没有 http:// 或 https://，自动补齐
  if (!/^https?:\/\//i.test(url)) {
    url = "http://" + url;
  }
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
</script>

<style scoped>
.page-container {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100%;
  background-color: #fafafa;
}

/* ===== Custom Nav Bar ===== */
.nav-bar {
  padding-top: env(safe-area-inset-top, 40rpx);
  height: calc(env(safe-area-inset-top, 40rpx) + 110rpx);
  padding-left: 36rpx;
  padding-right: 36rpx;
  display: flex;
  align-items: center;
  background-color: #ffffff;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  z-index: 50;
}

.nav-title {
  font-size: 34rpx;
  font-weight: 600;
  color: #1c1c1e;
  letter-spacing: -0.5px;
}

/* ===== Settings List ===== */
.settings-scroll {
  flex: 1;
  height: 0;
  min-height: 0;
}

.settings-list {
  padding: 36rpx 36rpx 180rpx 36rpx;
  display: flex;
  flex-direction: column;
  gap: 40rpx;
}

.setting-group {
  display: flex;
  flex-direction: column;
  gap: 14rpx;
}

.group-title {
  font-size: 22rpx;
  font-weight: 600;
  color: #8e8e93;
  padding-left: 12rpx;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.group-desc {
  font-size: 22rpx;
  color: #8e8e93;
  padding-left: 12rpx;
  line-height: 1.5;
  margin-top: -6rpx;
}

.setting-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background-color: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 24rpx;
  padding: 28rpx 24rpx;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.01);
  transition: all 0.2s ease;
}

.setting-item:active {
  background-color: rgba(0, 0, 0, 0.01);
}

.setting-item-left {
  display: flex;
  align-items: center;
  gap: 20rpx;
  flex: 1;
  min-width: 0;
}

.item-icon {
  color: #8e8e93;
  flex-shrink: 0;
}

.danger-icon {
  color: #ff3b30;
}

.danger-text {
  color: #ff3b30 !important;
}

.setting-info {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
  flex: 1;
  min-width: 0;
}

.setting-name {
  font-size: 28rpx;
  font-weight: 500;
  color: #1c1c1e;
}

.setting-desc {
  font-size: 22rpx;
  color: #8e8e93;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.setting-action {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.chevron {
  color: #c7c7cc;
}

/* ===== Stepper ===== */
.stepper {
  display: flex;
  align-items: center;
  background-color: rgba(0, 0, 0, 0.03);
  border-radius: 40rpx;
  padding: 4rpx;
  flex-shrink: 0;
}

.step-btn {
  width: 52rpx;
  height: 52rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background-color: #ffffff;
  font-size: 28rpx;
  font-weight: 500;
  color: #1c1c1e;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.step-btn:active {
  background-color: rgba(0, 0, 0, 0.05);
}

.step-value {
  min-width: 70rpx;
  text-align: center;
  font-size: 24rpx;
  font-weight: 600;
  color: #1c1c1e;
}

/* ===== AI Engine Settings Card ===== */
.loading-card {
  background-color: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 24rpx;
  padding: 60rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.loading-text {
  font-size: 26rpx;
  color: #8e8e93;
}

.engine-card {
  background-color: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 24rpx;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.01);
}

.engine-row {
  display: flex;
  flex-direction: column;
  padding: 24rpx 28rpx;
  gap: 16rpx;
}

.engine-row.border-bottom {
  border-bottom: 1px solid rgba(0, 0, 0, 0.03);
}

.engine-row-left {
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}

.engine-name-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.engine-param-name {
  font-size: 27rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.engine-param-val {
  font-size: 24rpx;
  font-weight: 600;
  color: #1c1c1e;
  background-color: rgba(0, 0, 0, 0.04);
  padding: 3rpx 14rpx;
  border-radius: 20rpx;
}

.engine-param-desc {
  font-size: 21rpx;
  color: #8e8e93;
  line-height: 1.4;
}

.engine-slider {
  width: 100%;
}

/* Custom Toggle (reused from chat.vue) */
.custom-toggle {
  width: 88rpx;
  height: 48rpx;
  border-radius: 24rpx;
  background-color: rgba(0, 0, 0, 0.1);
  position: relative;
  transition: background-color 0.25s ease;
  flex-shrink: 0;
  cursor: pointer;
  align-self: center;
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

/* Save Button */
.save-engine-btn {
  height: 88rpx;
  background-color: #1c1c1e;
  border-radius: 44rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.25s ease;
  cursor: pointer;
}

.save-engine-btn:active {
  background-color: #000000;
  transform: scale(0.975);
}

.save-engine-text {
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 600;
}

/* ===== Status Tag & Version ===== */
.status-tag {
  font-size: 22rpx;
  font-weight: 600;
  color: #ff9500;
  background-color: rgba(255, 149, 0, 0.1);
  padding: 6rpx 16rpx;
  border-radius: 20rpx;
}

.status-tag.is-mock {
  color: #34c759;
  background-color: rgba(52, 199, 89, 0.1);
}

.version-text {
  font-size: 26rpx;
  font-weight: 500;
  color: #8e8e93;
}

/* ===== Modal Backdrop & Dialog ===== */
.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(10px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
}

.edit-modal {
  width: 580rpx;
  background-color: #ffffff;
  border-radius: 28rpx;
  padding: 44rpx 36rpx;
  display: flex;
  flex-direction: column;
  gap: 24rpx;
  box-shadow: 0 15px 35px rgba(0, 0, 0, 0.1);
  border: 1px solid rgba(0, 0, 0, 0.05);
}

.modal-title {
  font-size: 32rpx;
  font-weight: 600;
  color: #1c1c1e;
  text-align: center;
}

.modal-desc {
  font-size: 22rpx;
  color: #8e8e93;
  line-height: 1.5;
  text-align: center;
}

.key-input {
  width: 100%;
  height: 80rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 16rpx;
  padding: 0 24rpx;
  font-size: 28rpx;
  color: #1c1c1e;
  box-sizing: border-box;
}

.modal-actions {
  display: flex;
  justify-content: space-between;
  gap: 20rpx;
  margin-top: 10rpx;
}

.modal-btn {
  flex: 1;
  height: 80rpx;
  border-radius: 40rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26rpx;
  font-weight: 600;
  transition: all 0.2s;
}

.modal-btn.cancel {
  background-color: rgba(0, 0, 0, 0.03);
  color: #48484a;
}

.modal-btn.cancel:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.modal-btn.save {
  background-color: #1c1c1e;
  color: #ffffff;
}

.modal-btn.save:active {
  background-color: #000000;
  transform: scale(0.97);
}

/* ===== Advanced Settings Collapsible ===== */
.advanced-toggle-row {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 32rpx 28rpx;
  background-color: #ffffff;
}

.advanced-toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  width: 100%;
  height: 80rpx;
  background-color: rgba(0, 0, 0, 0.015);
  border: 1px dashed rgba(0, 0, 0, 0.12);
  border-radius: 20rpx;
  transition: all 0.2s ease;
  cursor: pointer;
}

.advanced-toggle-btn:active {
  background-color: rgba(0, 0, 0, 0.05);
  border-color: rgba(0, 0, 0, 0.25);
  transform: scale(0.995);
}

.advanced-toggle-text {
  font-size: 26rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.advanced-toggle-subtext {
  font-size: 22rpx;
  color: #8e8e93;
}

.advanced-chevron {
  width: 24rpx;
  height: 24rpx;
  opacity: 0.6;
  transform: rotate(90deg); /* points down by default */
  transition: transform 0.25s ease;
}

.advanced-chevron.is-active {
  transform: rotate(270deg); /* points up when open */
}

.advanced-section {
  display: none;
  background-color: rgba(0, 0, 0, 0.005);
}

.advanced-section.is-show {
  display: block;
}

/* Custom SVG Icon Styles */
.item-icon {
  width: 40rpx;
  height: 40rpx;
  flex-shrink: 0;
}
.chevron {
  width: 32rpx;
  height: 32rpx;
  flex-shrink: 0;
}

/* Fallback Unicode Icon Styles */
.item-icon-fallback {
  font-size: 34rpx;
  line-height: 1;
  width: 40rpx;
  text-align: center;
}
.chevron-fallback {
  display: none;
}
</style>
