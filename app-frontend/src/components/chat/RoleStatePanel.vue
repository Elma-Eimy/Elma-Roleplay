<template>
  <view class="role-state-panel">
    <view class="state-heading">
      <view
        class="state-heading-left"
        role="button"
        :aria-expanded="!collapsed"
        @tap="collapsed = editing ? false : !collapsed"
      >
        <text class="state-title">当前状态</text>
        <text v-if="busy" class="state-sync-pill">同步中…</text>
        <image
          v-if="!editing"
          class="state-chevron"
          :class="{ 'is-active': !collapsed }"
          src="/static/icons/settings_chevron.svg"
          mode="aspectFit"
        />
      </view>
      <button
        v-if="!editing"
        class="state-btn state-btn-soft"
        :disabled="busy || generating || !snapshot"
        @tap.stop="beginEdit()"
      >
        编辑
      </button>
    </view>
    <text class="state-hint">
      <template v-if="collapsed && !editing && snapshot">
        场景：{{ snapshot.state.scene || '未描述' }} · {{ Object.keys(snapshot.state.characters || {}).length }} 人 · 点击展开
      </template>
      <template v-else>
        {{ generating ? '回复生成中，完成后更新状态。' : '未变化的状态会沿用；你可以手动校正。' }}
      </template>
    </text>
    <view v-if="error" class="state-error">
      <text class="state-error-text">{{ error }}</text>
      <button v-if="!editing" class="state-btn state-btn-retry" @tap="load">重试</button>
    </view>
    <template v-if="editing">
      <text class="state-label">场景</text>
      <textarea v-model="scene" :maxlength="300" auto-height placeholder="未描述，留空可清除" :disabled="busy" />
      <view v-for="(actor, index) in actors" :key="actor.name" class="actor-state">
        <view class="state-heading">
          <text class="actor-name">{{ actor.name }}</text>
          <button class="state-btn state-btn-danger" :disabled="busy" @tap="actors.splice(index, 1)">清除</button>
        </view>
        <text class="state-label">姿势</text><textarea v-model="actor.posture" :maxlength="200" auto-height placeholder="未描述" :disabled="busy" />
        <text class="state-label">衣着</text><textarea v-model="actor.clothing" :maxlength="200" auto-height placeholder="未描述" :disabled="busy" />
        <text class="state-label">位置</text><textarea v-model="actor.location" :maxlength="200" auto-height placeholder="未描述" :disabled="busy" />
      </view>
      <view class="add-actor">
        <input v-model="newName" :maxlength="50" placeholder="角色名称" :disabled="busy" />
        <button class="state-btn state-btn-soft" :disabled="busy || actors.length >= 8" @tap="addActor">添加人物</button>
      </view>
      <text class="state-hint">清除表示恢复为未知；模型之后仍可根据新剧情更新。</text>
      <view class="state-actions">
        <button class="state-btn state-btn-ghost" :disabled="busy" @tap="cancel">取消</button>
        <button class="state-btn state-btn-primary" :disabled="busy || generating" @tap="save">保存状态</button>
      </view>
    </template>
    <template v-else-if="snapshot && !collapsed">
      <view class="state-scene-card">
        <text class="state-line"><text class="state-line-key">场景：</text>{{ snapshot.state.scene || '未描述' }}</text>
      </view>
      <view v-for="(actor, name) in snapshot.state.characters || {}" :key="name" class="actor-state">
        <text class="actor-name">{{ name }}</text>
        <text class="state-line"><text class="state-line-key">姿势：</text>{{ actor.posture || '未描述' }}</text>
        <text class="state-line"><text class="state-line-key">衣着：</text>{{ actor.clothing || '未描述' }}</text>
        <text class="state-line"><text class="state-line-key">位置：</text>{{ actor.location || '未描述' }}</text>
      </view>
      <text v-if="!Object.keys(snapshot.state.characters || {}).length" class="state-hint">暂无人物状态。可手动填写，或由后续剧情逐步补充。</text>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useChatStore } from "@/store/chatStore";
