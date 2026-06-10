<template>
  <view class="create-container">
    <!-- 头部区域 -->
    <view class="header">
      <view class="back-btn" @tap="goBack">
        <image class="back-icon" src="/static/icons/header_back.svg" mode="aspectFit" />
      </view>
      <text class="title">{{ isEditMode ? '编辑角色人设' : '创建角色人设' }}</text>
      <view class="placeholder-btn"></view>
    </view>

    <scroll-view scroll-y class="form-scroll">
      <view class="form-content">
        
        <!-- 导入人设卡区域 -->
        <view class="import-section" @tap="importCharacterCard">
          <text class="import-icon-fallback">📥</text>
          <view class="import-text-container">
            <text class="import-title">导入角色卡</text>
            <text class="import-desc">支持 PNG 图片角色卡或 JSON 配置文件</text>
          </view>
        </view>

        <!-- 头像上传与预览区域 -->
        <view class="avatar-section" @tap="chooseAvatar">
          <image v-if="avatarPreview" :src="getAvatarUrl(avatarPreview)" class="avatar-upload has-image" mode="aspectFill" />
          <view v-else class="avatar-upload">
            <image class="upload-icon" src="/static/icons/char_camera.svg" mode="aspectFit" />
          </view>
          <text class="upload-text">{{ avatarPreview ? '更换头像' : '上传头像' }}</text>
        </view>

        <!-- 基础信息表单 -->
        <view class="form-group">
          <text class="label">姓名 *</text>
          <input class="input" v-model="form.name" placeholder="例如：赛博黑客、AI 助理..." />
        </view>

        <view class="form-group">
          <text class="label">人设背景描述 *</text>
          <textarea class="textarea" v-model="form.description" placeholder="详细输入角色的背景设定、身份以及性格特征..." :maxlength="1000"></textarea>
        </view>

        <view class="form-group">
          <text class="label">开场白 / 第一句话 *</text>
          <textarea class="textarea-small" v-model="form.first_mes" placeholder="当新对话开启时，角色主动对你说的第一句话..." :maxlength="1000"></textarea>
        </view>

        <!-- 高级人设设置开关 -->
        <view class="advanced-toggle" @tap="showAdvanced = !showAdvanced">
          <text class="advanced-text">高级人设设置</text>
          <image 
            class="advanced-icon" 
            :src="showAdvanced ? '/static/icons/char_caret_up.svg' : '/static/icons/char_caret_down.svg'" 
            mode="aspectFit" 
          />
        </view>

        <!-- 高级人设字段列表 -->
        <view class="advanced-section" v-if="showAdvanced">
          <view class="form-group">
            <text class="label">性格特征标签</text>
            <input class="input" v-model="form.personality" placeholder="例如：冷静、毒舌、幽默" />
          </view>

          <view class="form-group">
            <text class="label">对话所处场景</text>
            <textarea class="textarea-small" v-model="form.scenario" placeholder="场景上下文，例如：一间昏暗潮湿的地下酒吧里。"></textarea>
          </view>

          <view class="form-group">
            <text class="label">对话句式示例</text>
            <textarea class="textarea" v-model="form.mes_example" placeholder="展示角色对话的例句以强化风格约束。"></textarea>
          </view>

          <view class="form-group">
            <text class="label">创作者备忘录</text>
            <textarea class="textarea-small" v-model="form.creator_notes" placeholder="对该角色卡片的创作者说明信息（支持多行输入）..."></textarea>
          </view>
          
          <view class="form-group">
            <text class="label">系统设定覆盖 (Override)</text>
            <textarea class="textarea-small" v-model="form.system_prompt_override" placeholder="覆盖全局默认系统预设提示词（高级功能）"></textarea>
          </view>

          <view class="form-group">
            <text class="label">历史末端注入指令</text>
            <text class="label-hint">在每轮对话历史末尾追加的额外指令（会在 AI 生成前作为最后上下文注入）</text>
            <textarea class="textarea-small" v-model="form.post_history_instructions" placeholder="例如：请始终用第一人称回复，且不超过200字。"></textarea>
          </view>

          <view class="form-group">
            <text class="label">角色标签</text>
            <text class="label-hint">多个标签用英文逗号分隔，保存时自动转换</text>
            <input class="input" :value="(form.tags || []).join(', ')" @input="(e: any) => form.tags = e.detail.value.split(',').map((t: string) => t.trim()).filter(Boolean)" placeholder="例如：funny, fantasy, helper" />
          </view>
        </view>

      </view>
    </scroll-view>

    <!-- 底部操作栏 -->
    <view class="footer">
      <view 
        class="save-btn" 
        :class="{ 'is-disabled': !isFormValid }"
        @tap="saveCharacter"
      >
        <text class="save-text">{{ isEditMode ? '保存修改' : '保存并开启对话' }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { uploadAvatar, parseCharacter, createCharacter, updateCharacter, getAvatarUrl } from "@/api/characters";
import type { CharacterBase } from "@/api/characters";
import { createSession } from "@/api/sessions";
import { usePersonaStore } from "@/store/personaStore";
const personaStore = usePersonaStore();
const showAdvanced = ref(false);
const avatarPreview = ref<string>("");
const isEditMode = ref(false);
const editingCharId = ref<number | null>(null);

const form = ref<CharacterBase>({
  name: "",
  description: "",
  first_mes: "",
  personality: "",
  scenario: "",
  mes_example: "",
  creator_notes: "",
  system_prompt_override: "",
  post_history_instructions: "",
  tags: [],
});

const isFormValid = computed(() => {
  return form.value.name.trim() !== "" && 
         form.value.description.trim() !== "" && 
         form.value.first_mes?.trim() !== "";
});

onLoad((options) => {
  if (options && options.id) {
    const id = parseInt(options.id, 10);
    const char = personaStore.getCharacterById(id);
    if (char) {
      isEditMode.value = true;
      editingCharId.value = id;
      form.value = { ...char };
      avatarPreview.value = char.avatar_path || "";
    }
  }
});

const goBack = () => {
  const pages = getCurrentPages();
  if (pages.length > 1) {
    uni.navigateBack();
  } else {
    uni.switchTab({
      url: "/pages/character/index"
    });
  }
};

const chooseAvatar = () => {
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: ['album', 'camera'],
    success: async (res) => {
      const tempPath = res.tempFilePaths[0];
      try {
        uni.showLoading({ title: '正在上传头像...' });
        const uploadRes = await uploadAvatar(tempPath);
        avatarPreview.value = uploadRes.avatar_path;
      } catch (e) {
        console.error("Upload failed", e);
        uni.showToast({ title: '上传头像失败', icon: 'none' });
      } finally {
        uni.hideLoading();
      }
    }
  });
};

