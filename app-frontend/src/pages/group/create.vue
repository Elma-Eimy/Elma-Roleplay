<template>
  <view class="group-page">
    <AppPageHeader title="创建群聊" eyebrow="NEW GROUP" subtitle="为这次相遇选择共同的起点" show-back />
    <scroll-view class="group-scroll" scroll-y>
      <view class="group-content">
        <view class="group-card">
          <text class="group-heading">故事起点</text>
          <text class="group-label">群聊标题</text>
          <input v-model="title" class="group-input" maxlength="50" placeholder="例如：雨夜的边境酒馆" :disabled="locked" aria-label="群聊标题" />
          <text class="group-label">你的昵称</text>
          <input v-model="nickname" class="group-input" maxlength="50" :disabled="locked" aria-label="你的昵称" />
          <text class="group-label">共同设定（选填）</text>
          <textarea v-model="sharedSetting" class="group-textarea" :maxlength="20000" :disabled="locked" placeholder="描述大家此刻共同身处的场景与背景" aria-label="共同设定" />
        </view>

        <view class="group-card">
          <view class="group-row"><text class="group-heading">选择角色</text><text class="group-caption">已选 {{ members.length }}/3</text></view>
          <text class="group-copy">选择 2–3 名角色，同一张角色卡不能重复加入。</text>
          <AppStatusState v-if="loadingCharacters && !characters.length" kind="loading" title="正在读取角色" />
          <AppStatusState v-else-if="characterError && !characters.length" kind="error" title="角色读取失败" :description="characterError" action-label="重新加载" @action="reloadCharacters" />
          <AppStatusState v-else-if="!characters.length" kind="empty" title="还没有角色" description="先到角色库创建角色，再回来邀请他们加入。" />
          <view v-for="character in characters" :key="character.id" class="character-option" :class="{ selected: selected(character.id) }" role="checkbox" :aria-checked="selected(character.id)" :aria-disabled="locked" @tap="state.toggleCharacter(character)">
            <AvatarImage class="group-avatar" :src="getAvatarUrl(character.avatar_path || '')" />
            <view class="character-copy"><text class="group-label">{{ character.name }}</text><text class="character-description">{{ character.description || '从角色卡设定开始' }}</text></view>
            <text class="selection-mark">{{ selected(character.id) ? '✓' : '＋' }}</text>
          </view>
          <text v-if="characterError && characters.length" class="group-error">{{ characterError }}</text>
          <view v-if="hasMoreCharacters" class="group-action" role="button" :aria-disabled="loadingCharacters || locked" @tap="moreCharacters">{{ loadingCharacters ? '正在读取…' : '加载更多角色' }}</view>
        </view>

        <view v-for="member in members" :key="member.character.id" class="group-card">
          <view class="group-row"><text class="group-heading">{{ member.character.name }}的起点</text><view class="group-action" role="button" :aria-disabled="locked" @tap="state.toggleCharacter(member.character)">移除</view></view>
          <picker :range="modeLabels" :value="member.mode === 'card' ? 0 : 1" :disabled="locked" @change="changeMode(member.character.id, $event)">
            <view class="group-picker">{{ member.mode === 'card' ? '从原卡开始' : '导入单聊快照' }}　⌄</view>
          </picker>
          <template v-if="member.mode === 'card'">
            <text class="group-copy">保留原卡设定，不导入私人对话与记忆。开场白对全体成员可见，保存后固定；请检查人物、场景和私密描写。</text>
            <text v-if="member.loadingGreeting" class="group-copy">正在读取开场…</text>
            <template v-if="member.greetingLoaded">
              <picker :range="member.greetings" range-key="title" :value="member.greetingIndex" :disabled="locked" @change="state.selectGreeting(member, Number($event.detail.value))">
                <view class="group-picker">{{ member.greetings[member.greetingIndex]?.title || '默认开场' }}　⌄</view>
              </picker>
              <textarea v-model="member.greetingContent" class="group-textarea" :maxlength="20000" :disabled="locked" placeholder="预览并编辑开场；清空可跳过" :aria-label="member.character.name + '的公开开场'" />
            </template>
            <text v-if="member.greetingError" class="group-error">{{ member.greetingError }}</text>
            <button v-if="member.greetingError" class="group-action" :disabled="locked || member.loadingGreeting" @tap="state.loadGreetings(member)">重新读取开场</button>
          </template>
          <template v-else>
            <text class="group-copy">导入当前已保存状态与记忆，不插入开场白，等待你的第一条消息。原单聊后续变化不会影响群聊起点。</text>
            <text v-if="member.loadingSources" class="group-copy">正在读取来源故事…</text>
            <picker v-if="member.sources.length" :range="member.sources" range-key="title" :value="sourceIndex(member.character.id)" :disabled="locked || member.loadingSources" @change="selectSource(member.character.id, $event)">
              <view class="group-picker">{{ sourceTitle(member.character.id) }}　⌄</view>
            </picker>
            <text v-else-if="!member.loadingSources && !member.sourceError" class="group-copy">该角色还没有单聊故事，请改为从原卡开始。</text>
            <text v-if="member.sourceError" class="group-error">{{ member.sourceError }}</text>
            <view v-if="member.sourceError || member.hasMoreSources" class="group-action" role="button" :aria-disabled="locked || member.loadingSources" @tap="state.loadSources(member, member.sources.length > 0)">{{ member.sourceError ? '重新读取来源' : '加载更多来源故事' }}</view>
          </template>
        </view>
        <view class="group-notice"><text class="group-copy">{{ supportsSnapshots ? '成员与共同设定在创建后固定。创建后可进入故事，输入你的第一句台词或行动。' : '离线模式仅支持原卡起步与查看，不支持导入单聊快照或生成角色互动。' }}</text></view>
        <text v-if="error" class="group-error" role="alert">{{ error }}</text>
        <text v-else-if="validation" class="group-copy">{{ validation }}</text>
        <AppPrimaryButton label="创建群聊" loading-text="正在创建" :block="true" :loading="submitting" :disabled="locked || !!validation" @tap="state.submit" />
        <view v-if="uncertain" class="group-action" role="button" @tap="backToList">查看群聊列表</view>
        <view v-if="created" class="group-action" role="button" @tap="openCreated">查看已创建的群聊</view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { onShow, onHide, onUnload } from "@dcloudio/uni-app";
