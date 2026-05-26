<template>
  <view class="page-container" :class="{ 'is-android': isAndroid }">
    <!-- 动态磨砂玻璃背景图层 -->
    <view class="chat-bg" :style="backgroundStyle"></view>
    <!-- 自定义导航栏头部 -->
    <view class="custom-header">
      <!-- 返回按钮 -->
      <view class="header-btn left-btn" @tap="goBack">
        <image class="back-icon" style="width: 44rpx; height: 44rpx; flex-shrink: 0;" src="/static/icons/header_back.svg" mode="aspectFit" />
      </view>

      <!-- 中部标题与角色在线状态 -->
      <view class="header-center">
        <text class="character-name">{{ personaStore.characterName || '未选角色' }}</text>
        <view class="status-indicator">
          <view class="status-dot"></view>
          <text class="status-text">{{ personaStore.currentMood || '在线' }}</text>
        </view>
      </view>

      <!-- 右侧操作栏按钮（开启信息与状态抽屉面板） -->
      <view class="header-btn right-btn" @tap="isStatusPanelOpen = true">
        <image class="info-icon" style="width: 40rpx; height: 40rpx; flex-shrink: 0;" src="/static/icons/header_info.svg" mode="aspectFit" />
      </view>
    </view>

    <!-- 聊天消息滚动区域 -->
    <scroll-view 
      class="chat-scroll-area" 
      scroll-y 
      :scroll-top="scrollTop"
      :scroll-with-animation="scrollWithAnimation"
      @scrolltoupper="onLoadMore"
    >
      <view class="chat-list-padding">
        <ChatBubble
          v-for="msg in chatStore.messages"
          :key="msg.id || msg.tempId"
          :message="msg"
          :avatarUrl="getAvatarUrl(personaStore.activeCharacter?.avatar_path || '')"
          :characterName="personaStore.characterName"
          @longpress="onMessageLongPress"
        />

        <!-- 会话故事空状态 -->
        <view v-if="chatStore.messages.length === 0" class="empty-chat">
          <text class="empty-chat-text">开启新的会话故事...</text>
        </view>
      </view>
    </scroll-view>

    <!-- 底部对话输入区域 -->
    <view class="input-area-wrapper" :style="inputWrapperStyle">
      <!-- 深度思考推理模式开关行 -->
      <view class="reasoning-toggle-row">
        <view 
          class="reasoning-toggle-btn" 
          :class="{ 'is-reasoning': chatStore.useReasoning }"
          @tap="chatStore.useReasoning = !chatStore.useReasoning"
        >
          <image 
            class="reasoning-icon" 
            :src="chatStore.useReasoning ? '/static/icons/chat_sparkle_active.svg' : '/static/icons/chat_sparkle.svg'" 
            mode="aspectFit" 
          />
          <text class="reasoning-label">{{ chatStore.useReasoning ? '深度思考' : '普通模式' }}</text>
        </view>
      </view>
      <view class="input-area" :class="{ 'is-focused': isInputFocused }">
        <textarea 
          class="chat-input"
          v-model="inputText"
          placeholder="发送消息..."
          :auto-height="true"
          :maxlength="-1"
          :adjust-position="false"
          :cursor-spacing="0"
          :confirm-hold="true"
          confirm-type="send"
          @confirm="onSend"
          @focus="isInputFocused = true"
          @blur="isInputFocused = false"
          @linechange="scrollToBottom"
        />
        <view 
          class="send-btn" 
          :class="{ 'is-active': inputText.trim().length > 0 }"
          @tap="onSend"
        >
          <image class="send-icon" src="/static/icons/chat_send.svg" mode="aspectFit" />
        </view>
      </view>
      <!-- 原生软键盘占位高度（仅在 App 键盘弹起时生效），通过 flex 容器自动无缝推起并缩短上方滚动区 -->
      <view :style="{ height: keyboardHeight + 'px' }" style="transition: height 0.1s ease-out;"></view>
    </view>

    <!-- 编辑消息模态对话框 -->
    <view v-if="editingMessageId !== null" class="modal-backdrop">
      <view class="edit-modal">
        <text class="modal-title">编辑消息</text>
        <textarea 
          class="edit-textarea" 
          v-model="editMessageContent" 
          :maxlength="-1"
          :show-confirm-bar="false"
        ></textarea>
        <view class="modal-actions">
          <view class="modal-btn cancel" @tap="cancelEdit">取消</view>
          <view class="modal-btn save" @tap="saveEdit">保存</view>
        </view>
      </view>
    </view>

    <!-- 记忆与微观认知状态右侧抽屉面板 -->
    <view v-if="isStatusPanelOpen" class="status-panel-backdrop" @tap="isStatusPanelOpen = false">
      <view class="status-panel" @tap.stop>

        <!-- 面板头部：仅包含关闭按钮 -->
        <view class="panel-header">
          <view class="close-btn" @tap="isStatusPanelOpen = false">
            <image class="close-icon" src="/static/icons/drawer_close.svg" mode="aspectFit" />
          </view>
        </view>

        <scroll-view scroll-y class="panel-content">

          <!-- ① 角色卡片面板 -->
          <view class="char-card">
            <image
              class="char-card-avatar"
              :src="getAvatarUrl(personaStore.activeCharacter?.avatar_path || '')"
              mode="aspectFill"
            />
            <view class="char-card-info">
              <text class="char-card-name">{{ personaStore.characterName }}</text>
              <view class="mood-badge">
                <view class="mood-dot"></view>
                <text class="mood-text">{{ personaStore.currentMood || '在线' }}</text>
              </view>
            </view>
          </view>

          <!-- ② 好感度数值与进度条 -->
          <view class="panel-section">
            <view class="section-title-row">
              <text class="section-title">好感度</text>
              <text class="affection-value">{{ affectionEmoji }} {{ personaStore.affectionScore }} / 100</text>
            </view>
            <view class="progress-bg">
              <view class="progress-bar-gradient" :style="{ width: personaStore.affectionPercent + '%' }"></view>
            </view>
          </view>

          <!-- ③ 微观认知状态显示区 -->
          <view class="panel-section">
            <text class="section-title">微观认知</text>
            <view class="cognition-box">
              <text class="cognition-text">{{ personaStore.cognitionState || '暂无认知记录。' }}</text>
            </view>
          </view>

          <!-- ④ 对话配置开关项 -->
          <view class="panel-section">
            <text class="section-title">对话设置</text>
            <view class="setting-row">
              <view class="setting-row-left">
                <image 
                  class="setting-row-icon" 
                  :src="chatStore.useReasoning ? '/static/icons/chat_sparkle_active.svg' : '/static/icons/chat_sparkle.svg'" 
                  mode="aspectFit" 
                />
                <text class="setting-row-label">深度思考模式</text>
              </view>
              <view
                class="custom-toggle"
                :class="{ 'is-on': chatStore.useReasoning }"
                @tap="chatStore.useReasoning = !chatStore.useReasoning"
              >
                <view class="toggle-thumb"></view>
              </view>
            </view>
          </view>

          <!-- ⑤ 记忆管理手动操作区 -->
          <view class="panel-section">
            <text class="section-title">记忆管理</text>
            <view class="action-btn outline" @tap="forceMemoryExtract">
              <image class="btn-icon" src="/static/icons/drawer_brain.svg" mode="aspectFit" />
              <text class="btn-text">手动提取记忆元</text>
            </view>
            <view class="action-btn outline" @tap="updateCognition">
              <image class="btn-icon" src="/static/icons/drawer_sync.svg" mode="aspectFit" />
              <text class="btn-text">更新微观认知</text>
            </view>
          </view>

          <!-- ⑥ 危险操作区域（删除会话） -->
          <view class="panel-section danger-section">
            <text class="section-title danger-title">危险操作</text>
            <view class="action-btn danger-btn" @tap="deleteCurrentSession">
              <image class="danger-icon" src="/static/icons/drawer_trash.svg" mode="aspectFit" />
              <text class="danger-btn-text">删除本次会话</text>
            </view>
          </view>

        </scroll-view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, nextTick, watch, computed, onMounted, onUnmounted } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { useChatStore } from "@/store/chatStore";
