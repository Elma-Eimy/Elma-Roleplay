<template>
  <view class="create-container app-motion-enter">
    <!-- 头部区域 -->
    <view class="header">
      <view class="back-btn" @tap="goBack">
        <image class="back-icon" src="/static/icons/header_back.svg" mode="aspectFit" />
      </view>
      <text class="title">{{ isEditMode ? '编辑人物档案' : '创建新角色' }}</text>
      <view class="placeholder-btn"></view>
    </view>

    <scroll-view scroll-y class="form-scroll" v-if="isDataLoaded">
      <view class="form-content">
        <view class="page-intro">
          <text class="page-eyebrow">{{ isEditMode ? 'REFINE CHARACTER' : 'NEW CHARACTER' }}</text>
          <text class="page-heading">{{ isEditMode ? '让人物设定更清晰' : '从一张人物档案开始' }}</text>
          <text class="page-description">先完成形象与核心设定，高级内容可以之后慢慢补充。</text>
        </view>

        <!-- 导入人设卡区域 -->
        <view class="import-section" @tap="importCharacterCard">
          <view class="import-icon-wrap">
            <text class="import-icon-fallback">＋</text>
          </view>
          <view class="import-text-container">
            <text class="import-title">导入角色卡</text>
            <text class="import-desc">支持 PNG 图片角色卡或 JSON 配置文件</text>
          </view>
          <text class="import-badge">快捷导入</text>
        </view>

        <!-- 头像与基础信息形成完整区块 -->
        <view class="form-card identity-card">
          <view class="section-heading-row">
            <view class="section-heading-copy">
              <text class="section-kicker">01 · 角色形象</text>
              <text class="section-description">决定人物在角色库中的第一印象</text>
            </view>
            <text class="required-note">必填</text>
          </view>

          <view class="avatar-section" @tap="chooseAvatar">
            <AvatarImage
              v-if="avatarPreview"
              :src="getAvatarUrl(avatarPreview)"
              class="avatar-upload has-image"
              :lazy-load="false"
            />
            <view v-else class="avatar-upload">
              <image class="upload-icon" src="/static/icons/char_camera.svg" mode="aspectFit" />
            </view>
            <view class="avatar-copy">
              <text class="upload-text">{{ avatarPreview ? '更换角色头像' : '选择角色头像' }}</text>
              <text class="upload-hint">保留原图上传，不限制图片尺寸</text>
            </view>
          </view>

          <view class="form-group">
            <text class="label">姓名</text>
            <input class="input" v-model="form.name" placeholder="例如：赛博黑客、AI 助理..." />
          </view>

          <view class="form-group">
            <text class="label">人物背景</text>
            <textarea class="textarea" auto-height v-model="form.description" placeholder="写下角色的身份、经历与核心性格..." :maxlength="-1"></textarea>
          </view>

          <view class="form-group">
            <text class="label">开场白</text>
            <textarea class="textarea-small" auto-height v-model="form.first_mes" placeholder="新故事开始时，角色主动说出的第一句话..." :maxlength="-1"></textarea>
          </view>
        </view>

        <!-- 高级字段按主题独立折叠 -->
        <view class="advanced-area">
          <view class="section-heading-row advanced-heading">
            <view class="section-heading-copy">
              <text class="section-kicker">02 · 深入设定</text>
              <text class="section-description">按需要展开，不必一次写完所有内容</text>
            </view>
          </view>

          <view class="advanced-panel">
            <view class="advanced-toggle" @tap="toggleAdvancedSection('identity')">
              <view class="advanced-copy">
                <text class="advanced-text">性格与标签</text>
                <text class="advanced-summary">{{ identitySummary }}</text>
              </view>
              <image
                class="advanced-icon"
                :src="advancedSections.identity ? '/static/icons/char_caret_up.svg' : '/static/icons/char_caret_down.svg'"
                mode="aspectFit"
              />
            </view>
            <view class="advanced-section" v-if="advancedSections.identity">
              <view class="form-group">
                <text class="label">性格特征</text>
                <input class="input" v-model="form.personality" placeholder="例如：冷静、毒舌、幽默" />
              </view>
              <view class="form-group">
                <text class="label">角色标签</text>
                <text class="label-hint">多个标签使用英文逗号分隔</text>
                <input class="input" :value="(form.tags || []).join(', ')" @input="updateTags" placeholder="例如：funny, fantasy, helper" />
              </view>
            </view>
          </view>

          <view class="advanced-panel">
            <view class="advanced-toggle" @tap="toggleAdvancedSection('dialogue')">
              <view class="advanced-copy">
                <text class="advanced-text">场景与表达</text>
                <text class="advanced-summary">{{ dialogueSummary }}</text>
              </view>
              <image
                class="advanced-icon"
                :src="advancedSections.dialogue ? '/static/icons/char_caret_up.svg' : '/static/icons/char_caret_down.svg'"
                mode="aspectFit"
              />
            </view>
            <view class="advanced-section" v-if="advancedSections.dialogue">
              <view class="form-group">
                <text class="label">对话所处场景</text>
                <textarea class="textarea-small" auto-height v-model="form.scenario" placeholder="例如：一间昏暗潮湿的地下酒吧里。" :maxlength="-1"></textarea>
              </view>
              <view class="form-group">
                <text class="label">对话句式示例</text>
                <textarea class="textarea" auto-height v-model="form.mes_example" placeholder="用几段示例强化角色的表达风格。" :maxlength="-1"></textarea>
              </view>
            </view>
          </view>

          <view class="advanced-panel">
            <view class="advanced-toggle" @tap="toggleAdvancedSection('system')">
              <view class="advanced-copy">
                <view class="advanced-title-row">
                  <text class="advanced-text">提示词与备注</text>
                  <text class="expert-badge">进阶</text>
                </view>
                <text class="advanced-summary">{{ systemSummary }}</text>
              </view>
              <image
                class="advanced-icon"
                :src="advancedSections.system ? '/static/icons/char_caret_up.svg' : '/static/icons/char_caret_down.svg'"
                mode="aspectFit"
              />
            </view>
            <view class="advanced-section" v-if="advancedSections.system">
              <view class="form-group">
                <text class="label">创作者备忘录</text>
                <textarea class="textarea-small" auto-height v-model="form.creator_notes" placeholder="记录创作说明或使用提示..." :maxlength="-1"></textarea>
              </view>
              <view class="form-group">
                <text class="label">系统设定覆盖</text>
                <text class="label-hint">留空时沿用全局系统预设</text>
                <textarea class="textarea-small" auto-height v-model="form.system_prompt_override" placeholder="覆盖全局默认系统预设提示词" :maxlength="-1"></textarea>
              </view>
              <view class="form-group">
                <text class="label">历史末端注入指令</text>
                <text class="label-hint">每轮生成前追加到对话历史末端</text>
                <textarea class="textarea-small" auto-height v-model="form.post_history_instructions" placeholder="例如：始终使用第一人称回复。" :maxlength="-1"></textarea>
              </view>
            </view>
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
import { uploadAvatar, parseCharacter, createCharacter, updateCharacter, getAvatarUrl, getCharacter } from "@/api/characters";
import type { CharacterBase } from "@/api/characters";
import { createSession } from "@/api/sessions";
import { usePersonaStore } from "@/store/personaStore";
import AvatarImage from "@/components/common/AvatarImage.vue";
const personaStore = usePersonaStore();
type AdvancedSectionKey = "identity" | "dialogue" | "system";

