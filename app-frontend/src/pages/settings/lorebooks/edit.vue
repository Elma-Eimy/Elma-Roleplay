<template>
  <view class="page-container" :class="{ 'is-android': isAndroid }">
    <!-- 导航栏 -->
    <view class="nav-bar">
      <view class="back-btn" @tap="goBack">
        <image class="back-icon" src="/static/icons/header_back.svg" mode="aspectFit" />
      </view>
      <text class="nav-title">编辑设定集</text>
      <view class="save-header-btn" @tap="saveAll">保存</view>
    </view>

    <!-- 滚动区域 -->
    <scroll-view scroll-y class="scroll-container" v-if="lorebook">
      <view class="content-panel">
        
        <!-- 基础配置组 -->
        <view class="card-group">
          <text class="group-title">基础设定</text>
          
          <view class="form-item">
            <text class="label">名称 *</text>
            <input class="input" v-model="lorebook.name" placeholder="例如：霍格沃茨设定集..." />
          </view>
          
          <view class="form-item">
            <text class="label">描述</text>
            <textarea class="textarea-small" v-model="lorebook.description" placeholder="输入这本世界书设定集的整体背景说明..." />
          </view>
        </view>

        <!-- 高级检索配置组 -->
        <view class="card-group">
          <view class="group-header" @tap="showAdvanced = !showAdvanced">
            <text class="group-title">高级检索控制 (覆盖全局)</text>
            <image 
              class="caret-icon" 
              :src="showAdvanced ? '/static/icons/char_caret_up.svg' : '/static/icons/char_caret_down.svg'" 
              mode="aspectFit" 
            />
          </view>

          <view class="advanced-fields" v-if="showAdvanced">
            <view class="form-item border-bottom">
              <view class="form-item-left">
                <text class="label">扫描历史深度 (Scan Depth)</text>
                <text class="label-desc">匹配时向前扫描的聊天轮数。留空或填0将回退到全局默认配置。</text>
              </view>
              <view class="stepper">
                <view class="step-btn" @tap="stepParam('scan_depth', -1, 0, 50)">-</view>
                <text class="step-value">{{ lorebook.scan_depth !== null && lorebook.scan_depth !== undefined ? lorebook.scan_depth : '默认' }}</text>
                <view class="step-btn" @tap="stepParam('scan_depth', 1, 0, 50)">+</view>
              </view>
            </view>

            <view class="form-item border-bottom">
              <view class="form-item-left">
                <text class="label">Token 预算 (Token Budget)</text>
                <text class="label-desc">单次检索所能消耗的最大字符数限制。留空或填0将回退到全局设置。</text>
              </view>
              <view class="stepper-large">
                <view class="step-btn" @tap="stepParam('token_budget', -500, 0, 10000)">-</view>
                <text class="step-value">{{ lorebook.token_budget !== null && lorebook.token_budget !== undefined ? lorebook.token_budget : '默认' }}</text>
                <view class="step-btn" @tap="stepParam('token_budget', 500, 0, 10000)">+</view>
              </view>
            </view>

            <view class="form-item">
              <view class="form-item-left">
                <text class="label">递归检索 (Recursive Scanning)</text>
                <text class="label-desc">命中条目的设定内容中如果含有其它词条的关键字，是否继续递归触发。</text>
              </view>
              <view 
                class="custom-toggle"
                :class="{ 'is-on': lorebook.recursive_scanning }"
                @tap="toggleRecursive"
              >
                <view class="toggle-thumb"></view>
              </view>
            </view>
          </view>
        </view>

        <!-- 条目列表标题与添加按钮 -->
        <view class="entries-header-row">
          <text class="entries-section-title">设定条目 ({{ filteredEntries.length }} / {{ lorebook.entries.length }})</text>
          <view class="add-entry-btn" @tap="openAddEntryModal">
            <image class="add-icon" src="/static/icons/header_plus.svg" mode="aspectFit" />
            <text class="add-text">添加条目</text>
          </view>
        </view>

        <!-- 搜索过滤栏 -->
        <view class="search-bar-row" v-if="lorebook.entries.length > 0">
          <input 
            class="search-input" 
            v-model="searchQuery" 
            placeholder="搜索关键字或内容..." 
            confirm-type="search"
          />
          <text class="clear-search-btn" v-if="searchQuery" @tap="searchQuery = ''">×</text>
        </view>

        <!-- 条目列表 -->
        <view class="entries-list" v-if="filteredEntries.length > 0">
          <view 
            class="entry-item-card"
            v-for="(entry, index) in filteredEntries"
            :key="index"
            :class="{ 'is-disabled': !entry.enabled }"
          >
            <view class="entry-card-header">
              <view class="entry-keys">
                <text class="entry-key-tag" v-for="key in entry.keys" :key="key">{{ key }}</text>
                <text class="entry-key-tag constant-badge" v-if="entry.constant">常驻</text>
              </view>
              
              <view class="entry-switch-row">
                <view 
                  class="custom-toggle small"
                  :class="{ 'is-on': entry.enabled }"
                  @tap="toggleEntryEnabled(entry)"
                >
                  <view class="toggle-thumb"></view>
                </view>
              </view>
            </view>

            <text class="entry-body">{{ entry.content }}</text>

            <view class="entry-meta-info" v-if="entry.selective || entry.insertion_order !== 100">
              <text class="meta-item" v-if="entry.selective">条件触发 (二级过滤: {{ entry.secondary_keys.join(', ') }})</text>
              <text class="meta-item">优先级: {{ entry.insertion_order }}</text>
              <text class="meta-item">位置: {{ entry.position === 'before_char' ? '人设前' : '人设后' }}</text>
            </view>

            <view class="entry-card-actions">
              <view class="action-item edit" @tap="openEditEntryModal(entry)">
                <image class="action-icon" src="/static/icons/char_pencil.svg" mode="aspectFit" />
                <text class="action-text">编辑</text>
              </view>
              <view class="action-item delete" @tap="deleteEntry(entry)">
                <image class="action-icon" src="/static/icons/drawer_trash.svg" mode="aspectFit" />
                <text class="action-text danger">删除</text>
              </view>
            </view>
          </view>
        </view>
        
        <view class="empty-entries" v-else>
          <text class="empty-entries-text">
            {{ lorebook.entries.length > 0 ? '未找到匹配的设定条目。' : '该设定集尚未添加任何条目，点击“添加条目”进行配置。' }}
          </text>
        </view>

      </view>
    </scroll-view>

    <!-- 底部保存按钮 -->
    <view class="footer" v-if="lorebook">
      <view class="footer-save-btn" @tap="saveAll">
        <text class="save-btn-text">保存全部修改</text>
      </view>
    </view>

    <!-- 条目添加/修改模态框 -->
    <LorebookEntryModal
      :isOpen="isModalOpen"
      :entry="editingEntryIndex !== null && lorebook ? lorebook.entries[editingEntryIndex] : null"
      @close="closeModal"
      @save="onSaveEntry"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { getLorebook, updateLorebook } from "@/api/lorebooks";