import { usePersonaStore } from "@/store/personaStore";
import { createSession, triggerSummary, triggerCognition, deleteSession } from "@/api/sessions";
import { ChatBubble } from "@/components/chat";
import { getAvatarUrl } from "@/api/characters";

// 状态存储
const chatStore = useChatStore();
const personaStore = usePersonaStore();

// 状态变量
const currentSessionId = ref<number | null>(null);

// 界面 UI 状态
const inputText = ref("");
const isInputFocused = ref(false);
// 使用单调递增值，确保每次 scrollTop 变化都被 scroll-view 检测到
const scrollTop = ref(0);
const scrollWithAnimation = ref(false);
const isStatusPanelOpen = ref(false);

// 软键盘弹起时，iOS 端需移除底部安全区域的高度占位，防止出现双重空白间距
const inputWrapperStyle = computed(() => {
  if (keyboardHeight.value > 0) {
    return {
      paddingBottom: '14rpx'
    };
  }
  return {};
});

// 消息编辑状态
const editingMessageId = ref<number | null>(null);
const editMessageContent = ref("");

// 键盘高度自适应控制，确保 App 软键盘弹起时顶部自定义 Header 不动，仅下方滚动区自适应缩短
const keyboardHeight = ref(0);

let isAndroid = false;
// #ifdef APP-PLUS
isAndroid = uni.getSystemInfoSync().platform === 'android';
// #endif