const advancedSections = ref<Record<AdvancedSectionKey, boolean>>({
  identity: false,
  dialogue: false,
  system: false,
});
const avatarPreview = ref<string>("");
const isEditMode = ref(false);
const editingCharId = ref<number | null>(null);
const isDataLoaded = ref(true);

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

const identitySummary = computed(() => {
  const count = Number(Boolean(form.value.personality?.trim())) + Number(Boolean(form.value.tags?.length));
  return count > 0 ? `已填写 ${count} 项` : "性格关键词与检索标签";
});

const dialogueSummary = computed(() => {
  const count = Number(Boolean(form.value.scenario?.trim())) + Number(Boolean(form.value.mes_example?.trim()));
  return count > 0 ? `已填写 ${count} 项` : "故事环境与说话方式";
});

const systemSummary = computed(() => {
  const count = [
    form.value.creator_notes,
    form.value.system_prompt_override,
    form.value.post_history_instructions,
  ].filter((value) => Boolean(value?.trim())).length;
  return count > 0 ? `已填写 ${count} 项` : "创作备注与模型行为约束";
});

const toggleAdvancedSection = (key: AdvancedSectionKey) => {
  advancedSections.value[key] = !advancedSections.value[key];
};

const updateTags = (event: any) => {
  form.value.tags = event.detail.value
    .split(",")
    .map((tag: string) => tag.trim())
    .filter(Boolean);
};

