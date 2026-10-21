<template>
  <view class="greetings">
    <view class="greetings-heading"
      ><text>共 {{ options.length }} 个故事开场</text
      ><text>选择后预览全文</text></view
    >
    <input
      v-if="options.length > 5"
      class="greeting-search"
      v-model="query"
      placeholder="搜索开场标题或内容"
      :maxlength="100"
    />
    <view class="greeting-list">
      <button
        v-for="option in visibleOptions"
        :key="option.index === null ? 'default' : option.index"
        class="greeting-option"
        :class="{ selected: modelValue === option.index }"
        @tap="emit('update:modelValue', option.index)"
      >
        <view class="option-top"
          ><text class="option-title">{{ option.title }}</text
          ><text class="option-number"
            >{{ option.index === null ? "默认" : "#" + (option.index + 2) }}
            {{ modelValue === option.index ? "✓" : "" }}</text
          ></view
        >
        <text class="option-preview">{{ substitute(option.preview) }}</text>
      </button>
      <text v-if="!filtered.length" class="no-results"
        >没有匹配的开场，试试其他关键词。</text
      >
    </view>
    <view v-if="filtered.length > pageSize" class="greeting-pages">
      <button size="mini" :disabled="page === 0" @tap="page--">上一组</button
      ><text>{{ page + 1 }} / {{ Math.ceil(filtered.length / pageSize) }}</text
      ><button
        size="mini"
        :disabled="(page + 1) * pageSize >= filtered.length"
        @tap="page++"
      >
        下一组
      </button>
    </view>
    <view v-if="selected" class="greeting-reading"
      ><text class="selected-title">{{ selected.title }} · 全文预览</text
      ><CharacterCardText
        :content="substitute(selected.content)"
        empty-text="此开场未填写正文，建议先补充内容。"
    /></view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import { greetingOptions } from "@/utils/characterCard";
import CharacterCardText from "./CharacterCardText.vue";
const props = withDefaults(
  defineProps<{
    firstMes?: string;
    alternates?: string[];
    modelValue: number | null;
    characterName?: string;
    userName?: string;
  }>(),
  {
    firstMes: "",
    alternates: () => [],
    characterName: "角色",
    userName: "用户",
  },
);
const emit = defineEmits<{
  (event: "update:modelValue", index: number | null): void;
}>();
const query = ref("");
const page = ref(0);
const pageSize = 6;
const options = computed(() =>
  greetingOptions(props.firstMes, props.alternates),
);
const substitute = (text: string) =>
  text
    .replace(/\{\{char\}\}/gi, () => props.characterName)
    .replace(/\{\{user\}\}/gi, () => props.userName);
const filtered = computed(() =>
  options.value.filter((option) =>
    substitute(option.title + " " + option.content)
      .toLocaleLowerCase()
      .includes(query.value.trim().toLocaleLowerCase()),
  ),
);
const visibleOptions = computed(() =>
  filtered.value.slice(page.value * pageSize, (page.value + 1) * pageSize),
);
const selected = computed(() =>
  options.value.find((option) => option.index === props.modelValue),
);
watch(query, () => {
  page.value = 0;
});
watch(
  () => filtered.value.length,
  (count) => {
    page.value = Math.min(
      page.value,
      Math.max(0, Math.ceil(count / pageSize) - 1),
    );
  },
);
watch(
  () => props.alternates.length,
  (count) => {
    if (props.modelValue !== null && props.modelValue >= count)
      emit("update:modelValue", null);
  },
);
</script>

<style scoped>
.greetings {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}
.greetings-heading,
.option-top,
.greeting-pages {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
}
.greetings-heading {
  font-size: 23rpx;
  color: var(--app-color-text-secondary, #7c8983);
}
.greeting-search {
  background: var(--app-color-background, #f7f9f7);
  border: 1px solid var(--app-color-border, #e3e9e5);
  height: 84rpx;
  box-sizing: border-box;
  padding: 0 24rpx;
  border-radius: 16rpx;
  font-size: 25rpx;
}
.greeting-list {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}
.greeting-option {
  margin: 0;
  padding: 22rpx;
  text-align: left;
  background: #fff;
  border: 1px solid var(--app-color-border, #e3e9e5);
  border-radius: 18rpx;
  line-height: 1.5;
}
.greeting-option::after {
  border: 0;
}
.greeting-option.selected {
  border-color: var(--app-color-primary-strong, #4f8e7c);
  background: #eef6f1;
}
.option-title {
  min-width: 0;
  font-size: 25rpx;
  font-weight: 600;
  color: var(--app-color-text-primary, #26332e);
}
.option-number {
  flex-shrink: 0;
  font-size: 21rpx;
  color: var(--app-color-primary-strong, #4f8e7c);
}
.option-preview {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-top: 8rpx;
  font-size: 23rpx;
  color: var(--app-color-text-secondary, #7c8983);
}
.greeting-reading {
  border-top: 1px solid var(--app-color-border, #e3e9e5);
  padding-top: 24rpx;
}
.selected-title {
  display: block;
  font-size: 25rpx;
  font-weight: 600;
  margin-bottom: 22rpx;
  color: var(--app-color-primary-strong, #4f8e7c);
}
.greeting-pages text,
.no-results {
  font-size: 23rpx;
  color: var(--app-color-text-secondary, #7c8983);
}
.greeting-pages button {
  margin: 0;
  font-size: 22rpx;
  color: #4f8e7c;
}
</style>