import { useRoleState } from "@/composables/useRoleState";
const props = defineProps<{ sessionId: number | null }>();
const collapsed = ref(false);
const chatStore = useChatStore();
const generating = computed(() => chatStore.isLoading);
const { snapshot, busy, error, editing, scene, actors, newName, load, beginEdit, addActor, cancel, save } = useRoleState(() => props.sessionId, () => generating.value);
watch(() => [chatStore.isLoading, chatStore.messages.map(message => `${message.id}:${message.content}`).join('\u0000')], () => {
  if (!generating.value && !editing.value) void load();
});
</script>

<style scoped>
.role-state-panel {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  color: var(--app-color-text-primary, #26332e);
}

.role-state-panel button::after {
  border: 0;
  display: none;
}

.state-heading,
.state-actions,
.add-actor {
  display: flex;
  align-items: center;
  gap: 14rpx;
  justify-content: space-between;
}

.state-heading-left {
  display: flex;
  align-items: center;
  gap: 10rpx;
  min-width: 0;
  cursor: pointer;
}

.state-title {
  font-size: 28rpx;
  font-weight: 700;
}

.state-chevron {
  width: 26rpx;
  height: 26rpx;
  opacity: 0.55;
  transition: transform 0.22s ease;
}

.state-chevron.is-active {
  transform: rotate(180deg);
}

.state-sync-pill {
  padding: 2rpx 12rpx;
  border-radius: 999rpx;
  background: rgba(38, 51, 46, 0.06);
  color: var(--app-color-text-secondary, #7c8983);
  font-size: 20rpx;
  line-height: 1.4;
}

.state-btn {
  margin: 0;
  padding: 0 22rpx;
  height: 52rpx;
  min-width: 0;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  font-size: 23rpx;
  font-weight: 600;
  line-height: 1;
  border-radius: 999rpx;
  border: none;
  box-sizing: border-box;
}

.state-btn[disabled] {
  opacity: 0.48;
}

.state-btn-soft {
  background: rgba(112, 174, 155, 0.15);
  color: #3b7666;
}

.state-btn-ghost {
  background: #f1f5f2;
  color: #55635d;
}

.state-btn-danger {
  height: 46rpx;
  padding: 0 18rpx;
  font-size: 22rpx;
  background: rgba(217, 101, 93, 0.1);
  color: #c6534c;
}

.state-btn-retry {
  height: 46rpx;
  padding: 0 18rpx;
  font-size: 22rpx;
  background: rgba(217, 101, 93, 0.14);
  color: #b94646;
}

.state-btn-primary {
  background: var(--app-color-primary, #62a390);
  color: #ffffff;
}

.state-hint {
  display: block;
  font-size: 22rpx;
  line-height: 1.6;
  color: var(--app-color-text-secondary, #7c8983);
}

.state-label,
.actor-name {
  display: block;
  font-size: 24rpx;
  font-weight: 600;
  color: #2f3b36;
}

.state-scene-card {
  padding: 14rpx 18rpx;
  background: var(--app-color-surface-soft, #f3f6f4);
  border-radius: 14rpx;
}

.state-line {
  display: block;
  font-size: 24rpx;
  line-height: 1.7;
  color: #3d4b45;
  overflow-wrap: anywhere;
}

.state-line-key {
  color: #6f7e77;
  font-weight: 500;
}

.actor-state {
  padding: 16rpx 18rpx;
  background: var(--app-color-surface-soft, #f3f6f4);
  border-radius: 16rpx;
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

textarea,
input {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding: 14rpx 16rpx;
  border: 2rpx solid var(--app-color-border, #e1e8e2);
  border-radius: 12rpx;
  background: var(--app-color-surface, #fff);
  font-size: 24rpx;
}

.add-actor input {
  flex: 1;
  height: 64rpx;
  padding: 0 16rpx;
}

.state-actions .state-btn {
  flex: 1;
  height: 60rpx;
  border-radius: 14rpx;
  font-size: 24rpx;
}

.state-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12rpx;
  padding: 12rpx 16rpx;
  border-radius: 12rpx;
  background: rgba(217, 101, 93, 0.08);
  font-size: 22rpx;
  line-height: 1.5;
  color: var(--app-color-error, #a65542);
}

.state-error-text {
  flex: 1;
  min-width: 0;
}
</style>