import AppPageHeader from "@/components/common/AppPageHeader.vue";
import AppStatusState from "@/components/common/AppStatusState.vue";
import AppPrimaryButton from "@/components/common/AppPrimaryButton.vue";
import AvatarImage from "@/components/common/AvatarImage.vue";
import { getAvatarUrl } from "@/api/characters";
import { useGroupSessionCreate } from "@/composables/useGroupSessions";

const state = useGroupSessionCreate(group => uni.redirectTo({ url: `/pages/group/detail?sessionId=${group.session_id}` }));
const { title, nickname, sharedSetting, characters, members, loadingCharacters, hasMoreCharacters,
  characterError, submitting, error, uncertain, created, locked, validation, supportsSnapshots } = state;
const modeLabels = supportsSnapshots ? ["从原卡开始", "导入单聊快照"] : ["从原卡开始"];
onShow(state.show); onHide(state.hide); onUnload(state.hide);
const selected = (id: number) => members.value.some(member => member.character.id === id);
const reloadCharacters = () => state.loadCharacters();
const moreCharacters = () => { if (!locked.value) void state.loadCharacters(true); };
const changeMode = (id: number, event: { detail: { value: string | number } }) => {
  const member = members.value.find(item => item.character.id === id);
  if (member) state.setMode(member, Number(event.detail.value) === 0 ? "card" : "single_snapshot");
};
const selectSource = (id: number, event: { detail: { value: string | number } }) => {
  if (locked.value) return;
  const member = members.value.find(item => item.character.id === id);
  if (member) member.sourceSessionId = member.sources[Number(event.detail.value)]?.id ?? null;
};
const sourceTitle = (id: number) => {
  const member = members.value.find(item => item.character.id === id);
  return member?.sources.find(source => source.id === member.sourceSessionId)?.title || "请选择来源单聊";
};
const sourceIndex = (id: number) => {
  const member = members.value.find(item => item.character.id === id);
  return Math.max(0, member?.sources.findIndex(source => source.id === member.sourceSessionId) ?? 0);
};
const backToList = () => uni.navigateBack({ fail: () => uni.redirectTo({ url: "/pages/group/index" }) });
const openCreated = () => { if (created.value) uni.redirectTo({ url: `/pages/group/detail?sessionId=${created.value.session_id}` }); };
</script>

<style scoped>
@import "./group.css";
.character-option { display: flex; align-items: center; gap: 20rpx; padding: 20rpx 12rpx; margin-top: 16rpx; border: 1px solid var(--app-color-border); border-radius: var(--app-radius-sm); }
.character-option.selected { background: var(--app-color-primary-soft); border-color: var(--app-color-primary); }
.character-copy { flex: 1; min-width: 0; }
.character-copy .group-label { margin: 0 0 8rpx; }
.character-description { display: block; color: var(--app-color-text-secondary); font-size: var(--app-font-size-caption); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selection-mark { color: var(--app-color-primary-strong); font-size: 34rpx; padding: 12rpx; }
</style>
