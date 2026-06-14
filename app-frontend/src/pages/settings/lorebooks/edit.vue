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
    <view v-if="isModalOpen" class="modal-backdrop">
      <view class="modal-card">
        <view class="modal-header">
          <text class="modal-title">{{ editingEntryIndex === null ? '添加设定条目' : '编辑设定条目' }}</text>
          <view class="modal-close" @tap="closeModal">
            <image class="modal-close-icon" src="/static/icons/drawer_close.svg" mode="aspectFit" />
          </view>
        </view>

        <scroll-view scroll-y class="modal-scroll-form">
          <view class="modal-form-content">
            
            <view class="modal-form-item" v-if="!modalForm.constant">
              <text class="label">触发关键字 (Keys) *</text>
              <text class="hint-text">多个关键字用英文逗号分隔，命中任意一个即可触发</text>
              <input class="input" v-model="modalForm.keysRaw" placeholder="例如：霍格沃茨, 魔法学校, 学院" />
            </view>

            <view class="modal-form-item">
              <text class="label">常驻触发 (Constant)</text>
              <view class="toggle-row">
                <text class="hint-text">启用后，此条目始终加载到上下文中，无视关键字匹配</text>
                <view 
                  class="custom-toggle small"
                  :class="{ 'is-on': modalForm.constant }"
                  @tap="modalForm.constant = !modalForm.constant"
                >
                  <view class="toggle-thumb"></view>
                </view>
              </view>
            </view>

            <view class="modal-form-item" v-if="!modalForm.constant">
              <text class="label">联合过滤 (Selective)</text>
              <view class="toggle-row">
                <text class="hint-text">必须同时满足下方“二级关键字”中的任意一个，才能触发此条目</text>
                <view 
                  class="custom-toggle small"
                  :class="{ 'is-on': modalForm.selective }"
                  @tap="modalForm.selective = !modalForm.selective"
                >
                  <view class="toggle-thumb"></view>
                </view>
              </view>
            </view>

            <view class="modal-form-item" v-if="modalForm.selective && !modalForm.constant">
              <text class="label">二级关键字 (Secondary Keys) *</text>
              <text class="hint-text">必须与主关键字在历史中共同命中才会激活设定（逗号分隔）</text>
              <input class="input" v-model="modalForm.secondaryKeysRaw" placeholder="例如：巫师, 法师" />
            </view>

            <view class="modal-form-item" v-if="!modalForm.constant">
              <text class="label">大小写敏感 (Case Sensitive)</text>
              <view class="toggle-row">
                <text class="hint-text">关键字匹配是否严格区分大小写字母（如 Mana 还是 mana）</text>
                <view 
                  class="custom-toggle small"
                  :class="{ 'is-on': modalForm.case_sensitive }"
                  @tap="modalForm.case_sensitive = !modalForm.case_sensitive"
                >
                  <view class="toggle-thumb"></view>
                </view>
              </view>
            </view>

            <view class="modal-form-item">
              <text class="label">设定内容 (Content) *</text>
              <textarea class="textarea-modal" v-model="modalForm.content" placeholder="输入关键字命中后注入上下文的具体设定描述..." />
            </view>

            <view class="modal-form-item">
              <text class="label">插入位置 (Position)</text>
              <view class="radio-group">
                <view 
                  class="radio-item" 
                  :class="{ 'is-active': modalForm.position === 'after_char' }" 
                  @tap="modalForm.position = 'after_char'"
                >
                  <text class="radio-text">人设之后 (推荐)</text>
                </view>
                <view 
                  class="radio-item" 
                  :class="{ 'is-active': modalForm.position === 'before_char' }" 
                  @tap="modalForm.position = 'before_char'"
                >
                  <text class="radio-text">人设之前</text>
                </view>
              </view>
            </view>

            <view class="modal-form-item">
              <text class="label">匹配优先级 (Insertion Order)</text>
              <text class="hint-text">控制词条注入时的排序。数值越小排在越前面，默认 100</text>
              <input class="input" type="number" v-model.number="modalForm.insertion_order" placeholder="默认 100" />
            </view>

          </view>
        </scroll-view>

        <view class="modal-footer">
          <view class="modal-btn cancel" @tap="closeModal">取消</view>
          <view 
            class="modal-btn save" 
            :class="{ 'is-disabled': !isModalFormValid }"
            @tap="saveEntry"
          >
            保存条目
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { getLorebook, updateLorebook } from "@/api/lorebooks";
import type { LorebookDetail, LorebookEntry } from "@/api/lorebooks";

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

