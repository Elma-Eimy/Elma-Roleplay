<template>
  <scroll-view scroll-y :scroll-into-view="scrollTarget" class="consolidation-panel">
    <view class="intro">
      <text class="heading">让记忆更清楚，保留故事细节</text>
      <text class="description">每批检查当前故事最多 100 张有效原卡，寻找重复内容和同一次经历的碎片。先查看建议，再选择应用；原卡保留，可撤销。继承记忆暂不参与整理。</text>
      <text v-if="scanStatus" class="hint">当前有效原卡 {{ scanStatus.eligible_count }} 张 · 当前版本已检查 {{ scanStatus.checked_count }} 张 · 新增或变更待检 {{ scanStatus.pending_count }} 张</text>
      <button class="primary" :disabled="busy" @tap="preview(0, 'incremental')">{{ busy ? '正在处理，请稍候…' : '检查新增与变更' }}</button>
      <button :disabled="busy" @tap="preview(0, 'full')">重新检查全部</button>
      <text class="hint">增量检查仅比较本批新增或变更的卡片，不会关联已检查的旧卡。已检查不代表已应用；以前的建议仍保留在整理记录中。重新检查全部也会分批进行。</text>
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
      <text class="hint">检查范围：{{ current.scan_mode === 'incremental' ? '新增与变更' : '全部原卡（分批）' }}</text>
      <text v-if="current.model_checked === false && current.scanned_count === 1" class="description">本批只有 1 张待检卡，未调用模型，也未记录为已检查；新增其他卡后可再次检查。</text>
      <text v-else-if="!current.scanned_count" class="description">{{ current.scan_mode === 'incremental' ? '没有新增或变更的待检记忆。' : '当前范围没有可检查的原卡。' }}</text>
      <text v-if="current.model_checked && current.recorded_count !== undefined && current.recorded_count < current.scanned_count" class="hint">部分原卡在检查期间发生变化，仍需重新检查。</text>
      <text v-if="current.status === 'applied'" class="description">所选原卡已收起到历史原卡，聊天优先检索整理结果。来源和正文仍保留在下方。</text>
      <text v-if="current.status === 'undone'" class="description">当前故事已恢复原卡。此前分叉的故事继续保留各自的整理状态。</text>
      <text v-if="!current.groups.length && current.scanned_count >= 2" class="description">这批没有发现可以稳妥合并的记忆，原卡保持原样；已检查记录会保留。</text>

      <view v-for="group in current.groups" :key="group.id" class="group">
        <view class="row" @tap="toggle(group.id)">
          <text class="group-title">{{ group.kind === 'duplicate' ? '重复内容' : '同一次经历' }} · {{ group.source_ids.length }} 张原卡</text>
          <text v-if="current.status === 'preview'" class="selection" :class="{ checked: selected.includes(group.id) }">{{ group.conflict ? '存在冲突' : group.ignored ? '已忽略' : selected.includes(group.id) ? '✓ 已选择' : '○ 选择' }}</text>
          <text v-else class="hint">{{ current.selected_group_ids.includes(group.id) ? '已选建议' : '未应用' }}</text>
        </view>
        <text class="reason">{{ group.reason }}</text>
        <text v-if="group.conflict" class="conflict">{{ group.conflict }}</text>
        <text v-if="group.ignored" class="hint">已忽略此组{{ group.ignore_reason ? '：' + group.ignore_reason : '' }}（仅本次预览）</text>
        <text v-else-if="group.ignore_reason" class="hint">审阅备注：{{ group.ignore_reason }}</text>
        <text class="label">整理后</text>
        <text class="result">{{ group.content }}</text>
        <view v-if="group.original_content && group.original_content !== group.content" class="source">
          <text class="label">模型原稿</text>
          <text class="source-content">{{ group.original_content }}</text>
        </view>
        <view v-if="current.status === 'preview'" class="review-actions">
          <button v-if="editingId !== group.id" size="mini" :disabled="busy" @tap="editGroup(group.id)">编辑 / 忽略此组</button>
          <view v-else class="editor">
            <text class="hint">核对原卡后修改正文，保留时间、人物、条件和承诺。保存不会改变原卡。</text>
            <textarea v-model="draftContent" :disabled="busy || !!group.conflict" :maxlength="500" auto-height class="review-input" />
            <text class="hint">{{ draftContent.length }} / 500 字符</text>
            <view class="row">
              <text class="label">忽略此组（可恢复）</text>
              <switch :checked="draftIgnored" :disabled="busy" @change="changeIgnored" />
            </view>
            <textarea v-model="draftReason" :disabled="busy" :maxlength="160" auto-height placeholder="忽略原因或审阅备注（选填）" class="review-input" />
            <view class="row">
              <button size="mini" :disabled="busy" @tap="saveReview">保存审阅</button>
              <button size="mini" :disabled="busy" @tap="editingId = null">取消</button>
            </view>
          </view>
        </view>
        <text class="label">原卡与来源</text>
        <view v-for="source in groupSources(group.source_ids)" :key="source.id" class="source">
          <text class="source-content">{{ source.content }}</text>
          <text class="hint">原卡 #{{ source.id }} · {{ sourceLabel(source) }}</text>
        </view>
      </view>

      <button v-if="current.status === 'preview' && current.groups.length" class="primary" :disabled="busy || !selected.length || editingId !== null" @tap="apply">应用所选 {{ selected.length }} 组建议</button>
      <button v-if="current.status === 'applied'" :disabled="busy" @tap="undo(current)">撤销本次整理</button>
      <button v-if="current.has_more" :disabled="busy" @tap="continueScan">继续检查此范围的记忆</button>
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
const { batches, current, selected, busy, error, historyHasMore, scanStatus, choose, toggle, load, loadMoreHistory, preview, continueScan, apply, undo,
  editingId, draftContent, draftReason, draftIgnored, editGroup, saveReview } =
  useMemoryConsolidation(() => props.sessionId, () => emit("changed"));
const scrollTarget = ref("");
const changeIgnored = (event: Event) => {
  draftIgnored.value = (event as unknown as { detail: { value: boolean } }).detail.value;
};
const review = async (batch: MemoryConsolidation) => {
  if (busy.value) return;
  if (!choose(batch)) return;
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
.editor { display: flex; flex-direction: column; gap: 16rpx; }
.review-input { box-sizing: border-box; width: 100%; min-height: 90rpx; padding: 16rpx; font-size: 25rpx; line-height: 1.7; color: var(--text-primary, #333); background: var(--bg-color, #f4f5f8); border-radius: 12rpx; }
.conflict { font-size: 24rpx; line-height: 1.6; color: var(--text-danger, #a03524); }
button { margin: 0; font-size: 25rpx; border-radius: 14rpx; }
.primary { background: var(--primary-color, #1c1c1e); color: white; }
.primary[disabled] { opacity: .45; }
.error-box { margin: 16rpx 30rpx; padding: 20rpx; background: #fff1ee; color: #a03524; font-size: 24rpx; line-height: 1.6; border-radius: 14rpx; }
.history { padding-bottom: calc(36rpx + env(safe-area-inset-bottom)); }
.history-item { display: flex; flex-direction: column; gap: 10rpx; padding: 20rpx 0; font-size: 24rpx; border-bottom: 1px solid var(--border-color, #e5e5ea); }
</style>
