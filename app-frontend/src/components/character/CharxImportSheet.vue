<template>
  <view class="charx-overlay">
    <view class="charx-backdrop" @tap="close" />
    <view class="charx-sheet" role="dialog" aria-label="CHARX 角色包导入">
      <view class="charx-heading"><text class="charx-title">{{ characterId ? '从角色包补充图片' : '导入 CHARX 角色包' }}</text><button size="mini" :disabled="saving" @tap="close">关闭</button></view>
      <scroll-view scroll-y class="charx-scroll">
        <view class="charx-content">
          <text class="charx-hint">上传不超过 20 MB；最多 300 张静态图片、单图 8 MB。确认前不会保存到角色。</text>
          <text v-if="characterId" class="charx-hint">保留当前角色设定和头像；只有主动选为头像时才替换头像。</text>
          <button :disabled="busy || saving || recoveryNeeded" @tap="choose">{{ busy ? '正在读取…' : preview ? '重新选择角色包' : '选择 CHARX / ZIP 文件' }}</button>
          <view v-if="recoveryNeeded" class="charx-warnings"><text>上一次确认的结果尚未确定，修改选项已锁定。</text><button size="mini" :disabled="busy || saving" @tap="recover()">查询保存结果</button></view>
          <view v-if="error" class="charx-error"><text>{{ error }}</text><button v-if="preview" size="mini" :disabled="busy || saving || recoveryNeeded" @tap="loadPage(page)">重试预览</button></view>
          <template v-if="preview">
            <text class="charx-title">{{ preview.card.name }}</text>
            <view class="charx-warnings"><text v-for="(notice, index) in preview.warnings" :key="index">{{ notice }}</text></view>
            <view class="charx-warnings">
              <text>兼容性清单（导入成功不代表原平台效果完整还原）</text>
              <text v-for="(item, index) in preview.compatibility" :key="index">{{ { preserved: '保留', skipped: '跳过', unknown: '待确认' }[item.status] }} · {{ item.label }}{{ item.count === null ? '' : `：${item.count}` }}</text>
              <button v-if="preview.skipped_assets?.length" size="mini" @tap="showSkipped = !showSkipped">{{ showSkipped ? '收起' : '查看' }}跳过素材明细</button>
              <template v-if="showSkipped"><text v-for="(item, index) in preview.skipped_assets" :key="`skip-${index}`">{{ item.name }}：{{ item.reason }}</text></template>
            </view>
            <view v-if="!characterId" class="charx-field"><text>新角色名称</text><input v-model="name" :maxlength="50" :disabled="saving || recoveryNeeded" placeholder="输入角色名称" /></view>
            <view class="charx-description"><CharacterCardText :content="preview.card.description || '暂无角色描述'" /></view>
            <button size="mini" :disabled="saving" @tap="showOpenings = !showOpenings">{{ showOpenings ? '收起故事开场' : `查看 ${getCardGreetings(preview.card).length + 1} 个故事开场` }}</button>
            <CharacterGreetings v-if="showOpenings" v-model="greetingIndex" :first-mes="preview.card.first_mes" :alternates="getCardGreetings(preview.card)" :character-name="preview.card.name" />
            <text class="charx-hint">已读取 {{ preview.assets.length }} 张可用图片，已选 {{ selected.length }} 张加入立绘库。预览有效期 15 分钟。</text>
            <view class="charx-actions">
              <button size="mini" :disabled="busy || saving || recoveryNeeded" @tap="selected = preview.assets.map(asset => asset.index)">全选图片</button>
              <button size="mini" :disabled="busy || saving || recoveryNeeded" @tap="selected = []">清空选择</button>
              <button size="mini" :disabled="busy || saving || recoveryNeeded" @tap="avatar = null">{{ characterId ? '保留原头像' : '不设置头像' }}</button>
            </view>
            <view class="charx-field"><text>跳过内容相同的已有立绘</text><switch :checked="skipDuplicates" :disabled="saving || recoveryNeeded" @change="changeDuplicates" /></view>
            <text class="charx-hint">{{ characterId ? '本次仅追加素材，角色设定不变。' : '本次将创建新角色并保存上方设定。' }}选择 {{ selected.length }} 项立绘；{{ skipDuplicates ? '相同内容只保留一份立绘记录，已有素材也会跳过。' : '允许新增同内容立绘记录。' }}{{ avatar === null ? (characterId ? '保留原头像。' : '不设置头像。') : '使用指定图片作为头像。' }}</text>
            <text class="charx-hint">{{ avatar === null ? (characterId ? '将保留原头像' : '尚未选择头像') : '将使用下方标记的头像' }}</text>
            <view class="charx-grid">
              <view v-for="asset in visibleAssets" :key="asset.index" class="charx-asset" :class="{ chosen: selected.includes(asset.index) }">
                <image v-if="thumbnails[asset.index]" class="charx-thumbnail" :src="thumbnails[asset.index]" mode="aspectFit" />
                <view v-else class="charx-thumbnail charx-placeholder"><text>预览待加载</text></view>
                <text class="charx-name">{{ asset.name }}</text>
                <view class="charx-actions"><button size="mini" :disabled="busy || saving || recoveryNeeded" @tap="toggle(asset.index)">{{ selected.includes(asset.index) ? '已选立绘' : '加入立绘' }}</button><button size="mini" :disabled="busy || saving || recoveryNeeded" @tap="avatar = asset.index">{{ avatar === asset.index ? '当前头像' : '设为头像' }}</button></view>
              </view>
            </view>
            <view v-if="preview.assets.length" class="charx-pages"><button size="mini" :disabled="busy || saving || page === 0" @tap="loadPage(page - 1)">上一页</button><text>{{ page + 1 }} / {{ Math.ceil(preview.assets.length / 12) }}</text><button size="mini" :disabled="busy || saving || (page + 1) * 12 >= preview.assets.length" @tap="loadPage(page + 1)">下一页</button></view>
          </template>
        </view>
      </scroll-view>
      <view class="charx-footer"><button :disabled="!preview || busy || saving || (!characterId && !name.trim()) || (!!characterId && !selected.length && avatar === null)" @tap="save">{{ saving ? '正在保存…' : recoveryNeeded ? '重试原确认' : characterId ? '确认补充图片' : '确认创建角色' }}</button></view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { CharxImportResult } from "@/types/charx";