const modalForm = ref({
  keysRaw: "",
  secondaryKeysRaw: "",
  content: "",
  constant: false,
  case_sensitive: false,
  selective: false,
  position: "after_char",
  insertion_order: 100,
});

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
  modalForm.value = {
    keysRaw: "",
    secondaryKeysRaw: "",
    content: "",
    constant: false,
    case_sensitive: false,
    selective: false,
    position: "after_char",
    insertion_order: 100,
  };
  isModalOpen.value = true;
};

const openEditEntryModal = (entry: LorebookEntry) => {
  if (!lorebook.value) return;
  const originalIndex = lorebook.value.entries.indexOf(entry);
  if (originalIndex !== -1) {
    editingEntryIndex.value = originalIndex;
    modalForm.value = {
      keysRaw: entry.keys ? entry.keys.join(", ") : "",
      secondaryKeysRaw: entry.secondary_keys ? entry.secondary_keys.join(", ") : "",
      content: entry.content,
      constant: !!entry.constant,
      case_sensitive: !!entry.case_sensitive,
      selective: !!entry.selective,
      position: entry.position || "after_char",
      insertion_order: entry.insertion_order !== undefined ? entry.insertion_order : 100,
    };
    isModalOpen.value = true;
  }
};

const closeModal = () => {
  isModalOpen.value = false;
};

const isModalFormValid = computed(() => {
  if (modalForm.value.content.trim() === "") return false;
  if (modalForm.value.constant) return true;
  return modalForm.value.keysRaw.trim() !== "";
});

const saveEntry = () => {
  if (!isModalFormValid.value || !lorebook.value) return;
  
  const keys = modalForm.value.constant
    ? []
    : modalForm.value.keysRaw
        .split(",")
        .map((k) => k.trim())
        .filter(Boolean);
    
  const secondary_keys = modalForm.value.constant
    ? []
    : modalForm.value.secondaryKeysRaw
        .split(",")
        .map((k) => k.trim())
        .filter(Boolean);

  const entryData: LorebookEntry = {
    keys,
    content: modalForm.value.content.trim(),
    enabled: editingEntryIndex.value !== null ? lorebook.value.entries[editingEntryIndex.value].enabled : true,
    constant: modalForm.value.constant,
    case_sensitive: modalForm.value.constant ? false : modalForm.value.case_sensitive,
    selective: modalForm.value.constant ? false : modalForm.value.selective,
    secondary_keys: modalForm.value.constant ? [] : secondary_keys,
    position: modalForm.value.position,
    insertion_order: modalForm.value.insertion_order || 100,
  };

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

<style scoped>
.page-container {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
  min-height: 100vh;
  background-color: #fafafa;
  overflow: hidden;
}

/* ===== 导航栏 ===== */
.nav-bar {
  position: relative;
  padding-top: env(safe-area-inset-top, 40rpx);
  height: calc(env(safe-area-inset-top, 40rpx) + 110rpx);
  padding-left: 36rpx;
  padding-right: 36rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background-color: rgba(255, 255, 255, 0.65);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  z-index: 50;
  flex-shrink: 0;
}

.back-btn {
  width: 60rpx;
  height: 60rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.02);
  transition: background-color 0.2s;
}

.back-btn:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.back-icon {
  width: 34rpx;
  height: 34rpx;
}

.nav-title {
  font-size: 34rpx;
  font-weight: 600;
  color: #1c1c1e;
  letter-spacing: -0.5px;
}

.save-header-btn {
  font-size: 28rpx;
  font-weight: 600;
  color: #1c1c1e;
  padding: 12rpx 20rpx;
  background-color: rgba(0, 0, 0, 0.04);
  border-radius: 12rpx;
}

.save-header-btn:active {
  background-color: rgba(0, 0, 0, 0.08);
}

/* ===== 滚动容器 ===== */
.scroll-container {
  flex: 1;
  height: 0;
  overflow: hidden;
}

.content-panel {
  padding: 30rpx 36rpx 240rpx 36rpx;
}

/* ===== 表单组卡片 ===== */
.card-group {
  background-color: #ffffff;
  border-radius: 24rpx;
  padding: 36rpx;
  border: 1px solid rgba(0, 0, 0, 0.03);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.02);
  margin-bottom: 36rpx;
  display: flex;
  flex-direction: column;
  gap: 28rpx;
}

.group-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.group-title {
  font-size: 26rpx;
  font-weight: 700;
  color: #8e8e93;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.caret-icon {
  width: 36rpx;
  height: 36rpx;
  opacity: 0.5;
}

