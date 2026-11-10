<template>
  <view class="chat-bg" :class="{ 'mode-clean': !immersive, 'is-immersive': immersive }">
    <image v-if="immersive && wide" class="chat-scene-wash" :src="src" mode="aspectFill" aria-hidden="true" />
    <image v-if="immersive" :key="src" class="chat-scene-image" :src="src"
      :mode="wide ? 'aspectFit' : 'aspectFill'" :data-source="src" @error="emit('unavailable', $event)" />
  </view>
</template>

<script setup lang="ts">
defineProps<{ src: string; immersive: boolean; wide: boolean }>();
const emit = defineEmits<{ (event: 'unavailable', error: Event): void }>();
</script>

<style scoped>
.chat-bg { position: absolute; inset: 0; pointer-events: none; z-index: 0; }
.mode-clean { display: none; }
.chat-scene-image { position: absolute; inset: 0; width: 100%; height: 100%; }
.is-immersive { background: #24342c; }
.chat-scene-wash { position: absolute; inset: -24px; width: calc(100% + 48px); height: calc(100% + 48px); filter: blur(20px); opacity: .32; }
.is-immersive::after { content: ''; position: absolute; inset: 0; background: linear-gradient(180deg, rgba(10,18,18,.40) 0%, transparent 22%, transparent 72%, rgba(10,18,18,.40) 100%); }
</style>