onLoad(async (options) => {
  if (options && options.id) {
    const id = parseInt(options.id, 10);
    isEditMode.value = true;
    editingCharId.value = id;
    isDataLoaded.value = false;

    // 优先采用本地缓存的极简信息，以达到秒开渲染（防白屏闪烁）
    const quickChar = personaStore.getCharacterById(id);
    if (quickChar) {
      form.value.name = quickChar.name || "";
      avatarPreview.value = quickChar.avatar_path || "";
    }

    try {
      uni.showLoading({ title: '正在获取角色设定...' });
      const fullChar = await getCharacter(id);
      form.value = {
        name: fullChar.name || "",
        description: fullChar.description || "",
        first_mes: fullChar.first_mes || "",
        personality: fullChar.personality || "",
        scenario: fullChar.scenario || "",
        mes_example: fullChar.mes_example || "",
        creator_notes: fullChar.creator_notes || "",
        system_prompt_override: fullChar.system_prompt_override || "",
        post_history_instructions: fullChar.post_history_instructions || "",
        tags: fullChar.tags || [],
        extensions: fullChar.extensions || {},
      };
      avatarPreview.value = fullChar.avatar_path || "";

    } catch (e) {
      console.error("Failed to load full character details", e);
      uni.showToast({ title: '获取详细设定失败', icon: 'none' });
    } finally {
      isDataLoaded.value = true;
      uni.hideLoading();
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
    sizeType: ['original'],
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
  const proceedWithImport = () => {
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

  if (isEditMode.value) {
    uni.showModal({
      title: "确认导入",
      content: "导入新角色卡将覆盖当前编辑框中的所有人设内容，确定继续吗？",
      success: (modalRes) => {
        if (modalRes.confirm) {
          proceedWithImport();
        }
      }
    });
  } else {
    proceedWithImport();
  }
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
  background:
    radial-gradient(circle at 85% 4%, rgba(139, 184, 220, 0.14), transparent 26%),
    var(--app-color-background, #f7f9f7);
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
  box-sizing: border-box;
  border-bottom: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  background-color: rgba(247, 249, 247, 0.82);
  backdrop-filter: blur(18px);
  z-index: 20;
}

.back-btn {
  width: 64rpx;
  height: 64rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background-color: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.8);
  box-shadow: 0 6rpx 18rpx rgba(45, 72, 62, 0.07);
}

.back-btn:active {
  background-color: #ffffff;
  transform: scale(0.95);
}

.title {
  font-size: 32rpx;
  font-weight: 700;
  color: var(--app-color-text-primary, #26332e);
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
  padding: 38rpx var(--app-page-gutter, 36rpx) 240rpx;
  display: flex;
  flex-direction: column;
  gap: 24rpx;
}

.page-intro {
  display: flex;
  flex-direction: column;
  padding: 10rpx 4rpx 16rpx;
}

.page-eyebrow {
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: 20rpx;
  font-weight: 750;
  letter-spacing: 2rpx;
}

.page-heading {
  margin-top: 8rpx;
  color: var(--app-color-text-primary, #26332e);
  font-size: 40rpx;
  font-weight: 740;
  letter-spacing: -0.5rpx;
}

.page-description {
  margin-top: 12rpx;
  color: var(--app-color-text-secondary, #7c8983);
  font-size: 24rpx;
  line-height: 1.55;
}

/* ===== Import Section ===== */
.import-section {
  display: flex;
  align-items: center;
  background-color: rgba(255, 255, 255, 0.48);
  border: 1px dashed rgba(112, 174, 155, 0.42);
  border-radius: var(--app-radius-md, 24rpx);
  padding: 22rpx 24rpx;
  gap: 18rpx;
  transition: all 0.2s ease;
}

.import-section:active {
  background-color: rgba(255, 255, 255, 0.78);
  transform: scale(0.985);
}

.import-icon-wrap {
  width: 58rpx;
  height: 58rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 18rpx;
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
}

.import-text-container {
  display: flex;
  flex-direction: column;
  gap: 2rpx;
  flex: 1;
  min-width: 0;
}

.import-title {
  font-size: 28rpx;
  font-weight: 600;
  color: var(--app-color-text-primary, #26332e);
}

.import-desc {
  font-size: 22rpx;
  color: var(--app-color-text-secondary, #7c8983);
}

.import-badge {
  flex-shrink: 0;
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: 20rpx;
  font-weight: 650;
}

/* ===== 基础信息卡与头像区域 ===== */
.form-card {
  padding: 30rpx;
  border: 1px solid rgba(255, 255, 255, 0.82);
  border-radius: var(--app-radius-lg, 36rpx);
  background-color: rgba(255, 255, 255, 0.74);
  box-shadow: var(--app-shadow-soft, 0 12rpx 36rpx rgba(45, 72, 62, 0.08));
}

.identity-card {
  display: flex;
  flex-direction: column;
  gap: 28rpx;
}

.section-heading-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20rpx;
}

.section-heading-copy {
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}

.section-kicker {
  color: var(--app-color-text-primary, #26332e);
  font-size: 27rpx;
  font-weight: 720;
}

.section-description {
  color: var(--app-color-text-secondary, #7c8983);
  font-size: 21rpx;
}

.required-note {
  padding: 5rpx 13rpx;
  border-radius: 999rpx;
  color: #9a6d36;
  background-color: rgba(241, 201, 141, 0.2);
  font-size: 19rpx;
  font-weight: 650;
}

.avatar-section {
  display: flex;
  align-items: center;
  padding: 22rpx;
  border-radius: var(--app-radius-md, 24rpx);
  background:
    linear-gradient(135deg, rgba(112, 174, 155, 0.1), rgba(139, 184, 220, 0.1));
  border: 1px solid rgba(112, 174, 155, 0.1);
}

.avatar-copy {
  display: flex;
  flex: 1;
  min-width: 0;
  margin-left: 22rpx;
  flex-direction: column;
  align-items: flex-start;
  gap: 6rpx;
}

.avatar-upload {
  width: 116rpx;
  height: 116rpx;
  flex-shrink: 0;
  border-radius: 32rpx;
  background-color: rgba(255, 255, 255, 0.7);
  border: 1px dashed rgba(112, 174, 155, 0.38);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  box-shadow: 0 10rpx 24rpx rgba(45, 72, 62, 0.08);
}

.avatar-upload.has-image {
  border-style: solid;
  border-color: rgba(255, 255, 255, 0.76);
}

.upload-icon {
  color: #8e8e93;
}

.upload-text {
  font-size: 25rpx;
  color: var(--app-color-text-primary, #26332e);
  font-weight: 650;
}

.upload-hint {
  font-size: 20rpx;
  color: var(--app-color-text-secondary, #7c8983);
}

/* ===== 表单组样式 ===== */
.form-group {
  display: flex;
  flex-direction: column;
}

.label {
  font-size: 24rpx;
  font-weight: 600;
  color: var(--app-color-text-primary, #26332e);
  margin-bottom: 10rpx;
}

.label-hint {
  font-size: 21rpx;
  color: var(--app-color-text-secondary, #7c8983);
  margin-bottom: 10rpx;
  line-height: 1.4;
}

.input, .textarea, .textarea-small {
  background-color: rgba(247, 249, 247, 0.78);
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-radius: 18rpx;
  padding: 20rpx 24rpx;
  font-size: 28rpx;
  color: var(--app-color-text-primary, #26332e);
  box-sizing: border-box;
  transition: all 0.2s;
}

.input:focus, .textarea:focus, .textarea-small:focus {
  border-color: var(--app-color-primary, #70ae9b);
  background-color: #ffffff;
  box-shadow: 0 0 0 5rpx rgba(112, 174, 155, 0.08);
}

.input {
  height: 80rpx;
}

.textarea {
  min-height: 220rpx;
  width: 100%;
  line-height: 1.5;
  overflow-y: hidden;
}

.textarea-small {
  min-height: 130rpx;
  width: 100%;
  line-height: 1.5;
  overflow-y: hidden;
}

/* ===== 高级设置主题折叠 ===== */
.advanced-area {
  display: flex;
  flex-direction: column;
  gap: 14rpx;
}

.advanced-heading {
  padding: 22rpx 4rpx 10rpx;
}

.advanced-panel {
  overflow: hidden;
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-radius: var(--app-radius-md, 24rpx);
  background-color: rgba(255, 255, 255, 0.54);
}

.advanced-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24rpx 26rpx;
}

.advanced-copy {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: 5rpx;
}

.advanced-title-row {
  display: flex;
  align-items: center;
  gap: 10rpx;
}

.advanced-text {
  font-size: 26rpx;
  font-weight: 680;
  color: var(--app-color-text-primary, #26332e);
}

.advanced-summary {
  font-size: 20rpx;
  color: var(--app-color-text-secondary, #7c8983);
}

.expert-badge {
  padding: 3rpx 10rpx;
  border-radius: 999rpx;
  color: #5d83a1;
  background-color: rgba(139, 184, 220, 0.13);
  font-size: 18rpx;
  font-weight: 650;
}

.advanced-icon {
  flex-shrink: 0;
  opacity: 0.64;
}

.advanced-section {
  display: flex;
  flex-direction: column;
  gap: 28rpx;
  padding: 4rpx 26rpx 28rpx;
  border-top: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.06));
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
  box-sizing: border-box;
  padding: 20rpx var(--app-page-gutter, 36rpx) calc(env(safe-area-inset-bottom, 0px) + 24rpx);
  background-color: rgba(247, 249, 247, 0.88);
  backdrop-filter: blur(20px);
  border-top: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  box-shadow: 0 -12rpx 34rpx rgba(45, 72, 62, 0.06);
  z-index: 30;
}

.save-btn {
  height: 88rpx;
  background-color: var(--app-color-primary, #70ae9b);
  border-radius: 44rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.25s ease;
}

.save-btn:active {
  background-color: var(--app-color-primary-strong, #4f8e7c);
  transform: scale(0.975);
}

.save-btn.is-disabled {
  background-color: rgba(124, 137, 131, 0.14);
  pointer-events: none;
}

.save-btn.is-disabled .save-text {
  color: rgba(38, 51, 46, 0.34);
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
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: 34rpx;
  font-weight: 350;
  line-height: 1;
}
.upload-icon-fallback {
  display: none;
}
.advanced-icon-fallback {
  display: none;
}
</style>