import type { LorebookDetail, LorebookEntry } from "@/api/lorebooks";
import LorebookEntryModal from "./LorebookEntryModal.vue";

const lorebookId = ref<number | null>(null);
const lorebook = ref<LorebookDetail | null>(null);
const showAdvanced = ref(false);
const searchQuery = ref("");

const filteredEntries = computed(() => {
  if (!lorebook.value) return [];
  const query = searchQuery.value.trim().toLowerCase();
  if (!query) return lorebook.value.entries;
  
  return lorebook.value.entries.filter((entry) => {
    const keysMatch = entry.keys && entry.keys.some(k => k.toLowerCase().includes(query));
    const secKeysMatch = entry.secondary_keys && entry.secondary_keys.some(k => k.toLowerCase().includes(query));
    const contentMatch = entry.content && entry.content.toLowerCase().includes(query);
    return keysMatch || secKeysMatch || contentMatch;
  });
});

const isModalOpen = ref(false);
const editingEntryIndex = ref<number | null>(null);

let isAndroid = false;
// #ifdef APP-PLUS
isAndroid = uni.getSystemInfoSync().platform === 'android';
// #endif

onLoad((options) => {
  if (options && options.id) {
    lorebookId.value = parseInt(options.id, 10);
    fetchDetail();
  }
});