.advanced-fields {
  display: flex;
  flex-direction: column;
  gap: 28rpx;
  margin-top: 10rpx;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.form-item.border-bottom {
  border-bottom: 1px solid rgba(0, 0, 0, 0.03);
  padding-bottom: 24rpx;
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
  gap: 24rpx;
}

.form-item-left {
  display: flex;
  flex-direction: column;
  gap: 6rpx;
  flex: 1;
}

.label {
  font-size: 28rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.label-desc {
  font-size: 22rpx;
  color: #8e8e93;
  line-height: 1.3;
}

.input {
  width: 100%;
  height: 80rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 14rpx;
  padding: 0 20rpx;
  font-size: 28rpx;
  color: #1c1c1e;
  box-sizing: border-box;
}

.textarea-small {
  width: 100%;
  height: 150rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 14rpx;
  padding: 20rpx;
  font-size: 28rpx;
  color: #1c1c1e;
  box-sizing: border-box;
}

/* ===== Stepper (步进器) ===== */
.stepper {
  display: flex;
  align-items: center;
  background-color: rgba(0, 0, 0, 0.03);
  border-radius: 16rpx;
  height: 64rpx;
  overflow: hidden;
  flex-shrink: 0;
}

.stepper-large {
  display: flex;
  align-items: center;
  background-color: rgba(0, 0, 0, 0.03);
  border-radius: 16rpx;
  height: 64rpx;
  overflow: hidden;
  flex-shrink: 0;
}

.step-btn {
  width: 64rpx;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.step-btn:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.step-value {
  padding: 0 20rpx;
  font-size: 26rpx;
  font-weight: 600;
  color: #1c1c1e;
  min-width: 60rpx;
  text-align: center;
}

/* ===== Toggle 开关 ===== */
.custom-toggle {
  width: 90rpx;
  height: 52rpx;
  background-color: rgba(0, 0, 0, 0.08);
  border-radius: 30rpx;
  padding: 4rpx;
  box-sizing: border-box;
  transition: background-color 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.custom-toggle.small {
  width: 76rpx;
  height: 44rpx;
}

.custom-toggle.is-on {
  background-color: #30d158;
}

.toggle-thumb {
  width: 44rpx;
  height: 44rpx;
  background-color: #ffffff;
  border-radius: 50%;
  box-shadow: 0 3px 8px rgba(0, 0, 0, 0.15);
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.custom-toggle.small .toggle-thumb {
  width: 36rpx;
  height: 36rpx;
}

.custom-toggle.is-on .toggle-thumb {
  transform: translateX(38rpx);
}

.custom-toggle.small.is-on .toggle-thumb {
  transform: translateX(32rpx);
}

/* ===== 条目列表标题与操作 ===== */
.entries-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 50rpx;
  margin-bottom: 24rpx;
}

.entries-section-title {
  font-size: 26rpx;
  font-weight: 700;
  color: #8e8e93;
  letter-spacing: 0.5px;
}

.add-entry-btn {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 12rpx 24rpx;
  background-color: #1c1c1e;
  border-radius: 40rpx;
  box-shadow: 0 4px 10rpx rgba(0,0,0,0.15);
}

.add-entry-btn:active {
  background-color: #000000;
  transform: scale(0.97);
}

.add-icon {
  width: 24rpx;
  height: 24rpx;
  filter: invert(1);
}

.add-text {
  font-size: 24rpx;
  font-weight: 600;
  color: #ffffff;
}

/* ===== 条目卡片 ===== */
.entries-list {
  display: flex;
  flex-direction: column;
  gap: 24rpx;
}

.entry-item-card {
  background-color: #ffffff;
  border-radius: 24rpx;
  padding: 36rpx;
  border: 1px solid rgba(0, 0, 0, 0.03);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.02);
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  transition: opacity 0.2s;
}

.entry-item-card.is-disabled {
  opacity: 0.45;
}

.entry-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20rpx;
}

.entry-keys {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
  flex: 1;
}

.entry-key-tag {
  font-size: 22rpx;
  font-weight: 600;
  color: #1c1c1e;
  background-color: rgba(0, 0, 0, 0.04);
  padding: 6rpx 16rpx;
  border-radius: 30rpx;
}

.entry-key-tag.constant-badge {
  color: #ffffff;
  background-color: #34c759;
}

.entry-switch-row {
  display: flex;
  align-items: center;
  gap: 16rpx;
  flex-shrink: 0;
}

.entry-body {
  font-size: 26rpx;
  color: #3a3a3c;
  line-height: 1.4;
  word-break: break-all;
}

.entry-meta-info {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
  margin-top: 6rpx;
}

.meta-item {
  font-size: 20rpx;
  color: #8e8e93;
  background-color: rgba(0,0,0,0.02);
  padding: 4rpx 10rpx;
  border-radius: 6rpx;
}

.entry-card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 28rpx;
  margin-top: 10rpx;
  padding-top: 20rpx;
  border-top: 1px solid rgba(0, 0, 0, 0.02);
}

.action-item {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 8rpx 12rpx;
}

.action-icon {
  width: 28rpx;
  height: 28rpx;
}

.action-text {
  font-size: 22rpx;
  font-weight: 600;
  color: #545456;
}

.action-text.danger {
  color: #ff3b30;
}

.empty-entries {
  padding: 80rpx 40rpx;
  text-align: center;
}

.empty-entries-text {
  font-size: 26rpx;
  color: #8e8e93;
}

/* ===== 底部操作栏 ===== */
.footer {
  position: fixed;
  bottom: 0;
  left: 0;
  width: 100vw;
  background-color: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(20px);
  border-top: 1px solid rgba(0, 0, 0, 0.05);
  padding: 24rpx 36rpx calc(env(safe-area-inset-bottom, 24rpx) + 24rpx) 36rpx;
  box-sizing: border-box;
  z-index: 40;
}

.footer-save-btn {
  width: 100%;
  height: 90rpx;
  background-color: #1c1c1e;
  border-radius: 45rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 10px 20px rgba(0, 0, 0, 0.1);
}

.footer-save-btn:active {
  background-color: #000000;
  transform: scale(0.99);
}

.save-btn-text {
  font-size: 28rpx;
  font-weight: 600;
  color: #ffffff;
}

/* ===== 条目编辑模态框 (Modal) ===== */
.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(10px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-card {
  width: 650rpx;
  height: 80%;
  max-height: 1000rpx;
  background-color: #ffffff;
  border-radius: 28rpx;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 45px rgba(0, 0, 0, 0.15);
  border: 1px solid rgba(0, 0, 0, 0.05);
}

.modal-header {
  padding: 36rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
}

.modal-title {
  font-size: 32rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.modal-close {
  width: 50rpx;
  height: 50rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-close-icon {
  width: 30rpx;
  height: 30rpx;
  opacity: 0.5;
}

.modal-scroll-form {
  flex: 1;
  overflow: hidden;
}

.modal-form-content {
  padding: 36rpx;
  display: flex;
  flex-direction: column;
  gap: 32rpx;
}

.modal-form-item {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.hint-text {
  font-size: 22rpx;
  color: #8e8e93;
  line-height: 1.3;
}

.toggle-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20rpx;
}

.toggle-row .hint-text {
  flex: 1;
}

.textarea-modal {
  width: 100%;
  height: 200rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 14rpx;
  padding: 20rpx;
  font-size: 28rpx;
  color: #1c1c1e;
  box-sizing: border-box;
}

/* ===== Radio Group (单选框组) ===== */
.radio-group {
  display: flex;
  gap: 20rpx;
}

.radio-item {
  flex: 1;
  height: 72rpx;
  border-radius: 16rpx;
  background-color: rgba(0,0,0,0.02);
  border: 1px solid rgba(0,0,0,0.03);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.25s;
}

.radio-item.is-active {
  background-color: #1c1c1e;
  border-color: #1c1c1e;
}

.radio-text {
  font-size: 24rpx;
  font-weight: 600;
  color: #545456;
}

.radio-item.is-active .radio-text {
  color: #ffffff;
}

.modal-footer {
  padding: 24rpx 36rpx;
  border-top: 1px solid rgba(0, 0, 0, 0.05);
  display: flex;
  gap: 20rpx;
}

.modal-btn {
  flex: 1;
  height: 80rpx;
  border-radius: 40rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26rpx;
  font-weight: 600;
  transition: all 0.2s;
}

.modal-btn.cancel {
  background-color: rgba(0, 0, 0, 0.03);
  color: #48484a;
}

.modal-btn.cancel:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.modal-btn.save {
  background-color: #1c1c1e;
  color: #ffffff;
}

.modal-btn.save:active {
  background-color: #000000;
}

.modal-btn.save.is-disabled {
  opacity: 0.3;
  pointer-events: none;
}

/* Android Performance Fallbacks */
.is-android .nav-bar {
  backdrop-filter: none !important;
  background-color: #ffffff !important;
}

.is-android .footer {
  backdrop-filter: none !important;
  background-color: #ffffff !important;
}

.is-android .modal-backdrop {
  backdrop-filter: none !important;
  background-color: rgba(0, 0, 0, 0.6) !important;
}

/* ===== 搜索栏样式 ===== */
.search-bar-row {
  position: relative;
  margin-bottom: 30rpx;
  display: flex;
  align-items: center;
}

.search-input {
  width: 100%;
  height: 72rpx;
  background-color: #f2f2f7;
  border-radius: 18rpx;
  padding: 0 60rpx 0 24rpx;
  font-size: 26rpx;
  color: #1c1c1e;
  box-sizing: border-box;
}

.clear-search-btn {
  position: absolute;
  right: 20rpx;
  font-size: 36rpx;
  color: #8e8e93;
  padding: 10rpx;
}
</style>
