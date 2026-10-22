<template>
  <CharxImportSheet v-if="isOpen && charxOpen" :character-id="characterId" @close="charxOpen = false" @imported="onCharxImported" />
  <view v-if="isOpen && !charxOpen" class="import-overlay">
    <view class="sheet-backdrop" @tap="close"></view>
    <view class="import-sheet" role="dialog" aria-label="导入角色卡预览">
      <view class="sheet-header"
        ><view
          ><text class="sheet-kicker">CHARACTER IMPORT</text
          ><text class="sheet-title">{{
            card ? "确认这位故事主角" : "从角色卡开始"
          }}</text></view
        ><button
          class="sheet-close"
          aria-label="关闭导入"
          :disabled="busy"
          @tap="close"
        >
          ×
        </button></view
      >
      <view class="import-steps"
        ><text :class="{ done: !!card }">01 选择文件</text><text>—</text
        ><text :class="{ done: !!card }">02 预览内容</text><text>—</text
        ><text>03 确认导入</text></view
      >
      <scroll-view scroll-y class="sheet-scroll">
        <view class="sheet-content">
          <view v-if="!card" class="file-stage">
            <view class="file-illustration"><text>卡</text></view>
            <text class="file-title">把喜欢的角色带进故事</text>
            <text class="file-description"
              >选择原始 PNG 角色卡或 JSON
              文件。导入前可以检查设定、开场白与作者说明。</text
            >
            <!-- #ifdef APP-PLUS -->
            <text class="file-tip"
              >App 从相册选择原始 PNG，请勿使用截图或经过压缩的图片。</text
            >
            <!-- #endif -->
            <!-- #ifdef MP-WEIXIN -->
            <text class="file-tip"
              >从微信聊天文件中选择 PNG 或 JSON 角色卡。</text
            >
            <!-- #endif -->
            <button
              class="primary-button choose-button"
              :disabled="loading || picking"
              @tap="choose"
            >
              {{
                loading
                  ? "正在读取角色卡…"
                  : picking
                    ? "正在选择…"
                    : "选择角色卡文件"
              }}
            </button>
            <button :disabled="loading || picking || busy" @tap="charxOpen = true">CHARX 角色包（不超过 20 MB）</button>
            <view v-if="error" class="import-error"
              ><text class="error-title">未能导入这张角色卡</text
              ><text>{{ error }}</text
              ><text
                >普通图片没有角色设定，请从原始发布处下载角色卡再试。</text
              ></view
            >
          </view>
          <template v-else>
            <view class="preview-identity">
              <AvatarImage
                class="preview-avatar"
                :src="getAvatarUrl(card.avatar_path || '')"
                :lazy-load="false"
              />
              <view class="preview-name"
                ><text class="preview-eyebrow">已读取 · {{ fileName }}</text
                ><text class="character-name">{{ card.name }}</text
                ><text class="creator-line"
                  >{{
                    metadata.creator
                      ? "作者 " + metadata.creator
                      : "未提供作者信息"
                  }}{{
                    metadata.version ? " · 版本 " + metadata.version : ""
                  }}</text
                ></view
              >
            </view>
            <CharacterTranslationBar :available="!!translation" :busy="translating" :language="language" :error="translationError" @language="selectLanguage" @translate="translate" />
            <view class="preview-counts"
              ><view
                ><text>{{ greetings.length + 1 }}</text
                ><text>故事开场</text></view
              ><view
                ><text>{{ entries.length }}</text
                ><text>内嵌世界条目</text></view
              ><view
                ><text>{{ card.tags?.length || 0 }}</text
                ><text>角色标签</text></view
              ></view
            >
            <view v-if="missingFields.length" class="missing-notice"
              >{{
                missingFields.join("、")
              }}尚未填写，导入后可以继续补充。</view
            >
            <view v-if="current?.name" class="import-modes">
              <text class="mode-heading">如何应用到「{{ current.name }}」</text>
              <button
                class="mode-option"
                :class="{ active: mode === 'replace' }"
                @tap="mode = 'replace'"
              >
                <text>替换角色设定</text
                ><text>使用新卡内容；JSON 会保留当前头像</text>
              </button>
              <button
                class="mode-option"
                :class="{ active: mode === 'fill' }"
                @tap="mode = 'fill'"
              >
                <text>仅补充空项</text
                ><text>保留已有文字、开场白和世界设定</text>
              </button>
              <text class="mode-footnote">{{
                saveImmediately
                  ? "确认后保存设定，已有故事与聊天记录保留。"
                  : "只应用到编辑草稿，保存后才会生效。"
              }}</text>
            </view>
            <view class="preview-tabs"
              ><button
                v-for="item in tabs"
                :key="item.key"
                :class="{ active: tab === item.key }"
                @tap="tab = item.key"
              >
                {{ item.label }}
              </button></view
            >
            <view v-if="tab === 'profile'" class="preview-panel">
              <view class="preview-tags"
                ><text
                  v-for="(tag, index) in (showAllTags ? card.tags || [] : (card.tags || []).slice(0, 8))"
                  :key="index"
                  >#{{ tag }}</text
                ></view
              >
              <button v-if="(card.tags?.length || 0) > 8" class="preview-tag-toggle" @tap="showAllTags = !showAllTags">{{ showAllTags ? '收起标签' : '查看全部 ' + card.tags?.length + ' 个标签' }}</button>
              <text class="content-label">人物背景</text
              ><CharacterCardText :content="readingCard?.description" />
              <template v-if="card.personality"
                ><text class="content-label">性格</text
                ><CharacterCardText :content="readingCard?.personality"
              /></template>
              <template v-if="card.scenario"
                ><text class="content-label">故事场景</text
                ><CharacterCardText :content="readingCard?.scenario"
              /></template>
              <text
                v-if="
                  card.system_prompt_override || card.post_history_instructions
                "
                class="file-tip"
                >包含自定义提示词，导入后可在编辑页的「提示词与备注」中检查。</text
              >
            </view>
            <CharacterGreetings
              v-else-if="tab === 'greetings'"
              v-model="greetingIndex"
              :first-mes="readingCard?.first_mes"
              :alternates="greetings"
              :character-name="card.name"
            />
            <view v-else-if="tab === 'notes'" class="preview-panel"
              ><text class="content-label">作者说明 · 使用建议</text
              ><CharacterCardText
                :content="readingCard?.creator_notes"
                empty-text="作者没有附加使用说明。"
            /></view>
            <view v-else-if="tab === 'examples'" class="preview-panel">
              <text class="content-label">对话示例</text>
              <CharacterCardText :content="readingCard?.mes_example" source empty-text="这张卡没有对话示例。" />
            </view>
            <view v-else class="preview-panel"
              ><text class="file-tip"
                >内嵌世界书会随角色保存，可在人物档案的「世界」页查看。条目按各自的启用和触发条件参与对话。</text
              >
              <view
                v-for="(entry, index) in entries.slice(0, worldLimit)"
                :key="index"
                class="world-entry"
                ><text class="content-label"
                  >{{ entry.name || entry.comment || "条目 " + (index + 1)
                  }}{{ entry.enabled === false ? " · 已停用" : "" }}</text
                ><CharacterCardText
                  :content="
                    typeof entry.content === 'string' ? entry.content : ''
                  "
                  source
              /></view>
              <button
                v-if="entries.length > worldLimit"
                class="secondary-button"
                @tap="worldLimit += 5"
              >
                继续查看条目（{{ worldLimit }} / {{ entries.length }}）</button
              ><text v-if="!entries.length" class="file-tip"
                >这张卡没有附带内嵌世界书。</text
              >
            </view>
          </template>
        </view>
      </scroll-view>
      <view v-if="card" class="sheet-footer"
        ><button
          class="secondary-button"
          :disabled="busy || loading || picking"
          @tap="choose"
        >
          换一张卡</button
        ><button
          class="primary-button"
          :disabled="busy || loading"
          @tap="confirm"
        >
          {{
            busy
              ? "正在保存…"
              : saveImmediately
                ? "确认并保存设定"
                : "导入到编辑草稿"
          }}
        </button></view
      >
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from "vue";
import type { CharacterBase } from "@/api/characters";
import { getAvatarUrl } from "@/api/characters";
import { useCharacterCardImport } from "@/composables/useCharacterCardImport";
import { useCharacterTranslation } from "@/composables/useCharacterTranslation";
import CharacterTranslationBar from "./CharacterTranslationBar.vue";
import { chooseCharacterCard } from "@/utils/chooseCharacterCard";
import {
  getCardGreetings,
  getCardMetadata,
  getEmbeddedEntries,
  mergeCharacterCard,
} from "@/utils/characterCard";
import type { CardImportMode } from "@/utils/characterCard";
import AvatarImage from "@/components/common/AvatarImage.vue";
import CharacterCardText from "./CharacterCardText.vue";
import CharacterGreetings from "./CharacterGreetings.vue";
import CharxImportSheet from "./CharxImportSheet.vue";
import type { CharxImportResult } from "@/types/charx";
const props = defineProps<{
  isOpen: boolean;
  current?: CharacterBase;
  busy?: boolean;
  saveImmediately?: boolean;
  characterId?: number | null;
}>();
const emit = defineEmits<{
  (event: "update:isOpen", value: boolean): void;
  (event: "apply", card: CharacterBase): void;
  (event: "charx-imported", id: number, result: CharxImportResult): void;
}>();
const { card, loading, error, reset, load } = useCharacterCardImport();
const { translation, language, selectLanguage, translating, error: translationError, readingCard, translate } = useCharacterTranslation(() => props.isOpen ? card.value : null);
const picking = ref(false);
const charxOpen = ref(false);
function onCharxImported(id: number, result: CharxImportResult) {
  charxOpen.value = false;
  emit("update:isOpen", false);
  emit("charx-imported", id, result);
}
const fileName = ref("");
const mode = ref<CardImportMode>("replace");
const tab = ref("profile");
const greetingIndex = ref<number | null>(null);
const worldLimit = ref(5);
const showAllTags = ref(false);
const tabs = [
  { key: "profile", label: "人物设定" },
  { key: "greetings", label: "故事开场" },
  { key: "notes", label: "作者说明" },
  { key: "examples", label: "对话示例" },
  { key: "world", label: "内嵌世界" },
];
const metadata = computed(() =>
  getCardMetadata(card.value || { name: "", description: "" }),
);
const greetings = computed(() => getCardGreetings(readingCard.value || {}));
const entries = computed(() =>
  card.value ? getEmbeddedEntries(card.value) : [],
);
const missingFields = computed(() =>
  [
    ["人物背景", card.value?.description],
    ["默认开场白", card.value?.first_mes],
  ]
    .filter((item) => !item[1]?.trim())
    .map((item) => item[0]),
);
let session = 0;
watch(
  () => props.isOpen,
  () => {
    session++;
    charxOpen.value = false;
    reset();
    picking.value = false;
    mode.value = "replace";
    tab.value = "profile";
    greetingIndex.value = null;
    worldLimit.value = 5;
    showAllTags.value = false;
  },
);
onBeforeUnmount(() => {
  session++;
  reset();
});
const close = () => {
  if (!props.busy) {
    session++;
    reset();
    emit("update:isOpen", false);
  }
};
const choose = async () => {
  if (picking.value || loading.value || props.busy) return;
  const request = session;
  picking.value = true;
  try {
    const file = await chooseCharacterCard();
    if (!file || request !== session || !props.isOpen) return;
    fileName.value = file.name;
    tab.value = "profile";
    greetingIndex.value = null;
    worldLimit.value = 5;
    await load(file.path);
  } catch (failure) {
    if (request === session)
      error.value =
        failure instanceof Error ? failure.message : "无法选择文件。";
  } finally {
    if (request === session) picking.value = false;
  }
};
const confirm = () => {
  if (card.value && !props.busy)
    emit(
      "apply",
      mergeCharacterCard(
        props.current || { name: "", description: "" },
        card.value,
        mode.value,
      ),
    );
};
</script>