// #ifdef APP-PLUS
const onKeyboardChange = (res: any) => {
  // Android 平台由于配置了 adjustResize，WebView 会自动调整大小以适应键盘，无需手动用占位高度推起内容
  // iOS 平台 WebView 保持原有高度不变，必须通过键盘占位高度来将输入区域推到键盘上方
  keyboardHeight.value = isAndroid ? 0 : res.keyboardHeight;
  if (res.keyboardHeight > 0) {
    scrollToBottom();
  }
};
// #endif

onMounted(() => {
  // #ifdef APP-PLUS
  uni.onKeyboardHeightChange(onKeyboardChange);
  // #endif
});

onUnmounted(() => {
  // #ifdef APP-PLUS
  uni.offKeyboardHeightChange(onKeyboardChange);
  // #endif
});

onLoad(async (options) => {
  if (options && options.sessionId) {
    const sId = parseInt(options.sessionId, 10);
    currentSessionId.value = sId;
    
    // 初始进入页面时不带动画滚动，防止多次触发动画导致滚动回弹/抖动
    scrollWithAnimation.value = false;
    
    // 从后端加载该会话的详细信息与聊天历史记录
    await Promise.all([
      personaStore.loadSessionDetail(sId),
      chatStore.loadHistory(sId)
    ]);
    
    // 延迟 250 毫秒以确保历史消息组件在移动端端侧彻底完成 DOM 挂载和高度计算后再滚动到底端
    setTimeout(() => {
      scrollToBottom();
      // 瞬间置底完成后，开启滚动动画，使后续新消息有平滑过渡
      nextTick(() => {
        scrollWithAnimation.value = true;
      });
    }, 250);
  }
});

const goBack = () => {
  const pages = getCurrentPages();
  if (pages.length > 1) {
    uni.navigateBack();
  } else {
    uni.switchTab({
      url: "/pages/index/index"
    });
  }
};

const scrollToBottom = async () => {
  await nextTick();
  // 在 Uni-app 中，为确保 scroll-view 检测到值改变从而触发底层渲染滚动，
  // 我们交替使用两个极大值（999999 和 999998），触发滚动层准确滚动到底部
  scrollTop.value = scrollTop.value === 999999 ? 999998 : 999999;
};

// 引入高频滚动节流锁，防止流式输出时反复重绘导致的卡顿
let isScrollThrottled = false;
const scrollToBottomThrottled = () => {
  if (isScrollThrottled) return;
  isScrollThrottled = true;
  setTimeout(() => {
    scrollToBottom();
    isScrollThrottled = false;
  }, 120); // 限制滚动频率为 120ms 一次，既平滑又大幅降低 CPU 负载
};

