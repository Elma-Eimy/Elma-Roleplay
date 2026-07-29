<template>
  <view class="engine-settings-container">
    <!-- 加载配置时的 Loading 卡片 -->
    <AppStatusState
      v-if="isLoading"
      kind="loading"
      title="正在加载引擎配置"
      description="同步模型、记忆与世界书参数。"
      compact
    />

    <view v-else class="engine-card">
      <!-- 推理模式开关行 -->
      <view class="engine-row border-bottom">
        <view class="engine-row-left">
          <text class="engine-param-name">默认推理模式</text>
          <text class="engine-param-desc">全局默认是否使用深度思考模型（聊天页的切换优先级更高）</text>
        </view>
        <view
          class="custom-toggle"
          :class="{ 'is-on': localSettings.reasoning_mode }"
          @tap="localSettings.reasoning_mode = !localSettings.reasoning_mode"
        >
          <view class="toggle-thumb"></view>
        </view>
      </view>

      <!-- 温度参数滑块行 -->
      <view class="engine-row border-bottom">
        <view class="engine-row-left">
          <view class="engine-name-row">
            <text class="engine-param-name">创意温度 (Temperature)</text>
            <text class="engine-param-val">{{ localSettings.temperature.toFixed(1) }}</text>
          </view>
          <text class="engine-param-desc">控制回复的随机性。值越高越有创意，越低越保守精确（范围 0.1 ~ 2.0）</text>
        </view>
        <slider
          class="engine-slider"
          :value="Math.round(localSettings.temperature * 10)"
          :min="1" :max="20" :step="1"
          activeColor="#70ae9b"
          backgroundColor="rgba(38,51,46,0.08)"
          block-color="#ffffff"
          block-size="20"
          @change="(e: any) => localSettings.temperature = e.detail.value / 10"
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
          <text class="step-value">{{ localSettings.context_history_limit }}</text>
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
          <text class="step-value">{{ localSettings.retrieval_top_k }}</text>
          <view class="step-btn" @tap="stepInt('retrieval_top_k', 1, 1, 20)">+</view>
        </view>
      </view>

      <!-- 高级设置折叠切换行 -->
      <view class="advanced-toggle-row" @tap="showAdvanced = !showAdvanced">
        <view class="advanced-toggle-btn">
          <text class="advanced-toggle-text">{{ showAdvanced ? '收起高级参数' : '展开高级参数' }}</text>
          <text class="advanced-toggle-subtext" v-if="!showAdvanced">（包括重要度、世界书、Token限制等 13 项）</text>
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
        <!-- 核采样比例 Top P 滑块行 -->
        <view class="engine-row border-bottom">
          <view class="engine-row-left">
            <view class="engine-name-row">
              <text class="engine-param-name">核采样比例 (Top P)</text>
              <text class="engine-param-val">{{ localSettings.top_p.toFixed(2) }}</text>
            </view>
            <text class="engine-param-desc">核采样概率阈值，只保留概率累加达到此值的高概率词汇（范围 0.10 ~ 1.00）</text>
          </view>
          <slider
            class="engine-slider"
            :value="Math.round(localSettings.top_p * 100)"
            :min="10" :max="100" :step="5"
            activeColor="#70ae9b"
            backgroundColor="rgba(38,51,46,0.08)"
            block-color="#ffffff"
            block-size="20"
            @change="(e: any) => localSettings.top_p = e.detail.value / 100"
          />
        </view>

        <!-- 存在惩罚 Presence Penalty 滑块行 -->
        <view class="engine-row border-bottom">
          <view class="engine-row-left">
            <view class="engine-name-row">
              <text class="engine-param-name">存在惩罚 (Presence Penalty)</text>
              <text class="engine-param-val">{{ localSettings.presence_penalty.toFixed(1) }}</text>
            </view>
            <text class="engine-param-desc">对已出现过的词施加一次性惩罚，值越高越鼓励 AI 开启新话题（范围 -2.0 ~ 2.0）</text>
          </view>
          <slider
            class="engine-slider"
            :value="Math.round((localSettings.presence_penalty + 2) * 10)"
            :min="0" :max="40" :step="1"
            activeColor="#70ae9b"
            backgroundColor="rgba(38,51,46,0.08)"
            block-color="#ffffff"
            block-size="20"
            @change="(e: any) => localSettings.presence_penalty = (e.detail.value / 10) - 2"
          />
        </view>

        <!-- 频率惩罚 Frequency Penalty 滑块行 -->
        <view class="engine-row border-bottom">
          <view class="engine-row-left">
            <view class="engine-name-row">
              <text class="engine-param-name">频率惩罚 (Frequency Penalty)</text>
              <text class="engine-param-val">{{ localSettings.frequency_penalty.toFixed(1) }}</text>
            </view>
            <text class="engine-param-desc">根据词汇出现的累积频次施加惩罚，用于有效抑制复读机现象（范围 -2.0 ~ 2.0）</text>
          </view>
          <slider
            class="engine-slider"
            :value="Math.round((localSettings.frequency_penalty + 2) * 10)"
            :min="0" :max="40" :step="1"
            activeColor="#70ae9b"
            backgroundColor="rgba(38,51,46,0.08)"
            block-color="#ffffff"
            block-size="20"
            @change="(e: any) => localSettings.frequency_penalty = (e.detail.value / 10) - 2"
          />
        </view>

        <!-- 重复度惩罚 Repetition Penalty 滑块行 -->
        <view class="engine-row border-bottom">
          <view class="engine-row-left">
            <view class="engine-name-row">
              <text class="engine-param-name">重复度惩罚 (Repetition Penalty)</text>
              <text class="engine-param-val">{{ localSettings.repetition_penalty.toFixed(2) }}</text>
            </view>
            <text class="engine-param-desc">乘积型惩罚，主要用于本地及特定云端模型，1.0 代表不惩罚（范围 0.50 ~ 2.00）</text>
          </view>
          <slider
            class="engine-slider"
            :value="Math.round(localSettings.repetition_penalty * 100)"
            :min="50" :max="200" :step="5"
            activeColor="#70ae9b"
            backgroundColor="rgba(38,51,46,0.08)"
            block-color="#ffffff"
            block-size="20"
            @change="(e: any) => localSettings.repetition_penalty = e.detail.value / 100"
          />
        </view>

        <!-- 记忆过滤最低重要度滑块行 -->
        <view class="engine-row border-bottom">
          <view class="engine-row-left">
            <view class="engine-name-row">
              <text class="engine-param-name">记忆最低重要度</text>
              <text class="engine-param-val">{{ localSettings.retrieval_min_importance.toFixed(2) }}</text>
            </view>
            <text class="engine-param-desc">低于此阈值的记忆将被过滤（范围 0.00 ~ 1.00）</text>
          </view>
          <slider
            class="engine-slider"
            :value="Math.round(localSettings.retrieval_min_importance * 100)"
            :min="0" :max="100" :step="5"
            activeColor="#70ae9b"
            backgroundColor="rgba(38,51,46,0.08)"
            block-color="#ffffff"
            block-size="20"
            @change="(e: any) => localSettings.retrieval_min_importance = e.detail.value / 100"
          />
        </view>

        <!-- 记忆检索最大容忍距离滑块行 -->
        <view class="engine-row border-bottom">
          <view class="engine-row-left">
            <view class="engine-name-row">
              <text class="engine-param-name">记忆最大向量距离</text>
              <text class="engine-param-val">{{ localSettings.retrieval_max_distance.toFixed(1) }}</text>
            </view>
            <text class="engine-param-desc">向量相似度的最大容忍距离，越小越严格（范围 0.5 ~ 3.0）</text>
          </view>
          <slider
            class="engine-slider"
            :value="Math.round(localSettings.retrieval_max_distance * 10)"
            :min="5" :max="30" :step="1"
            activeColor="#70ae9b"
            backgroundColor="rgba(38,51,46,0.08)"
            block-color="#ffffff"
            block-size="20"
            @change="(e: any) => localSettings.retrieval_max_distance = e.detail.value / 10"
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
            <text class="step-value">{{ localSettings.lorebook_scan_depth }}</text>
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
            <text class="step-value">{{ localSettings.lorebook_token_budget }}</text>
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
            <text class="step-value">{{ localSettings.lorebook_max_recursive_passes }}</text>
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
            <text class="step-value">{{ localSettings.cognition_max_words }}</text>
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
            <text class="step-value">{{ localSettings.max_tokens }}</text>
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
            <text class="step-value">{{ localSettings.retrieval_half_life_turns }}</text>
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
            <text class="step-value">{{ localSettings.retrieval_candidate_multiplier }}</text>
            <view class="step-btn" @tap="stepInt('retrieval_candidate_multiplier', 1, 1, 20)">+</view>
          </view>
        </view>
      </view>
    </view>

    <!-- 引擎参数保存按钮 -->
    <view class="save-engine-btn" @tap="save" v-if="!isLoading">
      <text class="save-engine-text">保存引擎设置</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from "vue";