const importCharacterCard = () => {
  // #ifdef APP-PLUS
  // 手机 App 平台：由于不支持 uni.chooseFile，使用 uni.chooseImage 从相册选择 PNG 角色卡
  // 指定 sizeType: ['original']（原图）以防止图片被系统压缩导致 EXIF/iTXt 元数据丢失
  uni.chooseImage({
    count: 1,
    sizeType: ['original'],
    sourceType: ['album'],
    success: async (res) => {
      uni.showLoading({ title: '正在解析角色卡...' });
      try {
        const tempFilePath = res.tempFilePaths[0];
        const parseRes = await parseCharacter(tempFilePath);
        form.value = {
          ...form.value,
          ...parseRes.data
        };
        
        // 自动作为头像图片上传并填充预览
        try {
          const uploadRes = await uploadAvatar(tempFilePath);
          avatarPreview.value = uploadRes.avatar_path;
        } catch (uploadErr) {
          console.error("Auto avatar upload failed", uploadErr);
        }
        
        uni.showToast({ title: '解析并导入成功', icon: 'success' });
      } catch (e) {
        console.error("Parsing failed", e);
        uni.showToast({ title: '解析失败，请检查格式', icon: 'none' });
      } finally {
        uni.hideLoading();
      }
    },
    fail: (err) => {
      console.log("选择图片取消或失败", err);
    }
  });
  // #endif

  // #ifndef APP-PLUS
  // 非 App 平台（H5网页等）：使用 uni.chooseFile 以同时支持选择 PNG 图片和 JSON 配置文件
  uni.chooseFile({
    count: 1,
    type: "all",
    extension: [".png", ".json"],
    success: async (res) => {
      uni.showLoading({ title: '正在解析角色卡...' });
      try {
        const tempFilePath = res.tempFilePaths[0];
        const parseRes = await parseCharacter(tempFilePath);
        form.value = {
          ...form.value,
          ...parseRes.data
        };
        
        // 如果用户选择的是 PNG 格式的角色卡，自动作为其头像图片上传并填充预览
        if (tempFilePath.toLowerCase().endsWith('.png')) {
          try {
            const uploadRes = await uploadAvatar(tempFilePath);
            avatarPreview.value = uploadRes.avatar_path;
          } catch (uploadErr) {
            console.error("Auto avatar upload failed", uploadErr);
          }
        } else {
          avatarPreview.value = parseRes.data.avatar_path || "";
        }
        
        uni.showToast({ title: '解析并导入成功', icon: 'success' });
      } catch (e) {
        console.error("Parsing failed", e);
        uni.showToast({ title: '解析失败，请检查格式', icon: 'none' });
      } finally {
        uni.hideLoading();
      }
    },
    fail: (err) => {
      console.log("选择文件取消或失败", err);
    }
  });
  // #endif
};

const saveCharacter = async () => {
  if (!isFormValid.value) return;
  
  try {
    uni.showLoading({ title: '正在保存人设...' });
    const characterData = {
      ...form.value,
      avatar_path: avatarPreview.value
    };

    if (isEditMode.value && editingCharId.value !== null) {
      await updateCharacter(editingCharId.value, characterData);
      await personaStore.loadCharacters();
      uni.hideLoading();
      uni.showToast({ title: '修改已保存', icon: 'success' });
      setTimeout(() => {
        uni.navigateBack();
      }, 1000);
    } else {
      const res = await createCharacter(characterData);
      const sessionRes = await createSession({
        character_id: res.character_id,
        title: "新会话"
      });
      await personaStore.loadCharacters();
      uni.hideLoading();
      uni.redirectTo({
        url: `/pages/chat/chat?sessionId=${sessionRes.session_id}`
      });
    }
  } catch (e) {
    uni.hideLoading();
    uni.showToast({ title: '保存失败', icon: 'none' });
    console.error(e);
  }
};
</script>