// 监听消息数组长度的变化，无论是加载历史记录还是发送/接收新消息，都自动滚动到底部
watch(() => chatStore.messages.length, () => {
  scrollToBottom();
});

// 流式输出过程中，采用节流函数跟随滚动
watch(() => chatStore.streamingText, () => {
  scrollToBottomThrottled();
});

// 对话彻底结束或状态发生改变时，强制无条件滚动到底部以确保最终位置对齐
watch(() => chatStore.isLoading, (loading) => {
  if (!loading) {
    scrollToBottom();
  }
});

const onSend = async () => {
  const text = inputText.value.trim();
  if (!text || chatStore.isLoading || currentSessionId.value === null) return;

  // 立即清空输入框
  inputText.value = "";
  
  // 不 await 整个流：sendChatMessage 内部同步添加用户消息和 AI 占位 bubble，
  // 然后异步开始流式请求。这样我们可以立即滚动到底部显示用户消息。
  chatStore.sendChatMessage(currentSessionId.value, text);
  scrollToBottom();
};

const onMessageLongPress = (msg: any) => {
  const itemList = ['复制内容', '编辑消息', '创建分支（多宇宙）', '删除此消息'];
  // 仅在长按的消息是最后一条 AI 回复时，才允许出现“重新生成回复”选项（以保护历史一致性）
  const isLatestAssistant = msg.id === chatStore.lastAssistantMessage?.id;
  if (msg.role === 'assistant' && isLatestAssistant) {
    itemList.splice(3, 0, '重新生成回复'); // Insert before Delete
  }

  uni.showActionSheet({
    itemList,
    success: (res) => {
      const action = itemList[res.tapIndex];
      if (action === '复制内容') {
        uni.setClipboardData({
          data: msg.content,
          success: () => uni.showToast({ title: '复制成功', icon: 'none' })
        });
      } else if (action === '编辑消息') {
        editingMessageId.value = msg.id;
        editMessageContent.value = msg.content;
      } else if (action === '创建分支（多宇宙）') {
        uni.showModal({
          title: '创建分支会话',
          content: '确定要在此消息节点截断并开启一条新的分支故事会话吗？',
          confirmColor: '#10b981',
          cancelColor: '#8e8e93',
          success: async (mRes) => {
            if (mRes.confirm && currentSessionId.value !== null) {
              try {
                uni.showLoading({ title: '正在创建分支...' });
                const branchRes = await createSession({
                   character_id: personaStore.activeCharacter!.id,
                   parent_session_id: currentSessionId.value,
                   title: `${personaStore.activeCharacter!.name} (分支故事)`
                });
                uni.hideLoading();
                uni.showToast({ title: '分支创建成功', icon: 'success' });
                
                setTimeout(() => {
                  uni.redirectTo({
                    url: `/pages/chat/chat?sessionId=${branchRes.session_id}`
                  });
                }, 1000);
              } catch (e) {
                uni.hideLoading();
                console.error(e);
                uni.showToast({ title: '创建分支失败', icon: 'none' });
              }
            }
          }
        });
      } else if (action === '删除此消息') {
        uni.showModal({
          title: '删除消息',
          content: '确定要删除此消息吗？',
          confirmColor: '#ff3b30',
          cancelColor: '#8e8e93',
          success: async (mRes) => {
            if (mRes.confirm) {
              await chatStore.deleteMessageById(msg.id);
            }
          }
        });
      } else if (action === '重新生成回复') {
        if (currentSessionId.value !== null) {
          (async () => {
            try {
              await chatStore.regenerateChatMessage(currentSessionId.value!);
              scrollToBottom();
            } catch (e) {
              console.error("Failed to regenerate response", e);
            }
          })();
        }
      }
    }
  });
};

const cancelEdit = () => {
  editingMessageId.value = null;
  editMessageContent.value = "";
};

