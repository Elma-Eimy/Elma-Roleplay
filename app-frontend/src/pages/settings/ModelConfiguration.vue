<template>
  <view class="model-configuration">
    <text class="configuration-title">模型与思考</text
    ><text class="configuration-intro"
      >模型和思考模式独立选择。故事中的单独设置优先于这里的默认值。</text
    >
    <GenerationPicker
      :model="settings.default_chat_model"
      :thinking-mode="settings.reasoning_mode ? 'enabled' : 'disabled'"
      :effort="settings.reasoning_effort || 'inherit'"
      :catalog="catalog"
      :allow-inherit="false"
      @update:model="emit('change', { default_chat_model: $event })"
      @update:thinkingMode="
        emit('change', { reasoning_mode: $event === 'enabled' })
      "
      @update:effort="
        emit('change', {
          reasoning_effort: $event === 'inherit' ? null : $event,
        })
      "
    />
    <view class="configuration-section"
      ><button class="section-toggle" @tap="showProfiles = !showProfiles">
        {{ showProfiles ? "收起" : "管理" }}模型目录 ·
        {{ catalog.length }} 个模型
      </button>
      <view v-if="showProfiles" class="profiles">
        <text class="configuration-intro"
          >添加服务端可调用的模型
          ID，并选择与该服务匹配的适配方式。所有模型沿用当前服务器的聊天连接。</text
        >
        <view v-for="profile in catalog" :key="profile.id" class="profile-row"
          ><text class="profile-id">{{ profile.id }}</text
          ><input
            class="model-input"
            :value="profile.label"
            placeholder="显示名称"
            @input="
              (event: any) =>
                setProfile(profile.id, { label: event.detail.value })
            "
          /><picker
            :range="adapterLabels"
            :value="adapterValues.indexOf(profile.adapter)"
            @change="
              setProfile(profile.id, {
                adapter: adapterValues[Number($event.detail.value)],
              })
            "
            ><view class="adapter-value"
              >{{
                adapterLabels[adapterValues.indexOf(profile.adapter)]
              }}
              ⌄</view
            ></picker
          ><button
            v-if="
              settings.model_profiles.some((item) => item.id === profile.id)
            "
            size="mini"
            class="remove-profile"
            @tap="removeProfile(profile.id)"
          >
            移除自定义配置
          </button></view
        >
        <view class="add-profile"
          ><input
            class="model-input"
            v-model="newId"
            placeholder="模型 ID，例如 deepseek-flash"
            :maxlength="200"
          /><button size="mini" @tap="addProfile">添加模型</button
          ><text v-if="profileError" class="profile-error">{{
            profileError
          }}</text></view
        >
      </view>
    </view>
    <view class="configuration-section"
      ><button class="section-toggle" @tap="showAuxiliary = !showAuxiliary">
        {{ showAuxiliary ? "收起" : "展开" }}辅助任务模型</button
      ><view v-if="showAuxiliary" class="auxiliary-settings"
        ><text class="configuration-intro"
          >记忆提取、认知更新和语音文本整理使用独立设置，不随聊天中的模型切换。</text
        >
        <GenerationPicker
          model-label="记忆与认知模型"
          :model="settings.memory_model"
          :thinking-mode="settings.memory_thinking_mode"
          :effort="settings.memory_reasoning_effort"
          :catalog="catalog"
          :allow-inherit="false"
          :allow-default-effort="false"
          @update:model="emit('change', { memory_model: $event })"
          @update:thinkingMode="
            emit('change', {
              memory_thinking_mode:
                $event === 'enabled' ? 'enabled' : 'disabled',
            })
          "
          @update:effort="emit('change', { memory_reasoning_effort: $event })"
        />
        <view class="auxiliary-divider"></view
        ><GenerationPicker
          model-label="语音文本整理模型"
          :model="settings.tts_preprocess_model"
          :thinking-mode="settings.tts_thinking_mode"
          :effort="settings.tts_reasoning_effort"
          :catalog="catalog"
          :allow-inherit="false"
          :allow-default-effort="false"
          @update:model="emit('change', { tts_preprocess_model: $event })"
          @update:thinkingMode="
            emit('change', {
              tts_thinking_mode: $event === 'enabled' ? 'enabled' : 'disabled',
            })
          "
          @update:effort="emit('change', { tts_reasoning_effort: $event })"
        /> </view
    ></view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import type { AppSettings } from "@/api/settings";
