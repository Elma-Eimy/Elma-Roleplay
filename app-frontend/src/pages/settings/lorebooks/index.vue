<template>
  <view class="page-container" :class="{ 'is-android': isAndroid }">
    <!-- 导航栏 -->
    <view class="nav-bar">
      <view class="back-btn" @tap="goBack">
        <image class="back-icon" src="/static/icons/header_back.svg" mode="aspectFit" />
      </view>
      <text class="nav-title">独立世界书库</text>
      <view class="placeholder-btn"></view>
    </view>

    <!-- 滚动区域 -->
    <scroll-view scroll-y class="scroll-container">
      <view class="content-panel">
        
        <!-- 导入入口 -->
        <view class="import-card" @tap="triggerFileInput">
          <view class="import-icon-container">
            <svg class="import-svg-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M4 19.5C4 18.6716 4.67157 18 5.5 18H20V4H5.5C4.67157 4 4 4.67157 4 5.5V19.5Z" stroke="#007aff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M4 19.5C4 20.3284 4.67157 21 5.5 21H20" stroke="#007aff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M12 7V13M12 13L9.5 10.5M12 13L14.5 10.5" stroke="#007aff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </view>
          <view class="import-info">
            <text class="import-title">导入世界书</text>
            <text class="import-desc">支持导入 SillyTavern (.json) 格式的世界设定集</text>
          </view>
        </view>


        <!-- 列表标题 -->
        <view class="section-header">
          <text class="section-title">已导入设定集 ({{ lorebooks.length }})</text>
        </view>

        <!-- 世界书列表 -->
        <view class="lorebooks-list" v-if="lorebooks.length > 0">
          <view 
            class="lorebook-item"
            v-for="lb in lorebooks"
            :key="lb.id"
            @tap="editLorebook(lb.id)"
            @longpress="onLongPress(lb)"
            @contextmenu.prevent="onLongPress(lb)"
          >
            <view class="item-header">
              <view class="title-row">
                <image class="book-icon" src="/static/icons/modal_book_gray.svg" mode="aspectFit" />
                <text class="book-name">{{ lb.name }}</text>
              </view>
              <text class="badge">{{ lb.entries_count }} 条词条</text>
            </view>
            
            <text class="item-desc">{{ lb.description || '暂无描述设定。' }}</text>
            
            <view class="item-footer">
              <text class="meta-text" v-if="lb.scan_depth">深度: {{ lb.scan_depth }}</text>
              <text class="meta-text" v-if="lb.token_budget">预算: {{ lb.token_budget }}</text>
              <view class="delete-action-btn" @tap.stop="confirmDelete(lb)">
                <image class="delete-icon" src="/static/icons/drawer_trash.svg" mode="aspectFit" />
                <text class="delete-btn-text">删除</text>
              </view>
            </view>
          </view>
        </view>

        <!-- 空状态 -->
        <view class="empty-state" v-else>
          <image class="empty-image" src="/static/icons/modal_book_gray.svg" mode="aspectFit" />
          <text class="empty-text">书库中暂无独立世界书</text>
          <text class="empty-desc">点击上方导入卡片添加你的第一本世界设定集吧</text>
        </view>
        
      </view>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { getLorebooks, deleteLorebook, importLorebook } from "@/api/lorebooks";
import type { LorebookSummary } from "@/api/lorebooks";

const lorebooks = ref<LorebookSummary[]>([]);
const isLoading = ref(false);

let isAndroid = false;
// #ifdef APP-PLUS
isAndroid = uni.getSystemInfoSync().platform === 'android';
// #endif

const loadLorebooks = async () => {
  isLoading.value = true;
  try {
    const res = await getLorebooks();
    lorebooks.value = res.lorebooks;
  } catch (e) {
    console.error("Failed to load lorebooks", e);
    uni.showToast({ title: "加载世界书失败", icon: "none" });
  } finally {
    isLoading.value = false;
  }
};

onShow(() => {
  loadLorebooks();
});

const goBack = () => {
  uni.navigateBack();
};

const editLorebook = (id: number) => {
  uni.navigateTo({
    url: `/pages/settings/lorebooks/edit?id=${id}`
  });
};

const triggerFileInput = () => {
  // #ifdef H5
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".json";
  input.onchange = async (event: Event) => {
    const target = event.target as HTMLInputElement;
    const file = target.files?.[0];
    if (!file) return;

    uni.showLoading({ title: "正在导入世界书..." });
    try {
      const importRes = await importLorebook(file);
      uni.showToast({ title: `导入成功: ${importRes.name}`, icon: "success" });
      loadLorebooks();
    } catch (err: any) {
      console.error("Failed to import lorebook", err);
      uni.showToast({ title: err.message || "导入失败，请检查文件格式", icon: "none" });
    } finally {
      uni.hideLoading();
    }
  };
  input.click();
  return;
  // #endif

  // 非 H5 网页平台降级使用 uni.chooseFile
  handleImport();
};

const handleImport = () => {
  // #ifdef APP-PLUS
  uni.showToast({ title: "请选择包含世界书配置的 JSON 文件", icon: "none" });
  // #endif
  
  uni.chooseFile({
    count: 1,
    type: "all",
    extension: [".json"],
    success: async (res) => {
      uni.showLoading({ title: "正在导入世界书..." });
      try {
        const tempFiles = res.tempFiles as any;
        const fileObj = tempFiles?.[0]?.file || tempFiles?.[0] || res.tempFilePaths[0];
        const importRes = await importLorebook(fileObj);
        uni.showToast({ title: `导入成功: ${importRes.name}`, icon: "success" });
        loadLorebooks();
      } catch (e: any) {
        console.error("Failed to import lorebook", e);
        uni.showToast({ title: e.message || "导入失败，请检查文件格式", icon: "none" });
      } finally {
        uni.hideLoading();
      }
    },
    fail: (err) => {
      console.log("取消文件选择", err);
    }
  });
};

