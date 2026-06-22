<template>
  <view v-if="isOpen" class="modal-backdrop" :class="{ 'is-android': isAndroid }">
    <view class="modal-card">
      <view class="modal-header">
        <text class="modal-title">{{ entry === null ? '添加设定条目' : '编辑设定条目' }}</text>
        <view class="modal-close" @tap="close">
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
        <view class="modal-btn cancel" @tap="close">取消</view>
        <view 
          class="modal-btn save" 
          :class="{ 'is-disabled': !isModalFormValid }"
          @tap="submit"
        >
          保存条目
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import type { LorebookEntry } from "@/api/lorebooks";

const props = defineProps<{
  isOpen: boolean;
  entry: LorebookEntry | null;
}>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "save", entryData: LorebookEntry): void;
}>();

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

watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    if (props.entry) {
      modalForm.value = {
        keysRaw: props.entry.keys ? props.entry.keys.join(", ") : "",
        secondaryKeysRaw: props.entry.secondary_keys ? props.entry.secondary_keys.join(", ") : "",
        content: props.entry.content || "",
        constant: !!props.entry.constant,
        case_sensitive: !!props.entry.case_sensitive,
        selective: !!props.entry.selective,
        position: props.entry.position || "after_char",
        insertion_order: props.entry.insertion_order !== undefined ? props.entry.insertion_order : 100,
      };
    } else {
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
    }
  }
});

const isModalFormValid = computed(() => {
  if (!modalForm.value.content || modalForm.value.content.trim() === "") return false;
  if (modalForm.value.constant) return true;
  return modalForm.value.keysRaw.trim() !== "";
});

const close = () => {
  emit("close");
};

const submit = () => {
  if (!isModalFormValid.value) return;

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
    enabled: props.entry ? props.entry.enabled : true,
    constant: modalForm.value.constant,
    case_sensitive: modalForm.value.constant ? false : modalForm.value.case_sensitive,
    selective: modalForm.value.constant ? false : modalForm.value.selective,
    secondary_keys: modalForm.value.constant ? [] : secondary_keys,
    position: modalForm.value.position,
    insertion_order: modalForm.value.insertion_order || 100,
  };

  emit("save", entryData);
};
</script>

<style scoped>
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

.label {
  font-size: 28rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.hint-text {
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
.is-android .modal-backdrop {
  backdrop-filter: none !important;
  background-color: rgba(0, 0, 0, 0.6) !important;
}
</style>
