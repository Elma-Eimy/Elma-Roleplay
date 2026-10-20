<template>
  <scroll-view scroll-y :scroll-into-view="scrollTarget" class="consolidation-panel">
    <view class="intro">
      <text class="heading">让记忆更清楚，保留故事细节</text>
      <text class="description">每批检查当前故事最多 80 张有效原卡，寻找重复内容和同一次经历的碎片。先查看建议，再选择应用；原卡保留，可撤销。继承记忆暂不参与整理。</text>
      <button class="primary" :disabled="busy" @tap="preview(0)">{{ busy ? '正在处理，请稍候…' : '生成整理预览' }}</button>
      <text v-if="busy" class="hint">模型整理可能需要一些时间，关闭后可重新进入查看已保存的记录。</text>
    </view>

    <view v-if="error" class="error-box">
      <text>{{ error }}</text>
      <button size="mini" :disabled="busy" @tap="load">刷新整理记录</button>
    </view>

    <view v-if="current" id="memory-consolidation-current" class="batch">
      <view class="row">
        <text class="heading">{{ statusLabel(current.status) }}</text>
        <text class="hint">检查 {{ current.scanned_count }} / {{ current.remaining_count }} 张待检原卡</text>
      </view>
      <text v-if="current.status === 'applied'" class="description">所选原卡已收起到历史原卡，聊天优先检索整理结果。来源和正文仍保留在下方。</text>
      <text v-if="current.status === 'undone'" class="description">当前故事已恢复原卡。此前分叉的故事继续保留各自的整理状态。</text>
      <text v-if="!current.groups.length" class="description">这批没有发现可以稳妥合并的记忆，原卡保持原样。</text>

      <view v-for="group in current.groups" :key="group.id" class="group">
        <view class="row" @tap="toggle(group.id)">
          <text class="group-title">{{ group.kind === 'duplicate' ? '重复内容' : '同一次经历' }} · {{ group.source_ids.length }} 张原卡</text>
          <text v-if="current.status === 'preview'" class="selection" :class="{ checked: selected.includes(group.id) }">{{ selected.includes(group.id) ? '✓ 已选择' : '○ 选择' }}</text>
          <text v-else class="hint">{{ current.selected_group_ids.includes(group.id) ? '已选建议' : '未应用' }}</text>
        </view>
        <text class="reason">{{ group.reason }}</text>
        <text class="label">整理后</text>
        <text class="result">{{ group.content }}</text>
        <text class="label">原卡与来源</text>
        <view v-for="source in groupSources(group.source_ids)" :key="source.id" class="source">
          <text class="source-content">{{ source.content }}</text>
          <text class="hint">原卡 #{{ source.id }} · {{ sourceLabel(source) }}</text>
        </view>
      </view>

      <button v-if="current.status === 'preview' && current.groups.length" class="primary" :disabled="busy || !selected.length" @tap="apply">应用所选 {{ selected.length }} 组建议</button>
      <button v-if="current.status === 'applied'" :disabled="busy" @tap="undo(current)">撤销本次整理</button>
      <button v-if="current.has_more" :disabled="busy" @tap="preview(current.next_after_id)">继续检查后面的记忆</button>
      <text v-if="current.has_more" class="hint">本批建议已保存，可从下方记录重新打开。</text>
    </view>

    <view v-if="batches.length" class="history">
      <text class="heading">整理记录</text>
      <view v-for="batch in batches" :key="batch.id" class="history-item" @tap="review(batch)">
        <text>#{{ batch.id }} · {{ statusLabel(batch.status) }} · {{ batch.groups.length }} 组建议</text>
        <text class="hint">{{ formatDate(batch.created_at) }}</text>
      </view>
      <button v-if="historyHasMore" :disabled="busy" @tap="loadMoreHistory">查看更早的整理记录</button>
    </view>
  </scroll-view>
</template>

<script setup lang="ts">
import { ref, nextTick } from "vue";
import { useMemoryConsolidation } from "@/composables/useMemoryConsolidation";
import type { ConsolidationSource, MemoryConsolidation } from "@/types/memories";
const props = defineProps<{ sessionId: number }>();
const emit = defineEmits<{ (event: "changed"): void }>();
const { batches, current, selected, busy, error, historyHasMore, choose, toggle, load, loadMoreHistory, preview, apply, undo } =
  useMemoryConsolidation(() => props.sessionId, () => emit("changed"));
const scrollTarget = ref("");
const review = async (batch: MemoryConsolidation) => {
  if (busy.value) return;
  choose(batch);
  scrollTarget.value = "";
  await nextTick();
  scrollTarget.value = "memory-consolidation-current";
};
const statusLabel = (status: MemoryConsolidation["status"]) => ({ preview: "待审阅", applied: "已应用", undone: "已撤销" }[status]);
const groupSources = (ids: number[]) => current.value?.sources.filter(source => ids.includes(source.id)) || [];
const sourceLabel = (source: ConsolidationSource) => {
  if (!source.source_message_id) return "手动记录或来源未标注";
  const start = source.source_start_message_id || source.source_message_id;
  return start === source.source_message_id ? `消息 #${start}` : `消息 #${start}–#${source.source_message_id}`;
};
const formatDate = (value: string | null) => value ? value.replace("T", " ").slice(0, 16) : "";
</script>

<style scoped>
.consolidation-panel { flex: 1; min-height: 0; height: 0; background: var(--bg-color, #f8f8fa); }
.intro, .batch, .history { padding: 24rpx 30rpx; display: flex; flex-direction: column; gap: 18rpx; }
.heading { font-size: 27rpx; font-weight: 600; color: var(--text-primary, #1c1c1e); }
.description, .source-content, .result { font-size: 25rpx; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--text-primary, #333); }
.hint, .reason { font-size: 22rpx; line-height: 1.5; color: var(--text-secondary, #6b6b73); }
.row { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14rpx; }
.group { display: flex; flex-direction: column; gap: 16rpx; padding: 24rpx; border: 1px solid var(--border-color, #e5e5ea); border-radius: 18rpx; background: var(--bg-card, white); }
.group-title { font-size: 25rpx; font-weight: 600; }
.selection { padding: 12rpx 6rpx; font-size: 24rpx; color: var(--text-secondary, #777); }
.selection.checked { color: var(--primary-color, #576b95); font-weight: 600; }
.label { font-size: 21rpx; color: var(--text-secondary, #777); }
.result { padding: 18rpx; border-radius: 12rpx; background: var(--bg-color, #f4f5f8); }
.source { display: flex; flex-direction: column; gap: 8rpx; padding-top: 14rpx; border-top: 1px solid var(--border-color, #eee); }
button { margin: 0; font-size: 25rpx; border-radius: 14rpx; }
.primary { background: var(--primary-color, #1c1c1e); color: white; }
.primary[disabled] { opacity: .45; }
.error-box { margin: 16rpx 30rpx; padding: 20rpx; background: #fff1ee; color: #a03524; font-size: 24rpx; line-height: 1.6; border-radius: 14rpx; }
.history { padding-bottom: calc(36rpx + env(safe-area-inset-bottom)); }
.history-item { display: flex; flex-direction: column; gap: 10rpx; padding: 20rpx 0; font-size: 24rpx; border-bottom: 1px solid var(--border-color, #e5e5ea); }
</style>
