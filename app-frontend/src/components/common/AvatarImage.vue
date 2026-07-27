<template>
  <image
    :src="displaySrc"
    :mode="mode"
    :lazy-load="lazyLoad"
    :fade-show="fadeShow"
    @error="useFallback"
  />
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { DEFAULT_AVATAR_URL } from "@/api/characters";

type ImageMode =
  | "scaleToFill"
  | "aspectFit"
  | "aspectFill"
  | "widthFix"
  | "heightFix"
  | "top"
  | "bottom"
  | "center"
  | "left"
  | "right"
  | "top left"
  | "top right"
  | "bottom left"
  | "bottom right";

const props = withDefaults(defineProps<{
  src?: string;
  mode?: ImageMode;
  lazyLoad?: boolean;
  fadeShow?: boolean;
}>(), {
  src: "",
  mode: "aspectFill",
  lazyLoad: true,
  fadeShow: true,
});

const displaySrc = ref(props.src || DEFAULT_AVATAR_URL);

watch(
  () => props.src,
  (source) => {
    displaySrc.value = source || DEFAULT_AVATAR_URL;
  },
);

const useFallback = () => {
  if (displaySrc.value !== DEFAULT_AVATAR_URL) {
    displaySrc.value = DEFAULT_AVATAR_URL;
  }
};
</script>
