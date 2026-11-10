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
          <button
            class="char-card-avatar-link"
            :aria-label="`查看${personaStore.characterName}的人物档案`"
            :disabled="!personaStore.activeCharacter?.id || personaStore.isLoadingPersona || isOpeningProfile"
            @tap.stop="openCharacterProfile"
          >
            <AvatarImage
              class="char-card-avatar"
              :src="getAvatarUrl(personaStore.activeCharacter?.avatar_path || '')"
              :lazy-load="false"
            />
          </button>
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

        <view class="panel-section"><RoleStatePanel :session-id="props.sessionId" /></view>
        <view v-if="personaStore.activeCharacter?.id" class="panel-section">
          <CharacterPortraitPanel
            :character-id="personaStore.activeCharacter.id"
            :session-id="props.sessionId"
            :disabled="chatStore.isLoading"
            :timeline="portraitTimeline"
            @changed="emit('portrait-changed')"
          />
        </view>

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
              <text v-if="!showCognition" class="section-collapse-summary">{{ (personaStore.cognitionState || '暂无认知记录').slice(0, 14) }}{{ (personaStore.cognitionState || '').length > 14 ? '…' : '' }}</text>
              <image
                class="advanced-chevron"
                :class="{ 'is-active': showCognition }"
                src="/static/icons/settings_chevron.svg"
                mode="aspectFit"
              />
            </view>
          </view>
          <view v-if="showCognition" class="cognition-box">
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
              <view class="setting-row-copy">
                <text class="setting-row-label">我的名字</text>
                <text class="setting-row-hint">只对当前角色生效</text>
              </view>
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
          <text class="generation-scope">模型选择仅用于当前故事，在本机保存。</text>
          <text v-if="chatSettingsStore.isLoadingModels" class="generation-scope">正在加载模型配置…</text>
          <text v-if="chatSettingsStore.settingsError" class="generation-scope">{{ chatSettingsStore.settingsError }}</text>
          <GenerationPicker v-if="!chatSettingsStore.isLoadingModels && chatSettingsStore.modelId" v-model:model="chatSettingsStore.modelId" v-model:thinkingMode="chatSettingsStore.thinkingMode" v-model:effort="chatSettingsStore.reasoningEffort" :catalog="chatSettingsStore.catalog" :default-model="chatSettingsStore.defaults.default_chat_model" :default-thinking="chatSettingsStore.defaults.reasoning_mode" :default-effort="chatSettingsStore.defaults.reasoning_effort" />
          <text v-if="chatStore.lastMeta?.model_used" class="generation-scope">上次回复使用：{{ chatStore.lastMeta.model_used }}</text>
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
                    :src="getAvatarUrl(personaStore.activeCharacter?.avatar_path || '')"
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
              <slider :disabled="chatSettingsStore.effective.thinking"
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
              <slider :disabled="chatSettingsStore.effective.capability?.adapter === 'reasoning' || (chatSettingsStore.effective.capability?.adapter === 'deepseek' && (/flash/i.test(chatSettingsStore.effective.id) ? !chatSettingsStore.effective.thinking : chatSettingsStore.effective.thinking))"
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
              <slider :disabled="chatSettingsStore.effective.thinking"
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
              <slider :disabled="chatSettingsStore.effective.thinking"
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
              <slider :disabled="chatSettingsStore.effective.capability?.adapter !== 'compatible'"
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
          <MemoryProcessingPanel :session-id="props.sessionId" />
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
import { triggerCognition } from "@/api/sessions";
import MemoryProcessingPanel from "./MemoryProcessingPanel.vue";
import GenerationPicker from "./GenerationPicker.vue";
import RoleStatePanel from "./RoleStatePanel.vue";
import CharacterPortraitPanel from "@/components/character/CharacterPortraitPanel.vue";
import AvatarImage from "@/components/common/AvatarImage.vue";
import ChatReadingPreferences from "./ChatReadingPreferences.vue";

const props = defineProps<{
  isOpen: boolean;
  sessionId: number | null;
  backgroundMode: "clean" | "character";
}>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "portrait-changed"): void;
  (e: "delete-session"): void;
  (e: "open-branch-tree"): void;
  (e: "open-memory-view"): void;
  (e: "open-prompt-preview"): void;
  (e: "update:background-mode", mode: "clean" | "character"): void;
}>();

const chatStore = useChatStore();
const portraitTimeline = computed(() => `${chatStore.isLoading}:${chatStore.messages.map(message => message.id).join(',')}`);
const personaStore = usePersonaStore();
const chatSettingsStore = useChatSettingsStore();
const isOpeningProfile = ref(false);

const openCharacterProfile = () => {
  const characterId = personaStore.activeCharacter?.id;
  if (!characterId || personaStore.isLoadingPersona || isOpeningProfile.value) return;
  isOpeningProfile.value = true;
  // 压入页面栈，保留原聊天页及其草稿；档案页 navigateBack 返回此处。
  uni.navigateTo({
    url: `/pages/character/detail?id=${characterId}`,
    success: () => emit("close"),
    fail: () => uni.showToast({ title: "无法打开人物档案，请重试", icon: "none" }),
    complete: () => { isOpeningProfile.value = false; },
  });
};

const showAdvancedParams = ref(false);
const showCognition = ref(true);

const userNicknameInput = ref(personaStore.userNickname);

// 当前角色或该角色的名字变化时，同步输入框
watch(() => personaStore.userNickname, (newVal) => {
  userNicknameInput.value = newVal;
});

const saveUserNickname = () => {
  const name = userNicknameInput.value.trim();
  const characterId = personaStore.activeCharacter?.id;
  if (name && characterId != null) {
    personaStore.updateUserNickname(name, characterId);
  } else {
    userNicknameInput.value = personaStore.userNickname;
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
@import "./chatDrawer.css";
</style>
