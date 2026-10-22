<template>
  <view class="role-state-panel">
    <view class="state-heading">
      <text class="state-title">当前状态</text>
      <button v-if="!editing" size="mini" :disabled="busy || generating || !snapshot" @tap="beginEdit">编辑</button>
    </view>
    <text class="state-hint">{{ generating ? '回复生成中，完成后更新状态。' : '未变化的状态会沿用；你可以手动校正。' }}</text>
    <text v-if="busy" class="state-hint">正在同步…</text>
    <view v-if="error" class="state-error"><text>{{ error }}</text><button v-if="!editing" size="mini" @tap="load">重试</button></view>
    <template v-if="editing">
      <text class="state-label">场景</text>
      <textarea v-model="scene" :maxlength="300" auto-height placeholder="未描述，留空可清除" :disabled="busy" />
      <view v-for="(actor, index) in actors" :key="actor.name" class="actor-state">
        <view class="state-heading"><text class="actor-name">{{ actor.name }}</text><button size="mini" :disabled="busy" @tap="actors.splice(index, 1)">清除</button></view>
        <text class="state-label">姿势</text><textarea v-model="actor.posture" :maxlength="200" auto-height placeholder="未描述" :disabled="busy" />
        <text class="state-label">衣着</text><textarea v-model="actor.clothing" :maxlength="200" auto-height placeholder="未描述" :disabled="busy" />
        <text class="state-label">位置</text><textarea v-model="actor.location" :maxlength="200" auto-height placeholder="未描述" :disabled="busy" />
      </view>
      <view class="add-actor"><input v-model="newName" :maxlength="50" placeholder="角色名称" :disabled="busy" /><button size="mini" :disabled="busy || actors.length >= 8" @tap="addActor">添加人物</button></view>
      <text class="state-hint">清除表示恢复为未知；模型之后仍可根据新剧情更新。</text>
      <view class="state-actions"><button :disabled="busy" @tap="cancel">取消</button><button :disabled="busy || generating" @tap="save">保存状态</button></view>
    </template>
    <template v-else-if="snapshot">
      <text class="state-line">场景：{{ snapshot.state.scene || '未描述' }}</text>
      <view v-for="(actor, name) in snapshot.state.characters || {}" :key="name" class="actor-state">
        <text class="actor-name">{{ name }}</text>
        <text class="state-line">姿势：{{ actor.posture || '未描述' }}</text>
        <text class="state-line">衣着：{{ actor.clothing || '未描述' }}</text>
        <text class="state-line">位置：{{ actor.location || '未描述' }}</text>
      </view>
      <text v-if="!Object.keys(snapshot.state.characters || {}).length" class="state-hint">暂无人物状态。可手动填写，或由后续剧情逐步补充。</text>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed, watch } from "vue";
import { useChatStore } from "@/store/chatStore";
import { useRoleState } from "@/composables/useRoleState";
const props = defineProps<{ sessionId: number | null }>();
const chatStore = useChatStore();
const generating = computed(() => chatStore.isLoading);
const { snapshot, busy, error, editing, scene, actors, newName, load, beginEdit, addActor, cancel, save } = useRoleState(() => props.sessionId, () => generating.value);
watch(() => [chatStore.isLoading, chatStore.messages.map(message => `${message.id}:${message.content}`).join('\u0000')], () => {
  if (!generating.value && !editing.value) void load();
});
</script>

<style scoped>
.role-state-panel { display: flex; flex-direction: column; gap: 16rpx; color: var(--app-color-text-primary, #26332e); }
.state-heading, .state-actions, .add-actor { display: flex; align-items: center; gap: 16rpx; justify-content: space-between; }
.state-title { font-size: 28rpx; font-weight: 600; }
.state-heading button, .add-actor button { margin: 0; flex-shrink: 0; }
.state-hint { display: block; font-size: 22rpx; line-height: 1.7; color: var(--app-color-text-secondary, #7c8983); }
.state-label, .actor-name { display: block; font-size: 24rpx; font-weight: 600; }
.state-line { display: block; font-size: 25rpx; line-height: 1.8; overflow-wrap: anywhere; }
.actor-state { padding: 18rpx; background: var(--app-color-surface-soft, #f3f6f3); border-radius: 16rpx; display: flex; flex-direction: column; gap: 10rpx; }
textarea, input { width: 100%; min-width: 0; box-sizing: border-box; padding: 16rpx; border: 1px solid var(--app-color-border, #e1e8e2); border-radius: 12rpx; background: var(--app-color-surface, #fff); font-size: 25rpx; }
.state-actions button { flex: 1; margin: 0; font-size: 25rpx; }
.state-actions button:last-child { background: var(--app-color-primary, #4f8e7c); color: #fff; }
.state-error { font-size: 23rpx; line-height: 1.7; color: var(--app-color-error, #a65542); }
</style>
