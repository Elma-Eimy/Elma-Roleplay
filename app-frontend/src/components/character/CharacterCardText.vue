<template>
  <view class="card-reading">
    <template v-if="pageCount > 1">
      <text class="reading-hint">上下滑动阅读本页，翻页后从页首开始。</text>
      <scroll-view :key="page" scroll-y class="reading-viewport">
        <text v-if="source" class="source-text" selectable>{{ pageText }}</text>
        <rich-text v-else class="reading-text" :nodes="rendered" />
      </scroll-view>
    </template>
    <template v-else>
      <text v-if="source" class="source-text" selectable>{{ pageText }}</text>
      <rich-text v-else class="reading-text" :nodes="rendered" />
    </template>
    <text v-if="!content" class="reading-empty">{{ emptyText }}</text>
    <view v-if="pageCount > 1" class="reading-pages">
      <button size="mini" :disabled="page === 0" @tap="page--">上一页</button>
      <text
        >{{ page + 1 }} / {{ pageCount }} · 共
        {{ content.length.toLocaleString() }} 字符</text
      >
      <button size="mini" :disabled="page + 1 >= pageCount" @tap="page++">
        下一页
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import MarkdownIt from "markdown-it";
import { formatCardInlineMedia } from "@/utils/characterCard";
const props = withDefaults(
  defineProps<{ content?: string; source?: boolean; emptyText?: string }>(),
  { content: "", source: false, emptyText: "尚未填写" },
);
const page = ref(0);
const pageSize = 3000;
watch(
  () => props.content,
  () => {
    page.value = 0;
  },
);
const pageCount = computed(() =>
  Math.max(1, Math.ceil(props.content.length / pageSize)),
);
const pageText = computed(() =>
  props.content.slice(page.value * pageSize, (page.value + 1) * pageSize),
);
const md = new MarkdownIt({ html: false, breaks: true, linkify: true });
// 卡片中的远程图片只显示替代文字，阅读档案不会加载作者嵌入的追踪图片。
md.renderer.rules.image = (tokens, index) =>
  md.utils.escapeHtml(tokens[index].content || "[图片]");
const rendered = computed(() =>
  md
    .render(formatCardInlineMedia(pageText.value))
    .replace(/<p>/g, '<p style="margin:0 0 10px;">')
    .replace(
      /<pre>/g,
      '<pre style="white-space:pre-wrap;word-break:break-word;">',
    )
    .replace(
      /<table>/g,
      '<table style="max-width:100%;word-break:break-word;">',
    ),
);
</script>

<style scoped>
.card-reading {
  min-width: 0;
  color: var(--app-color-text-primary, #26332e);
}
.reading-hint {
  display: block;
  margin-bottom: 16rpx;
  font-size: 22rpx;
  color: var(--app-color-text-secondary, #7c8983);
}
.reading-viewport {
  height: 650rpx;
  max-height: 52vh;
}
.reading-text,
.source-text {
  display: block;
  font-size: 27rpx;
  line-height: 1.85;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.source-text {
  white-space: pre-wrap;
  font-family: monospace;
  padding: 24rpx;
  border-radius: 18rpx;
  background: var(--app-color-background, #f7f9f7);
  font-size: 24rpx;
}
.reading-empty {
  font-size: 24rpx;
  color: var(--app-color-text-secondary, #7c8983);
}
.reading-pages {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
  margin-top: 28rpx;
  padding-top: 20rpx;
  border-top: 1px solid var(--app-color-border, #e3e9e5);
}
.reading-pages text {
  font-size: 21rpx;
  color: var(--app-color-text-secondary, #7c8983);
  text-align: center;
}
.reading-pages button {
  margin: 0;
  flex-shrink: 0;
  font-size: 22rpx;
  color: var(--app-color-primary-strong, #4f8e7c);
  background: #f1f6f3;
}
</style>