<style scoped>
.create-container {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100%;
  background-color: #ffffff;
}

/* ===== Header ===== */
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: env(safe-area-inset-top, 40rpx);
  height: calc(env(safe-area-inset-top, 40rpx) + 110rpx);
  padding-left: 36rpx;
  padding-right: 36rpx;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
}

.back-btn {
  width: 60rpx;
  height: 60rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.02);
}

.back-btn:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.title {
  font-size: 32rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.placeholder-btn {
  width: 60rpx;
}

/* ===== Form Content ===== */
.form-scroll {
  flex: 1;
  height: 0;
  min-height: 0;
}

.form-content {
  padding: 36rpx 36rpx 200rpx 36rpx;
  display: flex;
  flex-direction: column;
  gap: 36rpx;
}

/* ===== Import Section ===== */
.import-section {
  display: flex;
  align-items: center;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px dashed rgba(0, 0, 0, 0.08);
  border-radius: 20rpx;
  padding: 24rpx 32rpx;
  gap: 24rpx;
  transition: all 0.2s ease;
}

.import-section:active {
  background-color: rgba(0, 0, 0, 0.05);
  transform: scale(0.985);
}

.import-icon {
  color: #1c1c1e;
}

.import-text-container {
  display: flex;
  flex-direction: column;
  gap: 2rpx;
}

.import-title {
  font-size: 28rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.import-desc {
  font-size: 22rpx;
  color: #8e8e93;
}

/* ===== 头像区域 ===== */
.avatar-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: 16rpx 0;
}

.avatar-upload {
  width: 140rpx;
  height: 140rpx;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px dashed rgba(0, 0, 0, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12rpx;
  overflow: hidden;
}

.avatar-upload.has-image {
  border-style: solid;
  border-color: rgba(0, 0, 0, 0.05);
}

.upload-icon {
  color: #8e8e93;
}

.upload-text {
  font-size: 22rpx;
  color: #8e8e93;
  font-weight: 500;
}

/* ===== 表单组样式 ===== */
.form-group {
  display: flex;
  flex-direction: column;
}

.label {
  font-size: 24rpx;
  font-weight: 600;
  color: #48484a;
  margin-bottom: 8rpx;
}

.label-hint {
  font-size: 21rpx;
  color: #8e8e93;
  margin-bottom: 10rpx;
  line-height: 1.4;
}

.input, .textarea, .textarea-small {
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 16rpx;
  padding: 20rpx 24rpx;
  font-size: 28rpx;
  color: #1c1c1e;
  box-sizing: border-box;
  transition: all 0.2s;
}

.input:focus, .textarea:focus, .textarea-small:focus {
  border-color: #1c1c1e;
  background-color: #ffffff;
}

.input {
  height: 80rpx;
}

.textarea {
  height: 220rpx;
  width: 100%;
}

.textarea-small {
  height: 130rpx;
  width: 100%;
}

/* ===== 高级设置切换 ===== */
.advanced-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24rpx 0;
  border-top: 1px solid rgba(0, 0, 0, 0.03);
  margin-top: 16rpx;
}

.advanced-text {
  font-size: 28rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.advanced-icon {
  color: #8e8e93;
}

.advanced-section {
  display: flex;
  flex-direction: column;
  gap: 36rpx;
  animation: slideDown 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ===== 底部操作区域 ===== */
.footer {
  position: fixed;
  bottom: 0;
  left: 0;
  width: 100%;
  padding: 24rpx 36rpx calc(env(safe-area-inset-bottom, 24rpx) + 24rpx);
  background-color: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(20px);
  border-top: 1px solid rgba(0, 0, 0, 0.05);
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.02);
}

.save-btn {
  height: 88rpx;
  background-color: #1c1c1e;
  border-radius: 44rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.25s ease;
}

.save-btn:active {
  background-color: #000000;
  transform: scale(0.975);
}

.save-btn.is-disabled {
  background-color: rgba(0, 0, 0, 0.08);
  pointer-events: none;
}

.save-btn.is-disabled .save-text {
  color: rgba(0, 0, 0, 0.25);
}

.save-text {
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 600;
}

/* Custom SVG Icon Styles */
.back-icon {
  width: 44rpx;
  height: 44rpx;
}
.upload-icon {
  width: 48rpx;
  height: 48rpx;
}
.advanced-icon {
  width: 32rpx;
  height: 32rpx;
}

/* Fallback Unicode Icon Styles */
.back-icon-fallback {
  display: none;
}
.import-icon-fallback {
  font-size: 38rpx;
  line-height: 1;
}
.upload-icon-fallback {
  display: none;
}
.advanced-icon-fallback {
  display: none;
}
</style>