import type { ModelProfile, ModelAdapter } from "@/types/generation";
import { configuredCatalog } from "@/utils/generation";
import GenerationPicker from "@/components/chat/GenerationPicker.vue";
const props = defineProps<{ settings: AppSettings }>();
const emit = defineEmits<{
  (event: "change", value: Partial<AppSettings>): void;
}>();
const catalog = computed(() => configuredCatalog(props.settings));
const showProfiles = ref(false);
const showAuxiliary = ref(false);
const newId = ref("");
const profileError = ref("");
const adapterValues: ModelAdapter[] = ["compatible", "deepseek", "reasoning"];
const adapterLabels = ["普通兼容模型", "DeepSeek 思考兼容", "固定思考推理模型"];
function setProfile(id: string, patch: Partial<ModelProfile>) {
  const rows = props.settings.model_profiles.map((item) => ({ ...item }));
  const existing = rows.find((item) => item.id === id);
  if (existing) Object.assign(existing, patch);
  else {
    const original = catalog.value.find((item) => item.id === id);
    rows.push({
      id,
      label: original?.label || id,
      adapter: original?.adapter || "compatible",
      ...patch,
    });
  }
  emit("change", { model_profiles: rows });
}
function removeProfile(id: string) {
  emit("change", {
    model_profiles: props.settings.model_profiles.filter(
      (item) => item.id !== id,
    ),
  });
}
function addProfile() {
  const id = newId.value.trim();
  if (!id) {
    profileError.value = "先填写模型 ID。";
    return;
  }
  if (catalog.value.some((item) => item.id === id)) {
    profileError.value =
      "此模型已在目录中，可以直接修改它的显示名称和适配方式。";
    return;
  }
  setProfile(id, {
    label: id,
    adapter: id.toLowerCase().startsWith("deepseek-")
      ? "deepseek"
      : "compatible",
  });
  newId.value = "";
  profileError.value = "";
}
</script>

<style scoped>
.model-configuration {
  padding: 28rpx;
  display: flex;
  flex-direction: column;
  gap: 26rpx;
  border-bottom: 1px solid #e2e9e3;
}
.configuration-title {
  font-size: 31rpx;
  font-weight: 700;
  color: #26332e;
}
.configuration-intro {
  display: block;
  font-size: 23rpx;
  line-height: 1.8;
  color: #7c8983;
}
.configuration-section {
  padding-top: 8rpx;
}
.section-toggle {
  margin: 0;
  background: #eef4ef;
  color: #4f7860;
  border-radius: 16rpx;
  font-size: 25rpx;
  text-align: left;
  padding: 0 22rpx;
  line-height: 76rpx;
}
.profiles,
.auxiliary-settings {
  display: flex;
  flex-direction: column;
  gap: 24rpx;
  padding-top: 24rpx;
}
.profile-row {
  padding: 22rpx;
  border: 1px solid #e0e8e1;
  border-radius: 18rpx;
  display: flex;
  flex-direction: column;
  gap: 14rpx;
}
.profile-id {
  font-size: 23rpx;
  color: #557763;
  overflow-wrap: anywhere;
}
.model-input {
  height: 84rpx;
  box-sizing: border-box;
  padding: 0 22rpx;
  border: 1px solid #e0e8e1;
  border-radius: 14rpx;
  background: #fff;
  font-size: 25rpx;
}
.adapter-value {
  padding: 18rpx 22rpx;
  border-radius: 14rpx;
  font-size: 24rpx;
  color: #4f7560;
  background: #f2f6f2;
}
.remove-profile {
  margin: 0;
  color: #7c8983;
  background: #f6f7f4;
  font-size: 22rpx;
}
.add-profile {
  display: flex;
  flex-direction: column;
  gap: 18rpx;
}
.add-profile button {
  margin: 0;
  color: #4f8e7c;
  font-size: 25rpx;
}
.profile-error {
  color: #9b6c4c;
  font-size: 23rpx;
}
.auxiliary-divider {
  height: 1px;
  background: #e2e9e3;
  margin: 12rpx 0;
}
</style>
