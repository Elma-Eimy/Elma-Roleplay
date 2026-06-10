<template>
  <view class="tree-view-container">
    <view v-if="sessionTreeRoots.length > 0" class="forest-container">
      <view 
        v-for="(root, index) in sessionTreeRoots" 
        :key="root.id" 
        class="tree-root-section"
      >
        <!-- 时空起源树标题分割线 -->
        <view class="tree-root-header">
          <view class="header-line"></view>
          <text class="header-title">独立宇宙时空线 #{{ sessionTreeRoots.length - index }}</text>
          <view class="header-line"></view>
        </view>
        
        <!-- 树根节点开始渲染 -->
        <view class="tree-content">
          <BranchTreeNode
            :node="root"
            :depth="0"
            :is-last="true"
            :latest-session-id="latestSessionId"
            @tap-node="emitTapNode"
            @longpress-node="emitLongpressNode"
            @branch-node="emitBranchNode"
          />
        </view>
      </view>
    </view>
    
    <view v-else class="empty-state">
      <text class="empty-text">暂无宇宙分支，开启全新平行宇宙！</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from "vue";
import BranchTreeNode from "./BranchTreeNode.vue";

interface Session {
  id: number;
  title: string;
  parent_session_id: number | null;
  created_at: string;
  updated_at: string;
  persona?: {
    id: number;
    affection_score?: number;
    current_mood?: string;
  };
  lastMessage?: string;
}

interface SessionNode extends Session {
  children: SessionNode[];
  depth: number;
}

const props = defineProps<{
  sessions: Session[];
}>();

const emit = defineEmits<{
  (e: 'tap-node', session: any): void;
  (e: 'longpress-node', session: any): void;
  (e: 'branch-node', session: any): void;
}>();

// 将扁平会话列表转换为时空森林（包含多个树）
const sessionTreeRoots = computed(() => {
  const list = props.sessions || [];
  if (list.length === 0) return [];

  const map: { [key: number]: SessionNode } = {};
  const roots: SessionNode[] = [];

  // 1. 初始化节点映射
  list.forEach(s => {
    map[s.id] = {
      ...s,
      children: [],
      depth: 0
    };
  });

  // 2. 将子节点关联到对应的父节点
  list.forEach(s => {
    const node = map[s.id];
    if (s.parent_session_id && map[s.parent_session_id]) {
      map[s.parent_session_id].children.push(node);
    } else {
      roots.push(node);
    }
  });

  // 3. 递归设置深度并对子分支按创建时间先后排序
  const setDepthAndSort = (node: SessionNode, depth: number) => {
    node.depth = depth;
    node.children.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
    node.children.forEach(child => setDepthAndSort(child, depth + 1));
  };

  roots.forEach(root => setDepthAndSort(root, 0));

  // 4. 按各个树的最新更新时间（树中任何分支的最晚活跃时间）降序排列
  roots.sort((a, b) => {
    const getNewestUpdateTime = (node: SessionNode): number => {
      let maxTime = new Date(node.updated_at).getTime();
      node.children.forEach(child => {
        const childMax = getNewestUpdateTime(child);
        if (childMax > maxTime) maxTime = childMax;
      });
      return maxTime;
    };
    return getNewestUpdateTime(b) - getNewestUpdateTime(a);
  });

  return roots;
});

// 计算哪个时空会话是最近活跃的
const latestSessionId = computed(() => {
  const list = props.sessions || [];
  if (list.length === 0) return null;
  let latest = list[0];
  let latestTime = new Date(latest.updated_at).getTime();
  
  list.forEach(s => {
    const time = new Date(s.updated_at).getTime();
    if (time > latestTime) {
      latest = s;
      latestTime = time;
    }
  });
  return latest.id;
});

const emitTapNode = (session: any) => emit('tap-node', session);
const emitLongpressNode = (session: any) => emit('longpress-node', session);
const emitBranchNode = (session: any) => emit('branch-node', session);
</script>

<style scoped>
.tree-view-container {
  width: 100%;
  display: flex;
  flex-direction: column;
}

.forest-container {
  display: flex;
  flex-direction: column;
  gap: 40rpx;
  padding: 0rpx 0rpx;
}

.tree-root-section {
  display: flex;
  flex-direction: column;
}

/* ===== 时空宇宙线的分隔条 ===== */
.tree-root-header {
  display: flex;
  align-items: center;
  margin-bottom: 28rpx;
  padding: 0 10rpx;
}

.header-line {
  flex: 1;
  height: 1px;
  background-color: rgba(0, 0, 0, 0.05);
}

.header-title {
  font-size: 24rpx;
  color: #8e8e93;
  font-weight: 600;
  padding: 0 20rpx;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.tree-content {
  display: flex;
  flex-direction: column;
  width: 100%;
}

.empty-state {
  display: flex;
  justify-content: center;
  padding: 120rpx 0;
}

.empty-text {
  font-size: 26rpx;
  color: #8e8e93;
}
</style>