const saveEdit = async () => {
  if (editingMessageId.value !== null) {
    await chatStore.editMessage(editingMessageId.value, editMessageContent.value);
    cancelEdit();
  }
};

const forceMemoryExtract = async () => {
  if (currentSessionId.value === null) return;
  try {
    uni.showLoading({ title: '正在提取记忆元...' });
    const res = await triggerSummary(currentSessionId.value);
    uni.hideLoading();
    uni.showToast({ title: res.message || '记忆提取完成', icon: 'success' });
  } catch (e) {
    uni.hideLoading();
    uni.showToast({ title: '记忆提取失败', icon: 'none' });
    console.error(e);
  }
};

const updateCognition = async () => {
  if (currentSessionId.value === null) return;
  try {
    uni.showLoading({ title: '正在更新认知...' });
    const res = await triggerCognition(currentSessionId.value);
    await personaStore.loadSessionDetail(currentSessionId.value);
    uni.hideLoading();
    uni.showToast({ title: res.message || '认知更新完成', icon: 'success' });
  } catch (e) {
    uni.hideLoading();
    uni.showToast({ title: '认知更新失败', icon: 'none' });
    console.error(e);
  }
};

const onReasoningChange = (e: any) => {
  chatStore.useReasoning = e.detail.value;
};

// 好感度 emoji 映射
const affectionEmoji = computed(() => {
  const s = personaStore.affectionScore;
  if (s >= 90) return '💖';
  if (s >= 70) return '❤️';
  if (s >= 50) return '😊';
  if (s >= 30) return '😐';
  if (s >= 10) return '😕';
  return '💔';
});

// 聊天背景图样式
const backgroundStyle = computed(() => {
  const avatar = personaStore.activeCharacter?.avatar_path;
  if (!avatar) return {};
  const url = getAvatarUrl(avatar);
  return {
    backgroundImage: `url(${url})`
  };
});

// 删除当前会话
const deleteCurrentSession = () => {
  if (currentSessionId.value === null) return;
  uni.showModal({
    title: '删除会话',
    content: '确定要删除此会话吗？所有聊天记录与记忆数据将无法找回。',
    confirmColor: '#ff3b30',
    cancelColor: '#8e8e93',
    success: async (res) => {
      if (res.confirm) {
        try {
          uni.showLoading({ title: '正在删除...' });
          await deleteSession(currentSessionId.value!);
          uni.hideLoading();
          isStatusPanelOpen.value = false;
          uni.navigateBack();
        } catch (e) {
          uni.hideLoading();
          uni.showToast({ title: '删除失败，请重试', icon: 'none' });
          console.error(e);
        }
      }
    }
  });
};

const onLoadMore = () => {
  console.log("Load older messages");
};
</script>

<style scoped>
/* ===== 页面大容器 ===== */
.page-container {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
  min-height: 100vh;
  background-color: #fafafa;
  position: relative;
  overflow: hidden;
}

/* 动态磨砂玻璃背景图层 */
.chat-bg {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-size: cover;
  background-position: center;
  opacity: 0.08; /* 降低不透明度使其更为隐约透明 */
  filter: blur(4rpx); /* 减少模糊半径以增加识别度，呈现更精致的半透效果 */
  pointer-events: none;
  z-index: 0;
}

/* ===== 自定义导航栏头部 ===== */
.custom-header {
  padding-top: env(safe-area-inset-top, 40rpx);
  height: calc(env(safe-area-inset-top, 40rpx) + 110rpx);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-left: 36rpx;
  padding-right: 36rpx;
  background-color: rgba(255, 255, 255, 0.70); /* 更高的透明度，更显轻薄 */
  backdrop-filter: blur(10px); /* 减小模糊值，使毛玻璃效果看起来更精致通透 */
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  z-index: 50;
}

.header-btn {
  width: 60rpx;
  height: 60rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.02);
}

.header-btn:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.left-btn {
  margin-left: -10rpx;
}

.right-btn {
  margin-right: -10rpx;
  color: #1c1c1e;
}

