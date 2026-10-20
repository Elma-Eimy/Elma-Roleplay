<template>
  <view :propVal="request" :change:propVal="stream.onStreamRequestChange" class="stream-bridge" />
</template>

<script lang="ts">
import { defineComponent, type PropType } from "vue";
import type { ActiveStreamRequest, StreamPayload } from "../../types/chatStream";

export default defineComponent({
  props: {
    request: { type: Object as PropType<ActiveStreamRequest | null>, default: null },
  },
  emits: ["message"],
  methods: {
    onStreamEvent(payload: StreamPayload) {
      this.$emit("message", { detail: payload });
    },
  },
});
</script>

<script module="stream" lang="renderjs">
import { createRenderjsStreamBridge } from "../../api/transports/appStream";
export default createRenderjsStreamBridge();
</script>

<style scoped>
.stream-bridge { position: absolute; width: 0; height: 0; overflow: hidden; }
</style>
