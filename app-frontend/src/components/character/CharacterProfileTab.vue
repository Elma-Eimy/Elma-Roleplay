<template>
  <view class="profile-details-section">
    <!-- 角色背景描述卡片 -->
    <view class="section-card" :class="{ 'is-collapsed': !expanded.description }">
      <view class="section-card-header" @tap="toggleSection('description')">
        <text class="section-title">人设背景描述</text>
        <view class="expand-arrow" :class="{ 'is-expanded': expanded.description }"></view>
      </view>
      <view class="section-body-wrapper" v-if="expanded.description">
        <rich-text class="section-body" :nodes="renderedDescription" />
      </view>
    </view>

    <view class="section-card" v-if="character.scenario" :class="{ 'is-collapsed': !expanded.scenario }">
      <view class="section-card-header" @tap="toggleSection('scenario')">
        <text class="section-title">所处场景环境</text>
        <view class="expand-arrow" :class="{ 'is-expanded': expanded.scenario }"></view>
      </view>
      <view class="section-body-wrapper" v-if="expanded.scenario">
        <rich-text class="section-body" :nodes="renderedScenario" />
      </view>
    </view>

    <view class="section-card" v-if="character.first_mes" :class="{ 'is-collapsed': !expanded.first_mes }">
      <view class="section-card-header" @tap="toggleSection('first_mes')">
        <text class="section-title">开场白预设</text>
        <view class="expand-arrow" :class="{ 'is-expanded': expanded.first_mes }"></view>
      </view>
      <view class="section-body-wrapper" v-if="expanded.first_mes">
        <rich-text class="section-body italic" :nodes="renderedFirstMes" />
      </view>
    </view>

    <view class="section-card" v-if="character.mes_example" :class="{ 'is-collapsed': !expanded.mes_example }">
      <view class="section-card-header" @tap="toggleSection('mes_example')">
        <text class="section-title">对话句式示例</text>
        <view class="expand-arrow" :class="{ 'is-expanded': expanded.mes_example }"></view>
      </view>
      <view class="section-body-wrapper" v-if="expanded.mes_example">
        <rich-text class="section-body dialogue-example" :nodes="renderedMesExample" />
      </view>
    </view>

    <view class="section-card" v-if="character.creator_notes" :class="{ 'is-collapsed': !expanded.creator_notes }">
      <view class="section-card-header" @tap="toggleSection('creator_notes')">
        <text class="section-title">创作者备忘录</text>
        <view class="expand-arrow" :class="{ 'is-expanded': expanded.creator_notes }"></view>
      </view>
      <view class="section-body-wrapper" v-if="expanded.creator_notes">
        <rich-text class="section-body" :nodes="renderedCreatorNotes" />
      </view>
    </view>

    <view class="section-card" v-if="character.system_prompt_override" :class="{ 'is-collapsed': !expanded.system_prompt_override }">
      <view class="section-card-header" @tap="toggleSection('system_prompt_override')">
        <text class="section-title">系统设定覆盖</text>
        <view class="expand-arrow" :class="{ 'is-expanded': expanded.system_prompt_override }"></view>
      </view>
      <view class="section-body-wrapper" v-if="expanded.system_prompt_override">
        <rich-text class="section-body code-text" :nodes="renderedSystemPromptOverride" />
      </view>
    </view>

    <view class="section-card" v-if="character.post_history_instructions" :class="{ 'is-collapsed': !expanded.post_history_instructions }">
      <view class="section-card-header" @tap="toggleSection('post_history_instructions')">
        <text class="section-title">历史末端注入指令</text>
        <view class="expand-arrow" :class="{ 'is-expanded': expanded.post_history_instructions }"></view>
      </view>
      <view class="section-body-wrapper" v-if="expanded.post_history_instructions">
        <rich-text class="section-body code-text" :nodes="renderedPostHistoryInstructions" />
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import type { CharacterDetail } from "@/api/characters";
import { usePersonaStore } from "@/store/personaStore";
import MarkdownIt from "markdown-it";

const props = defineProps<{
  character: CharacterDetail;
}>();

const personaStore = usePersonaStore();

const expanded = ref<Record<string, boolean>>({
  description: true, // 默认展开第一项
  scenario: false,
  first_mes: false,
  mes_example: false,
  creator_notes: false,
  system_prompt_override: false,
  post_history_instructions: false,
});

const toggleSection = (key: string) => {
  expanded.value[key] = !expanded.value[key];
};