import type { AppSettings } from "@/api/settings";
import AppStatusState from "@/components/common/AppStatusState.vue";

const props = defineProps<{
  settings: AppSettings;
  isLoading: boolean;
}>();

const emit = defineEmits<{
  (e: "save", settings: AppSettings): void;
}>();

const showAdvanced = ref(false);
const localSettings = reactive<AppSettings>({ ...props.settings });

// 监听父组件属性变化，并同步更新本地副本
watch(() => props.settings, (newVal) => {
  if (newVal) {
    Object.assign(localSettings, newVal);
  }
}, { deep: true });

// 步进器调整字段逻辑
const stepInt = (
  key: keyof AppSettings,
  delta: number,
  min: number,
  max: number
) => {
  const cur = localSettings[key] as number;
  const next = cur + delta;
  if (next >= min && next <= max) {
    (localSettings as any)[key] = next;
  }
};

const save = () => {
  emit("save", { ...localSettings });
};
</script>

<style scoped>
.engine-settings-container {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.engine-card {
  background-color: rgba(247, 249, 247, 0.6);
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-radius: 24rpx;
  overflow: hidden;
}

.engine-row {
  display: flex;
  flex-direction: column;
  padding: 24rpx 28rpx;
  gap: 16rpx;
}

.engine-row.border-bottom {
  border-bottom: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.07));
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
  color: var(--app-color-text-primary, #26332e);
}