const fetchDetail = async () => {
  if (lorebookId.value === null) return;
  try {
    uni.showLoading({ title: "加载详情..." });
    const res = await getLorebook(lorebookId.value);
    lorebook.value = res;
  } catch (e) {
    console.error(e);
    uni.showToast({ title: "加载世界书详情失败", icon: "none" });
  } finally {
    uni.hideLoading();
  }
};

const goBack = () => {
  uni.navigateBack();
};

const toggleRecursive = () => {
  if (lorebook.value) {
    lorebook.value.recursive_scanning = !lorebook.value.recursive_scanning;
  }
};

const stepParam = (paramName: 'scan_depth' | 'token_budget', delta: number, min: number, max: number) => {
  if (!lorebook.value) return;
  
  let val = lorebook.value[paramName];
  if (val === undefined || val === null) {
    val = 0;
  }
  
  const newVal = val + delta;
  if (newVal >= min && newVal <= max) {
    lorebook.value[paramName] = newVal === 0 ? undefined : newVal;
  }
};

const toggleEntryEnabled = (entry: LorebookEntry) => {
  if (!lorebook.value) return;
  const originalIndex = lorebook.value.entries.indexOf(entry);
  if (originalIndex !== -1) {
    lorebook.value.entries[originalIndex].enabled = !lorebook.value.entries[originalIndex].enabled;
  }
};

const deleteEntry = (entry: LorebookEntry) => {
  if (!lorebook.value) return;
  const originalIndex = lorebook.value.entries.indexOf(entry);
  if (originalIndex !== -1) {
    uni.showModal({
      title: "删除条目",
      content: "确定要删除此条设定词条吗？",
      success: (res) => {
        if (res.confirm && lorebook.value) {
          lorebook.value.entries.splice(originalIndex, 1);
        }
      }
    });
  }
};

const openAddEntryModal = () => {
  editingEntryIndex.value = null;
  isModalOpen.value = true;
};

const openEditEntryModal = (entry: LorebookEntry) => {
  if (!lorebook.value) return;
  const originalIndex = lorebook.value.entries.indexOf(entry);
  if (originalIndex !== -1) {
    editingEntryIndex.value = originalIndex;
    isModalOpen.value = true;
  }
};

const closeModal = () => {
  isModalOpen.value = false;
};

const onSaveEntry = (entryData: LorebookEntry) => {
  if (!lorebook.value) return;
  if (editingEntryIndex.value === null) {
    lorebook.value.entries.push(entryData);
  } else {
    lorebook.value.entries[editingEntryIndex.value] = entryData;
  }
  closeModal();
};

const saveAll = async () => {
  if (!lorebook.value || lorebookId.value === null) return;
  if (lorebook.value.name.trim() === "") {
    uni.showToast({ title: "世界书名称不能为空", icon: "none" });
    return;
  }

  try {
    uni.showLoading({ title: "正在保存修改..." });
    await updateLorebook(lorebookId.value, {
      name: lorebook.value.name.trim(),
      description: lorebook.value.description ? lorebook.value.description.trim() : "",
      scan_depth: lorebook.value.scan_depth,
      token_budget: lorebook.value.token_budget,
      recursive_scanning: lorebook.value.recursive_scanning,
      entries: lorebook.value.entries,
    });
    uni.showToast({ title: "修改已保存", icon: "success" });
    setTimeout(() => {
      uni.navigateBack();
    }, 1000);
  } catch (e) {
    console.error(e);
    uni.showToast({ title: "保存失败", icon: "none" });
  } finally {
    uni.hideLoading();
  }
};
</script>

<style scoped src="./edit.css"></style>