const confirmDelete = (lb: LorebookSummary) => {
  uni.showModal({
    title: "删除世界书",
    content: `确定要删除《${lb.name}》吗？删除后，已关联该世界书的角色将不再检索其中的设定条目。`,
    confirmColor: "#ff3b30",
    cancelColor: "#8e8e93",
    success: async (res) => {
      if (res.confirm) {
        try {
          uni.showLoading({ title: "正在删除..." });
          await deleteLorebook(lb.id);
          uni.showToast({ title: "已成功删除", icon: "success" });
          loadLorebooks();
        } catch (e) {
          console.error("Failed to delete lorebook", e);
          uni.showToast({ title: "删除失败", icon: "none" });
        } finally {
          uni.hideLoading();
        }
      }
    }
  });
};

const onLongPress = (lb: LorebookSummary) => {
  uni.vibrateShort({ success: () => {} });
  uni.showActionSheet({
    itemList: ["编辑条目", "删除设定集"],
    success: (res) => {
      if (res.tapIndex === 0) {
        editLorebook(lb.id);
      } else if (res.tapIndex === 1) {
        confirmDelete(lb);
      }
    }
  });
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

.placeholder-btn {
  width: 60rpx;
  height: 60rpx;
}

/* ===== 滚动容器 ===== */
.scroll-container {
  flex: 1;
  height: 0;
  overflow: hidden;
}

.content-panel {
  padding: 30rpx 36rpx 100rpx 36rpx;
}

/* ===== 导入卡片 ===== */
.import-card {
  display: flex;
  align-items: center;
  padding: 36rpx;
  background-color: #ffffff;
  border: 1px dashed rgba(0, 0, 0, 0.12);
  border-radius: 24rpx;
  gap: 28rpx;
  transition: all 0.2s ease;
  margin-bottom: 40rpx;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.01);
}

.import-card:active {
  background-color: rgba(0, 0, 0, 0.01);
  transform: scale(0.99);
}

.import-icon-container {
  width: 88rpx;
  height: 88rpx;
  border-radius: 20rpx;
  background-color: rgba(0, 122, 255, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.import-svg-icon {
  width: 48rpx;
  height: 48rpx;
}

.import-info {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.import-title {
  font-size: 30rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.import-desc {
  font-size: 24rpx;
  color: #8e8e93;
  line-height: 1.3;
}

/* ===== 部分标题 ===== */
.section-header {
  margin-bottom: 20rpx;
}

.section-title {
  font-size: 26rpx;
  font-weight: 600;
  color: #8e8e93;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* ===== 列表卡片 ===== */
.lorebooks-list {
  display: flex;
  flex-direction: column;
  gap: 24rpx;
}

.lorebook-item {
  background-color: #ffffff;
  border-radius: 24rpx;
  padding: 36rpx;
  border: 1px solid rgba(0, 0, 0, 0.03);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.02);
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  transition: all 0.2s ease;
}

.lorebook-item:active {
  transform: translateY(-2rpx);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.04);
}

.item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 16rpx;
  min-width: 0;
  flex: 1;
}

.book-icon {
  width: 38rpx;
  height: 38rpx;
  flex-shrink: 0;
}

.book-name {
  font-size: 30rpx;
  font-weight: 600;
  color: #1c1c1e;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.badge {
  font-size: 22rpx;
  font-weight: 600;
  color: #1c1c1e;
  background-color: rgba(0, 0, 0, 0.04);
  padding: 6rpx 16rpx;
  border-radius: 30rpx;
  flex-shrink: 0;
}

.item-desc {
  font-size: 26rpx;
  color: #8e8e93;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10rpx;
  padding-top: 20rpx;
  border-top: 1px solid rgba(0, 0, 0, 0.02);
}

.meta-text {
  font-size: 22rpx;
  color: #8e8e93;
  background-color: rgba(0, 0, 0, 0.02);
  padding: 4rpx 12rpx;
  border-radius: 8rpx;
  margin-right: 12rpx;
}

.delete-action-btn {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 10rpx 18rpx;
  border-radius: 12rpx;
  background-color: rgba(255, 59, 48, 0.05);
  transition: background-color 0.2s;
}

.delete-action-btn:active {
  background-color: rgba(255, 59, 48, 0.12);
}

.delete-icon {
  width: 28rpx;
  height: 28rpx;
}

.delete-btn-text {
  font-size: 22rpx;
  font-weight: 600;
  color: #ff3b30;
}

/* ===== 空状态 ===== */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 120rpx 40rpx;
  text-align: center;
}

.empty-image {
  width: 120rpx;
  height: 120rpx;
  opacity: 0.15;
  margin-bottom: 30rpx;
}

.empty-text {
  font-size: 30rpx;
  font-weight: 600;
  color: #3a3a3c;
  margin-bottom: 12rpx;
}

.empty-desc {
  font-size: 24rpx;
  color: #8e8e93;
  max-width: 480rpx;
  line-height: 1.4;
}

/* Android Performance Fallbacks */
.is-android .nav-bar {
  backdrop-filter: none !important;
  background-color: #ffffff !important;
}
</style>
