<template>
  <view class="group-page">
    <AppPageHeader title="群聊故事" eyebrow="GROUP STORIES" subtitle="让不同的角色在同一场景相遇" show-back>
      <template #action><view class="group-action" role="button" aria-label="新建群聊" @tap="create">新建</view></template>
    </AppPageHeader>
    <scroll-view class="group-scroll" scroll-y @scrolltolower="loadMore">
      <view class="group-content">
        <view class="group-notice"><text class="group-copy">目前可创建和查看群聊，角色互动将在后续开放。</text></view>
        <AppStatusState v-if="loading && !groups.length" kind="loading" title="正在读取群聊" />
        <AppStatusState v-else-if="error && !groups.length" kind="error" title="群聊加载失败" :description="error" action-label="重新加载" @action="refresh" />
        <AppStatusState v-else-if="!groups.length" kind="empty" title="还没有群聊故事" description="选择 2–3 名角色，设定他们共同的起点。" action-label="创建群聊" @action="create" />
        <template v-else>
          <view class="group-row"><text class="group-caption">共 {{ total }} 个群聊</text><view class="group-action" role="button" :aria-disabled="loading" @tap="refresh">刷新</view></view>
          <view v-for="group in groups" :key="group.session_id" class="group-card" role="button" :aria-label="`查看${group.title}`" @tap="open(group.session_id)">
            <text class="group-heading">{{ group.title }}</text>
            <view class="group-avatars"><AvatarImage v-for="member in group.members" :key="member.persona_id" class="group-avatar" :src="getAvatarUrl(member.character.avatar_path || '')" /></view>
            <text class="group-copy">{{ memberNames(group) }}</text>
            <view class="group-row"><text class="group-copy">{{ group.shared_setting || '未填写共同设定' }}</text><text class="group-caption">查看 ›</text></view>
          </view>
          <text v-if="error" class="group-error">{{ error }}</text>
          <view v-if="hasMore" class="group-action" role="button" :aria-disabled="loading" @tap="loadMore">{{ loading ? '正在读取…' : '加载更多' }}</view>
          <text v-else class="group-copy">已显示全部群聊</text>
        </template>
      </view>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { onShow, onHide, onUnload } from "@dcloudio/uni-app";
import AppPageHeader from "@/components/common/AppPageHeader.vue";
import AppStatusState from "@/components/common/AppStatusState.vue";
import AvatarImage from "@/components/common/AvatarImage.vue";
import { getAvatarUrl } from "@/api/characters";
import { useGroupSessionList } from "@/composables/useGroupSessions";
import type { GroupSessionDetail } from "@/types/groupSessions";

const state = useGroupSessionList();
const { groups, loading, error, total, hasMore } = state;
onShow(state.show); onHide(state.hide); onUnload(state.hide);
const refresh = () => state.load();
const loadMore = () => state.load(true);
const create = () => uni.navigateTo({ url: "/pages/group/create" });
const open = (id: number) => {
  if (groups.value.some(group => group.session_id === id)) uni.navigateTo({ url: `/pages/group/detail?sessionId=${id}` });
};
const memberNames = (group: GroupSessionDetail) => group.members.map(member => member.character.name).join(" · ");
</script>

<style scoped>
@import "./group.css";
</style>