.header-center {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.character-name {
  font-size: 30rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8rpx;
  margin-top: 4rpx;
}

.status-dot {
  width: 8rpx;
  height: 8rpx;
  background-color: #34c759;
  border-radius: 50%;
}

.status-text {
  font-size: 18rpx;
  color: #8e8e93;
  font-weight: 500;
}

/* ===== 聊天内容滚动区域 ===== */
.chat-scroll-area {
  flex: 1;
  width: 100%;
  /* H5 端：scroll-view 在 flex 容器内必须有明确高度才能滚动 */
  height: 0;
  min-height: 0;
  overflow: hidden;
  position: relative;
  z-index: 1;
  background-color: transparent !important;
}

.chat-list-padding {
  padding: 24rpx 0;
  display: flex;
  flex-direction: column;
  min-height: 100%;
}

.empty-chat {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-chat-text {
  color: #8e8e93;
  font-size: 26rpx;
}

/* ===== 底部对话输入区域 ===== */
.input-area-wrapper {
  position: relative;
  z-index: 10;
  background-color: #ffffff;
  border-top: 1px solid rgba(0, 0, 0, 0.04);
  padding: 10rpx 36rpx calc(env(safe-area-inset-bottom, 16rpx) + 14rpx) 36rpx;
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.01);
}

/* ===== 深度思考切换行 ===== */
.reasoning-toggle-row {
  display: flex;
  align-items: center;
  margin-bottom: 10rpx;
}

.reasoning-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  padding: 8rpx 20rpx;
  border-radius: 40rpx;
  border: 1.5px solid rgba(0, 0, 0, 0.08);
  background-color: rgba(0, 0, 0, 0.02);
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  cursor: pointer;
}

.reasoning-toggle-btn:active {
  transform: scale(0.95);
}

.reasoning-toggle-btn.is-reasoning {
  background-color: #1c1c1e;
  border-color: #1c1c1e;
}

.reasoning-icon {
  color: #8e8e93;
  flex-shrink: 0;
}

.reasoning-toggle-btn.is-reasoning .reasoning-icon {
  color: #f5d020;
}

.reasoning-label {
  font-size: 22rpx;
  font-weight: 500;
  color: #8e8e93;
  line-height: 1;
}

.reasoning-toggle-btn.is-reasoning .reasoning-label {
  color: #ffffff;
}