const md = new MarkdownIt({
  html: true,
  breaks: true,
  linkify: true,
});

// 替换 {{char}} / {{user}} 占位符
const replacePlaceholders = (text: string) => {
  if (!text) return "";
  const charName = props.character?.name || "角色";
  const userName = personaStore.userNickname;
  return text
    .replace(/\{\{char\}\}/gi, charName)
    .replace(/\{\{user\}\}/gi, userName);
};

const renderMarkdown = (content: string, isCode = false) => {
  if (!content) return "";
  let raw = replacePlaceholders(content);
  if (isCode) {
    raw = "```\n" + raw + "\n```";
  }
  let html = md.render(raw);
  
  if (isCode) {
    html = html.replace(/<p>/g, '<p class="md-p">');
  } else {
    html = html.replace(/<p>/g, '<p class="md-p">')
               .replace(/<em>/g, '<em class="md-em">')
               .replace(/<strong>/g, '<strong class="md-strong">')
               .replace(/“([^”]+)”/g, '<span class="md-dialogue">“$1”</span>')
               .replace(/「([^」]+)」/g, '<span class="md-dialogue">「$1」</span>');
  }
  return html;
};

const renderedDescription = computed(() => renderMarkdown(props.character?.description || ""));
const renderedScenario = computed(() => renderMarkdown(props.character?.scenario || ""));
const renderedFirstMes = computed(() => renderMarkdown(props.character?.first_mes || ""));
const renderedMesExample = computed(() => renderMarkdown(props.character?.mes_example || ""));
const renderedCreatorNotes = computed(() => renderMarkdown(props.character?.creator_notes || ""));
const renderedSystemPromptOverride = computed(() => renderMarkdown(props.character?.system_prompt_override || "", true));
const renderedPostHistoryInstructions = computed(() => renderMarkdown(props.character?.post_history_instructions || "", true));
</script>

<style scoped>
/* ===== 人设细节 (Profile Section) ===== */
.profile-details-section {
  display: flex;
  flex-direction: column;
  gap: 36rpx;
  padding: 8rpx 0 100rpx 0;
}

.section-card {
  background-color: #ffffff;
  border-radius: 24rpx;
  padding: 36rpx;
  border: 1px solid rgba(0, 0, 0, 0.03);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.02);
  display: flex;
  flex-direction: column;
  gap: 20rpx;
  transition: all 0.2s ease;
}

.section-card.is-collapsed {
  gap: 0;
  padding: 28rpx 36rpx;
}

.section-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.section-title {
  font-size: 26rpx;
  font-weight: 700;
  color: #8e8e93;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  flex: 1;
}

.expand-arrow {
  width: 32rpx;
  height: 32rpx;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.25s ease;
}

.expand-arrow::after {
  content: "";
  width: 12rpx;
  height: 12rpx;
  border-right: 3rpx solid #8e8e93;
  border-bottom: 3rpx solid #8e8e93;
  transform: rotate(45deg);
  transition: transform 0.2s ease;
}

.expand-arrow.is-expanded {
  transform: rotate(225deg);
  margin-top: 6rpx;
}

.section-body-wrapper {
  margin-top: 10rpx;
}

.section-body {
  font-size: 28rpx;
  color: #1c1c1e;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

.section-body.italic {
  font-style: italic;
  color: #3a3a3c;
}

.section-body :deep(.md-p) {
  margin: 0 0 12rpx 0;
}

.section-body :deep(.md-p:last-child) {
  margin-bottom: 0;
}

.section-body :deep(.md-em) {
  color: #8e8e93;
  font-style: italic;
}

.section-body :deep(.md-strong) {
  font-weight: 600;
  color: #000000;
}

.section-body :deep(.md-dialogue) {
  color: #1c1c1e;
  font-weight: 500;
}

.section-body.code-text {
  font-family: monospace;
  font-size: 24rpx;
  background-color: #f2f2f7;
  padding: 20rpx;
  border-radius: 14rpx;
  color: #48484a;
}

.section-body :deep(pre) {
  background-color: #f2f2f7;
  padding: 16rpx 20rpx;
  border-radius: 12rpx;
  font-family: monospace;
  font-size: 24rpx;
  color: #1c1c1e;
  word-break: break-all;
  white-space: pre-wrap;
  margin: 10rpx 0;
}

.section-body.dialogue-example :deep(.md-dialogue) {
  color: #007aff;
  font-weight: 600;
}
</style>