import { useCharxImport } from "@/composables/useCharxImport";
import CharacterCardText from "./CharacterCardText.vue";
import CharacterGreetings from "./CharacterGreetings.vue";
import { getCardGreetings } from "@/utils/characterCard";
const greetingIndex = ref<number | null>(null);
const showOpenings = ref(false);
const showSkipped = ref(false);
const props = defineProps<{ characterId?: number | null }>();
const emit = defineEmits<{ (event: "close"): void; (event: "imported", id: number, result: CharxImportResult): void }>();
const { preview, selected, avatar, name, thumbnails, page, busy, saving, error, skipDuplicates, recoveryNeeded, choose, loadPage, save, recover } = useCharxImport(
  () => props.characterId ?? null, result => emit("imported", result.character_id, result),
);
const visibleAssets = computed(() => preview.value?.assets.slice(page.value * 12, (page.value + 1) * 12) || []);
watch(() => preview.value?.token, () => { greetingIndex.value = null; showOpenings.value = false; showSkipped.value = false; });
function changeDuplicates(event: Event) { skipDuplicates.value = (event as unknown as { detail: { value: boolean } }).detail.value; }
function toggle(index: number) { selected.value = selected.value.includes(index) ? selected.value.filter(id => id !== index) : [...selected.value, index]; }
function close() { if (!saving.value) emit("close"); }
</script>

<style scoped>
.charx-overlay { position: fixed; inset: 0; z-index: 370; display: flex; align-items: center; justify-content: center; padding: 20rpx; box-sizing: border-box; }
.charx-backdrop { position: absolute; inset: 0; background: rgba(20, 36, 30, .5); }
.charx-sheet { position: relative; display: flex; flex-direction: column; width: 100%; max-width: 760px; height: 90vh; background: var(--app-color-surface, #fff); color: var(--app-color-text-primary, #26332e); border-radius: 24rpx; overflow: hidden; }
.charx-heading, .charx-pages { display: flex; align-items: center; justify-content: space-between; gap: 16rpx; padding: 24rpx; }
.charx-title { display: block; font-size: 30rpx; font-weight: 600; }
.charx-scroll { flex: 1; min-height: 0; height: 0; }
.charx-content { display: flex; flex-direction: column; gap: 20rpx; padding: 24rpx; }
.charx-hint, .charx-warnings, .charx-name { font-size: 24rpx; line-height: 1.7; overflow-wrap: anywhere; }
.charx-hint { color: var(--app-color-text-secondary, #7c8983); }
.charx-warnings { padding: 18rpx; border-radius: 14rpx; background: var(--app-color-surface-soft, #f3f6f3); }
.charx-warnings text { display: block; margin-bottom: 10rpx; }
.charx-error { font-size: 24rpx; color: var(--app-color-danger, #b94646); overflow-wrap: anywhere; }
.charx-field input { height: 84rpx; box-sizing: border-box; border: 1px solid var(--app-color-border, #e1e8e2); border-radius: 12rpx; padding: 16rpx; margin-top: 12rpx; }
.charx-description { max-height: 240rpx; overflow: auto; font-size: 24rpx; }
.charx-actions { display: flex; gap: 10rpx; flex-wrap: wrap; }
.charx-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16rpx; }
.charx-asset { display: flex; flex-direction: column; gap: 12rpx; padding: 12rpx; border: 2rpx solid var(--app-color-border, #e1e8e2); border-radius: 14rpx; min-width: 0; }
.charx-asset.chosen { border-color: var(--app-color-primary, #4f8e7c); }
.charx-thumbnail { width: 100%; height: 230rpx; }
.charx-placeholder { display: flex; align-items: center; justify-content: center; font-size: 22rpx; }
.charx-footer { padding: 20rpx 24rpx calc(20rpx + env(safe-area-inset-bottom)); border-top: 1px solid var(--app-color-border, #e1e8e2); }
.charx-sheet button { margin: 0; font-size: 24rpx; }
</style>