.input-area {
  display: flex;
  align-items: flex-end;
  background-color: rgba(0, 0, 0, 0.02);
  border-radius: 40rpx;
  padding: 6rpx 6rpx 6rpx 28rpx;
  border: 1px solid transparent;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.input-area.is-focused {
  background-color: #ffffff;
  border-color: rgba(0, 0, 0, 0.1);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
}

.chat-input {
  flex: 1;
  min-height: 48rpx;
  max-height: 200rpx;
  padding: 14rpx 0;
  font-size: 28rpx;
  color: #1c1c1e;
  line-height: 1.4;
  height: auto;
}

.send-btn {
  width: 68rpx;
  height: 68rpx;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-left: 16rpx;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.send-btn.is-active {
  background-color: #1c1c1e;
}

.send-btn.is-active:active {
  transform: scale(0.92);
  background-color: #000000;
}

.send-btn.is-active .send-icon {
  /* 由于 SVG 经由 <image> 引入时，内部 currentColor 渲染默认会因为外联作用域问题降级为黑色， */
  /* 我们在这里通过 CSS 滤镜将黑色图像黑白反转为白色，实现在黑色背景上的优雅对比。 */
  filter: brightness(0) invert(1);
}

.send-icon {
  color: #ffffff;
}

/* ===== 消息编辑模态框 ===== */
.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(10px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.2s ease;
}

.edit-modal {
  width: 580rpx;
  background-color: #ffffff;
  border-radius: 28rpx;
  padding: 44rpx 36rpx;
  display: flex;
  flex-direction: column;
  gap: 28rpx;
  box-shadow: 0 15px 35px rgba(0, 0, 0, 0.1);
  border: 1px solid rgba(0, 0, 0, 0.05);
}

.modal-title {
  font-size: 32rpx;
  font-weight: 600;
  color: #1c1c1e;
  text-align: center;
}

.edit-textarea {
  width: 100%;
  height: 260rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 16rpx;
  padding: 20rpx 24rpx;
  font-size: 28rpx;
  color: #1c1c1e;
  line-height: 1.5;
  box-sizing: border-box;
}

.edit-textarea:focus {
  border-color: #1c1c1e;
  background-color: #ffffff;
}

.modal-actions {
  display: flex;
  justify-content: space-between;
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
  transform: scale(0.97);
}

/* ===== 状态属性右侧抽屉面板 ===== */
.status-panel-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(12px);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}

.status-panel {
  width: 82vw;
  max-width: 600rpx;
  height: 100%;
  background-color: #f8f8fa;
  display: flex;
  flex-direction: column;
  animation: slideInRight 0.35s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: -12px 0 48px rgba(0, 0, 0, 0.1);
}

@keyframes slideInRight {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

/* Panel header bar (close button only) */
.panel-header {
  padding-top: env(safe-area-inset-top, 40rpx);
  height: calc(env(safe-area-inset-top, 40rpx) + 80rpx);
  display: flex;
  justify-content: flex-end;
  align-items: flex-end;
  padding-right: 28rpx;
  padding-bottom: 12rpx;
  background-color: #f8f8fa;
}

.close-btn {
  width: 52rpx;
  height: 52rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.05);
  color: #8e8e93;
  transition: background-color 0.2s;
}

.close-btn:active {
  background-color: rgba(0, 0, 0, 0.1);
}

/* Scroll area */
.panel-content {
  flex: 1;
  height: 0;
  min-height: 0;
}

/* ===== ① 角色卡片展示 ===== */
.char-card {
  display: flex;
  align-items: center;
  gap: 24rpx;
  padding: 28rpx 32rpx 32rpx 32rpx;
  background: linear-gradient(135deg, #1c1c1e 0%, #3a3a3c 100%);
  margin: 0 20rpx 28rpx 20rpx;
  border-radius: 24rpx;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
}

.char-card-avatar {
  width: 100rpx;
  height: 100rpx;
  border-radius: 50%;
  border: 2.5px solid rgba(255, 255, 255, 0.25);
  flex-shrink: 0;
  background-color: rgba(255, 255, 255, 0.1);
}

.char-card-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10rpx;
}

.char-card-name {
  font-size: 30rpx;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: -0.3px;
}

.mood-badge {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  background-color: rgba(255, 255, 255, 0.12);
  border-radius: 40rpx;
  padding: 5rpx 16rpx;
  align-self: flex-start;
}

.mood-dot {
  width: 8rpx;
  height: 8rpx;
  border-radius: 50%;
  background-color: #34c759;
  flex-shrink: 0;
}

.mood-text {
  font-size: 20rpx;
  color: rgba(255, 255, 255, 0.85);
  font-weight: 500;
}

/* ===== 各设定区块通用 ===== */
.panel-section {
  margin: 0 20rpx 24rpx 20rpx;
  background-color: #ffffff;
  border-radius: 20rpx;
  padding: 24rpx;
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.03);
}

.section-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.section-title {
  font-size: 20rpx;
  font-weight: 700;
  color: #8e8e93;
  text-transform: uppercase;
  letter-spacing: 0.8px;
}