<style scoped>
.import-overlay {
  position: fixed;
  inset: 0;
  z-index: 350;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24rpx;
  box-sizing: border-box;
}
.sheet-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(28, 44, 37, 0.46);
  backdrop-filter: blur(8px);
}
.import-sheet {
  position: relative;
  width: 100%;
  max-width: 780px;
  height: 90vh;
  height: 90dvh;
  display: flex;
  flex-direction: column;
  border-radius: 32rpx;
  background: var(--app-color-surface, #fff);
  overflow: hidden;
  box-shadow: 0 24px 90px #15291e33;
}
.sheet-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 30rpx 32rpx 22rpx;
  gap: 20rpx;
}
.sheet-kicker {
  display: block;
  font-size: 18rpx;
  letter-spacing: 3rpx;
  color: #71917f;
  margin-bottom: 8rpx;
}
.sheet-title {
  display: block;
  font-size: 34rpx;
  font-weight: 700;
  color: #26332e;
}
.sheet-close {
  margin: 0;
  width: 64rpx;
  height: 64rpx;
  padding: 0;
  line-height: 58rpx;
  border-radius: 50%;
  font-size: 40rpx;
  background: #f3f6f3;
  color: #718177;
}
.sheet-close::after,
.preview-tabs button::after,
.mode-option::after {
  border: 0;
}
.import-steps {
  display: flex;
  justify-content: space-between;
  gap: 8rpx;
  background: #f5f8f5;
  padding: 18rpx 32rpx;
  font-size: 20rpx;
  color: #89958d;
}
.import-steps .done {
  color: #4f8e7c;
}
.sheet-scroll {
  flex: 1;
  height: 0;
  min-height: 0;
}
.sheet-content {
  padding: 32rpx;
}
.file-stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 24rpx;
  padding: 40rpx 0;
}
.file-illustration {
  width: 120rpx;
  height: 150rpx;
  background: linear-gradient(150deg, #f3eee1, #dbece2);
  border: 6rpx solid #fff;
  border-radius: 18rpx;
  box-shadow: 0 12rpx 40rpx #405c4220;
  transform: rotate(-8deg);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 42rpx;
  color: #66856c;
  margin-bottom: 12rpx;
}
.file-title {
  font-size: 32rpx;
  font-weight: 600;
  color: #26332e;
}
.file-description {
  font-size: 27rpx;
  line-height: 1.8;
  text-align: center;
  color: #697c70;
  max-width: 540rpx;
}
.file-tip {
  display: block;
  font-size: 24rpx;
  line-height: 1.8;
  color: #7c8983;
  margin-bottom: 20rpx;
}
.primary-button,
.secondary-button {
  margin: 0;
  font-size: 26rpx;
  border-radius: 18rpx;
  padding: 0 26rpx;
  line-height: 84rpx;
}
.primary-button {
  background: #4f8e7c;
  color: white;
  font-weight: 600;
}
.secondary-button {
  background: #f3f6f3;
  color: #597363;
}
.choose-button {
  min-width: 360rpx;
  margin-top: 12rpx;
}
.import-error {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
  padding: 24rpx;
  background: #fff5ec;
  border: 1px solid #f0dcc7;
  border-radius: 20rpx;
  font-size: 25rpx;
  color: #8c6345;
  line-height: 1.7;
  overflow-wrap: anywhere;
  width: 100%;
  box-sizing: border-box;
}
.error-title {
  font-weight: 600;
}
.preview-identity {
  display: flex;
  align-items: center;
  gap: 24rpx;
}
.preview-avatar {
  flex-shrink: 0;
  width: 120rpx;
  height: 150rpx;
  border-radius: 20rpx;
  overflow: hidden;
}
.preview-name {
  min-width: 0;
}
.preview-eyebrow {
  display: block;
  font-size: 20rpx;
  color: #7c8983;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.character-name {
  display: block;
  font-size: 34rpx;
  font-weight: 700;
  color: #26332e;
  margin: 10rpx 0;
  word-break: break-word;
}
.creator-line {
  display: block;
  font-size: 23rpx;
  color: #6f8577;
}
.preview-counts {
  display: flex;
  background: #f3f7f3;
  border-radius: 20rpx;
  margin: 28rpx 0;
  padding: 22rpx 0;
}
.preview-counts view {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
}
.preview-counts text:first-child {
  font-size: 34rpx;
  font-weight: 700;
  color: #4f7560;
}
.preview-counts text:last-child {
  font-size: 21rpx;
  color: #7c8983;
}
.missing-notice {
  padding: 20rpx;
  background: #fff6e8;
  color: #8f7045;
  font-size: 24rpx;
  line-height: 1.7;
  border-radius: 16rpx;
  margin-bottom: 24rpx;
}
.import-modes {
  padding: 24rpx;
  border: 1px solid #e0e8e1;
  border-radius: 20rpx;
  margin-bottom: 28rpx;
}
.mode-heading {
  display: block;
  font-size: 25rpx;
  font-weight: 600;
  margin-bottom: 16rpx;
}
.mode-option {
  margin: 12rpx 0;
  padding: 18rpx 20rpx;
  border: 1px solid #e2e9e3;
  border-radius: 14rpx;
  background: white;
  line-height: 1.5;
  text-align: left;
}
.mode-option.active {
  border-color: #4f8e7c;
  background: #eef6f1;
}
.mode-option text {
  display: block;
  font-size: 24rpx;
  color: #355b47;
}
.mode-option text:last-child {
  font-size: 21rpx;
  color: #7c8983;
  margin-top: 6rpx;
}
.mode-footnote {
  font-size: 22rpx;
  color: #7c8983;
}
.preview-tabs {
  display: flex;
  border-bottom: 1px solid #e2e9e3;
  margin-bottom: 28rpx;
}
.preview-tabs button {
  flex: 1;
  padding: 0;
  margin: 0;
  background: transparent;
  border-radius: 0;
  font-size: 24rpx;
  color: #7c8983;
  line-height: 76rpx;
}
.preview-tabs .active {
  color: #4f8e7c;
  font-weight: 600;
  border-bottom: 4rpx solid #4f8e7c;
}
.content-label {
  display: block;
  font-size: 26rpx;
  font-weight: 600;
  color: #355b47;
  margin: 24rpx 0 18rpx;
}
.preview-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
}
.preview-tag-toggle { margin: 12rpx 0 0; padding: 0; background: transparent; color: #4f8e7c; font-size: 22rpx; line-height: 48rpx; text-align: left; }
.preview-tag-toggle::after { border: 0; }
.preview-tags text {
  padding: 7rpx 14rpx;
  background: #f4f5ef;
  color: #7a8264;
  font-size: 20rpx;
  border-radius: 10rpx;
}
.world-entry {
  border-bottom: 1px solid #e2e9e3;
  padding-bottom: 24rpx;
}
.sheet-footer {
  display: flex;
  gap: 16rpx;
  padding: 24rpx 32rpx;
  padding-bottom: max(24rpx, env(safe-area-inset-bottom));
  border-top: 1px solid #e2e9e3;
  background: white;
}
.sheet-footer .primary-button {
  flex: 1;
}
@media (max-width: 600px) {
  .import-overlay {
    padding: 0;
    align-items: flex-end;
  }
  .import-sheet {
    height: 94vh;
    height: 94dvh;
    border-radius: 30rpx 30rpx 0 0;
  }
}
</style>
