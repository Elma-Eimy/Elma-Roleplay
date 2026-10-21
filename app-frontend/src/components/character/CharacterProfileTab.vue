<template>
  <view class="profile-details-section">
    <view v-if="metadata.creator || metadata.version" class="profile-meta"
      ><text v-if="metadata.creator">作者 · {{ metadata.creator }}</text
      ><text v-if="metadata.version"
        >角色版本 · {{ metadata.version }}</text
      ></view
    >
    <view v-for="section in sections" :key="section.key" class="section-card">
      <button
        class="section-header"
        :aria-expanded="!!expanded[section.key]"
        @tap="expanded[section.key] = !expanded[section.key]"
      >
        <view
          ><text class="section-title">{{ section.title }}</text
          ><text class="section-caption">{{ section.caption }}</text></view
        ><text class="section-arrow">{{
          expanded[section.key] ? "−" : "＋"
        }}</text>
      </button>
      <view v-if="expanded[section.key]" class="section-content"
        ><CharacterCardText :content="section.content" :source="section.source"
      /></view>
    </view>
    <view class="section-card">
      <button
        class="section-header"
        :aria-expanded="!!expanded.greetings"
        @tap="expanded.greetings = !expanded.greetings"
      >
        <view
          ><text class="section-title"
            >故事开场 · {{ greetings.length + 1 }}</text
          ><text class="section-caption"
            >浏览不同的相遇，开启故事时可自由选择</text
          ></view
        ><text class="section-arrow">{{
          expanded.greetings ? "−" : "＋"
        }}</text>
      </button>
      <view v-if="expanded.greetings" class="section-content"
        ><CharacterGreetings
          v-model="selectedGreeting"
          :first-mes="reading.first_mes"
          :alternates="greetings"
          :character-name="character.name"
          :user-name="personaStore.nicknameFor(character.id)"
      /></view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import type { CharacterBase, CharacterDetail } from "@/api/characters";
import { usePersonaStore } from "@/store/personaStore";
import { getCardGreetings, getCardMetadata } from "@/utils/characterCard";
import CharacterCardText from "./CharacterCardText.vue";
import CharacterGreetings from "./CharacterGreetings.vue";
const props = defineProps<{ character: CharacterDetail; readingCharacter?: CharacterBase }>();
const reading = computed(() => props.readingCharacter || props.character);
const personaStore = usePersonaStore();
const expanded = ref<Record<string, boolean>>({ description: true });
const selectedGreeting = ref<number | null>(null);
watch(
  () => props.character.id,
  () => {
    expanded.value = { description: true };
    selectedGreeting.value = null;
  },
);
const metadata = computed(() => getCardMetadata(props.character));
const greetings = computed(() => getCardGreetings(reading.value));
const sections = computed(() =>
  [
    {
      key: "creator_notes",
      title: "作者说明",
      caption: "使用建议与创作备注，不作为角色台词",
      content: reading.value.creator_notes,
      source: false,
    },
    {
      key: "description",
      title: "人物背景",
      caption: "身份、经历与人物设定",
      content: reading.value.description,
      source: false,
    },
    {
      key: "personality",
      title: "性格特征",
      caption: "人物的性情与表达习惯",
      content: reading.value.personality,
      source: false,
    },
    {
      key: "scenario",
      title: "故事场景",
      caption: "这段故事发生的环境",
      content: reading.value.scenario,
      source: false,
    },
    {
      key: "mes_example",
      title: "对话示例",
      caption: "保留作者的示例格式与占位符",
      content: reading.value.mes_example,
      source: true,
    },
    {
      key: "system_prompt_override",
      title: "自定义系统提示词",
      caption: "进阶设定 · 原文",
      content: props.character.system_prompt_override,
      source: true,
    },
    {
      key: "post_history_instructions",
      title: "历史末端指令",
      caption: "进阶设定 · 原文",
      content: props.character.post_history_instructions,
      source: true,
    },
  ].filter((section) => section.content?.trim()),
);
</script>

<style scoped>
.profile-details-section {
  display: flex;
  flex-direction: column;
  gap: 18rpx;
  padding: 0 var(--app-page-gutter, 36rpx) 100rpx;
}
.profile-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 18rpx;
  padding: 8rpx 4rpx 18rpx;
  color: var(--app-color-text-secondary, #7c8983);
  font-size: 23rpx;
}
.section-card {
  background: rgba(255, 255, 255, 0.75);
  border: 1px solid var(--app-color-border, #e3e9e5);
  border-radius: 24rpx;
  overflow: hidden;
}
.section-header {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 20rpx;
  padding: 28rpx;
  text-align: left;
  margin: 0;
  background: transparent;
  border-radius: 0;
  line-height: 1.5;
}
.section-header::after {
  border: 0;
}
.section-title {
  display: block;
  font-size: 28rpx;
  font-weight: 600;
  color: var(--app-color-text-primary, #26332e);
}
.section-caption {
  display: block;
  font-size: 22rpx;
  color: var(--app-color-text-secondary, #7c8983);
  margin-top: 6rpx;
}
.section-arrow {
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: 30rpx;
  flex-shrink: 0;
}
.section-content {
  padding: 0 28rpx 30rpx;
}
</style>