/* ===== ② 好感度进度条 ===== */
.affection-value {
  font-size: 24rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.progress-bg {
  width: 100%;
  height: 14rpx;
  background-color: rgba(0, 0, 0, 0.05);
  border-radius: 7rpx;
  overflow: hidden;
}

.progress-bar-gradient {
  height: 100%;
  background: linear-gradient(90deg, #ff6b9d 0%, #ff8c69 60%, #ffd93d 100%);
  border-radius: 7rpx;
  transition: width 0.5s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 2px 6px rgba(255, 107, 157, 0.4);
}

/* ===== ③ 认知信息展示框 ===== */
.cognition-box {
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 12rpx;
  padding: 20rpx;
  min-height: 120rpx;
}

.cognition-text {
  font-size: 25rpx;
  color: #3a3a3c;
  line-height: 1.65;
}

/* ===== ④ 自定义开关组件 ===== */
.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4rpx 0;
}

.setting-row-left {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.setting-row-icon {
  color: #8e8e93;
}

.setting-row-label {
  font-size: 27rpx;
  font-weight: 500;
  color: #1c1c1e;
}

.custom-toggle {
  width: 88rpx;
  height: 48rpx;
  border-radius: 24rpx;
  background-color: rgba(0, 0, 0, 0.1);
  position: relative;
  transition: background-color 0.25s ease;
  flex-shrink: 0;
  cursor: pointer;
}

.custom-toggle.is-on {
  background-color: #1c1c1e;
}

.toggle-thumb {
  position: absolute;
  top: 4rpx;
  left: 4rpx;
  width: 40rpx;
  height: 40rpx;
  border-radius: 50%;
  background-color: #ffffff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.custom-toggle.is-on .toggle-thumb {
  transform: translateX(40rpx);
}

/* ===== ⑤ 功能操作按钮 ===== */
.action-btn {
  height: 80rpx;
  border-radius: 14rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10rpx;
  transition: all 0.2s;
  cursor: pointer;
}

.action-btn.outline {
  border: 1px solid rgba(0, 0, 0, 0.07);
  background-color: rgba(0, 0, 0, 0.02);
}

.action-btn.outline:active {
  background-color: rgba(0, 0, 0, 0.05);
  transform: scale(0.985);
}

.btn-icon {
  color: #3a3a3c;
}

.btn-text {
  font-size: 26rpx;
  font-weight: 500;
  color: #3a3a3c;
}

/* ===== ⑥ 危险操作区域 ===== */
.danger-section {
  background-color: rgba(255, 59, 48, 0.04);
  border: 1px solid rgba(255, 59, 48, 0.1);
}

.danger-title {
  color: #ff3b30 !important;
}

.danger-btn {
  background-color: rgba(255, 59, 48, 0.06);
  border: 1px solid rgba(255, 59, 48, 0.15);
}

.danger-btn:active {
  background-color: rgba(255, 59, 48, 0.12);
  transform: scale(0.985);
}

.danger-icon {
  color: #ff3b30;
}

.danger-btn-text {
  font-size: 26rpx;
  font-weight: 500;
  color: #ff3b30;
}

/* Custom SVG Icon Styles */
.back-icon {
  width: 44rpx;
  height: 44rpx;
}
.info-icon {
  width: 40rpx;
  height: 40rpx;
}
.reasoning-icon {
  width: 26rpx;
  height: 26rpx;
}
.setting-row-icon {
  width: 40rpx;
  height: 40rpx;
}
.send-icon {
  width: 36rpx;
  height: 36rpx;
}
.close-icon {
  width: 36rpx;
  height: 36rpx;
}
.btn-icon {
  width: 32rpx;
  height: 32rpx;
}
.danger-icon {
  width: 32rpx;
  height: 32rpx;
}

/* Fallback Unicode Icon Styles */
.back-icon-fallback {
  display: none;
}
.info-icon-fallback {
  display: none;
}
.send-icon-fallback {
  display: none;
}
.reasoning-icon-fallback {
  display: none;
}
.close-icon-fallback {
  display: none;
}
.btn-icon-fallback {
  display: none;
}
.danger-icon-fallback {
  display: none;
}

/* Android Performance Fallbacks (Disable Frosted Glass) */
.is-android .custom-header {
  backdrop-filter: none !important;
  background-color: #ffffff !important;
  border-bottom: 1px solid rgba(0, 0, 0, 0.08) !important;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.02) !important;
}

.is-android .modal-backdrop {
  backdrop-filter: none !important;
  background-color: rgba(0, 0, 0, 0.5) !important;
}

.is-android .status-panel-backdrop {
  backdrop-filter: none !important;
  background-color: rgba(0, 0, 0, 0.55) !important;
}
</style>

