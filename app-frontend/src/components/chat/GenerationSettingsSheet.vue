<template>
  <view v-if="isOpen" class="generation-overlay"
    ><view class="generation-backdrop" @tap="emit('close')"></view
    ><view class="generation-sheet" role="dialog" aria-label="故事模型设置"
      ><view class="sheet-heading"
        ><view
          ><text class="sheet-kicker">STORY ENGINE</text
          ><text class="sheet-title">为这段故事选择模型</text></view
        ><button aria-label="关闭模型设置" @tap="emit('close')">×</button></view
      ><scroll-view scroll-y class="sheet-body"
        ><view class="sheet-inner"
          ><text class="scope-hint"
            >仅此故事 · 当前设备保存 · 下一次生成生效</text
          ><text v-if="store.isLoadingModels" class="scope-hint"
            >正在加载模型目录…</text
          ><view v-if="store.settingsError" class="load-error"
            ><text>{{ store.settingsError }}</text
            ><button size="mini" @tap="store.refreshModels">重试</button></view
          ><GenerationPicker
            v-if="!store.isLoadingModels && store.modelId"
            v-model:model="store.modelId"
            v-model:thinkingMode="store.thinkingMode"
            v-model:effort="store.reasoningEffort"
            :catalog="store.catalog"
            :default-model="store.defaults.default_chat_model"
            :default-thinking="store.defaults.reasoning_mode"
            :default-effort="store.defaults.reasoning_effort"
          /><text class="scope-hint"
            >新故事采用默认配置，之后独立保存。</text
          ></view
        ></scroll-view
      ><view class="sheet-footer"
        ><button @tap="emit('close')">完成</button></view
      ></view
    ></view
  >
</template>
<script setup lang="ts">
import { watch } from "vue";
import { useChatSettingsStore } from "@/store/chatSettingsStore";
import GenerationPicker from "./GenerationPicker.vue";
const props = defineProps<{ isOpen: boolean }>();
const emit = defineEmits<{ (event: "close"): void }>();
const store = useChatSettingsStore();
watch(
  () => props.isOpen,
  (open) => {
    if (open) void store.refreshModels();
  },
);
</script>
<style scoped>
.generation-overlay {
  position: fixed;
  inset: 0;
  z-index: 350;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 24rpx;
  box-sizing: border-box;
}
.generation-backdrop {
  position: absolute;
  inset: 0;
  background: #17291f70;
  backdrop-filter: blur(8px);
}
.generation-sheet {
  position: relative;
  width: 100%;
  max-width: 640px;
  max-height: 90vh;
  background: #fff;
  border-radius: 28rpx;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.sheet-heading {
  padding: 32rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.sheet-heading button {
  margin: 0;
  padding: 0;
  width: 64rpx;
  height: 64rpx;
  line-height: 60rpx;
  border-radius: 50%;
  font-size: 38rpx;
  background: #f1f5f1;
  color: #7c8983;
}
.sheet-kicker {
  display: block;
  font-size: 18rpx;
  letter-spacing: 3rpx;
  color: #71917f;
  margin-bottom: 8rpx;
}
.sheet-title {
  font-size: 32rpx;
  font-weight: 700;
  color: #26332e;
}
.sheet-body {
  height: 480rpx;
  max-height: 60vh;
  min-height: 0;
}
.sheet-inner {
  padding: 0 32rpx 32rpx;
}
.scope-hint {
  display: block;
  font-size: 23rpx;
  color: #7c8983;
  line-height: 1.8;
  margin-bottom: 24rpx;
}
.load-error {
  padding: 20rpx;
  background: #fff6e8;
  color: #8f7045;
  font-size: 24rpx;
  margin-bottom: 20rpx;
}
.sheet-footer {
  padding: 24rpx 32rpx max(24rpx, env(safe-area-inset-bottom));
  border-top: 1px solid #e2e9e3;
}
.sheet-footer button {
  background: #4f8e7c;
  color: #fff;
  border-radius: 18rpx;
  font-size: 27rpx;
}
@media (max-width: 600px) {
  .generation-overlay {
    padding: 0;
    align-items: flex-end;
  }
  .generation-sheet {
    border-radius: 28rpx 28rpx 0 0;
  }
}
</style>
