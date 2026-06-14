<template>
  <view class="profile-details-section">
    <!-- 角色背景描述卡片 -->
    <view class="section-card">
      <text class="section-title">人设背景描述</text>
      <scroll-view scroll-y class="section-scroll-container">
        <rich-text class="section-body" :nodes="renderedDescription" />
      </scroll-view>
    </view>

    <view class="section-card" v-if="character.scenario">
      <text class="section-title">所处场景环境</text>
      <scroll-view scroll-y class="section-scroll-container">
        <rich-text class="section-body" :nodes="renderedScenario" />
      </scroll-view>
    </view>

    <view class="section-card" v-if="character.first_mes">
      <text class="section-title">开场白预设</text>
      <scroll-view scroll-y class="section-scroll-container">
        <rich-text class="section-body italic" :nodes="renderedFirstMes" />
      </scroll-view>
    </view>

    <view class="section-card" v-if="character.mes_example">
      <text class="section-title">对话句式示例</text>
      <scroll-view scroll-y class="section-scroll-container">
        <rich-text class="section-body dialogue-example" :nodes="renderedMesExample" />
      </scroll-view>
    </view>

    <view class="section-card" v-if="character.creator_notes">
      <text class="section-title">创作者备忘录</text>
      <scroll-view scroll-y class="section-scroll-container">
        <rich-text class="section-body" :nodes="renderedCreatorNotes" />
      </scroll-view>
    </view>

    <view class="section-card" v-if="character.system_prompt_override">
      <text class="section-title">系统设定覆盖 (System Prompt Override)</text>
      <scroll-view scroll-y class="section-scroll-container">
        <rich-text class="section-body code-text" :nodes="renderedSystemPromptOverride" />
      </scroll-view>
    </view>

    <view class="section-card" v-if="character.post_history_instructions">
      <text class="section-title">历史末端注入指令 (Post History Instructions)</text>
      <scroll-view scroll-y class="section-scroll-container">
        <rich-text class="section-body code-text" :nodes="renderedPostHistoryInstructions" />
      </scroll-view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { CharacterDetail } from "@/api/characters";
import { usePersonaStore } from "@/store/personaStore";
import MarkdownIt from "markdown-it";

const props = defineProps<{
  character: CharacterDetail;
}>();

const personaStore = usePersonaStore();

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
}

.section-title {
  font-size: 26rpx;
  font-weight: 700;
  color: #8e8e93;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.section-scroll-container {
  max-height: 400rpx;
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