.engine-param-val {
  font-size: 24rpx;
  font-weight: 600;
  color: var(--app-color-primary-strong, #4f8e7c);
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  padding: 3rpx 14rpx;
  border-radius: 20rpx;
}

.engine-param-desc {
  font-size: 21rpx;
  color: var(--app-color-text-secondary, #7c8983);
  line-height: 1.4;
}

.engine-slider {
  width: 100%;
  margin: 0;
  box-sizing: border-box;
}

/* Custom Toggle */
.custom-toggle {
  width: 88rpx;
  height: 48rpx;
  border-radius: 24rpx;
  background-color: rgba(124, 137, 131, 0.2);
  position: relative;
  transition: background-color 0.25s ease;
  flex-shrink: 0;
  cursor: pointer;
  align-self: center;
}

.custom-toggle.is-on {
  background-color: var(--app-color-primary, #70ae9b);
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
  background-color: var(--app-color-primary, #70ae9b);
  border-radius: 44rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.25s ease;
  cursor: pointer;
}

.save-engine-btn:active {
  background-color: var(--app-color-primary-strong, #4f8e7c);
  transform: scale(0.975);
}

.save-engine-text {
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 600;
}

/* ===== Stepper ===== */
.stepper {
  display: flex;
  align-items: center;
  background-color: rgba(124, 137, 131, 0.09);
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
  color: var(--app-color-text-primary, #26332e);
  box-shadow: 0 3rpx 10rpx rgba(45, 72, 62, 0.07);
}

.step-btn:active {
  background-color: rgba(0, 0, 0, 0.05);
}

.step-value {
  min-width: 70rpx;
  text-align: center;
  font-size: 24rpx;
  font-weight: 600;
  color: var(--app-color-text-primary, #26332e);
}

/* ===== Advanced Settings Collapsible ===== */
.advanced-toggle-row {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 32rpx 28rpx;
  background-color: rgba(247, 249, 247, 0.42);
}

.advanced-toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  width: 100%;
  height: 80rpx;
  background-color: rgba(255, 255, 255, 0.58);
  border: 1px dashed rgba(112, 174, 155, 0.32);
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
  color: var(--app-color-text-primary, #26332e);
}

.advanced-toggle-subtext {
  font-size: 22rpx;
  color: var(--app-color-text-secondary, #7c8983);
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
  background-color: rgba(255, 255, 255, 0.3);
}

.advanced-section.is-show {
  display: block;
}
</style>
