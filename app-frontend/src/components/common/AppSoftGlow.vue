<template>
  <view class="app-soft-glow" aria-hidden="true">
    <view class="glow glow-primary"></view>
    <view class="glow glow-secondary"></view>
    <view class="glow glow-warm"></view>
  </view>
</template>

<style scoped>
.app-soft-glow {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
}

.glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(22px);
  opacity: 0.52;
}

.glow-primary {
  top: -120rpx;
  right: -180rpx;
  width: 520rpx;
  height: 420rpx;
  background: radial-gradient(
    circle,
    var(--app-color-primary-soft, rgba(112, 174, 155, 0.14)) 0%,
    rgba(112, 174, 155, 0) 70%
  );
}

.glow-secondary {
  top: 280rpx;
  left: -240rpx;
  width: 480rpx;
  height: 480rpx;
  background: radial-gradient(
    circle,
    rgba(139, 184, 220, 0.13) 0%,
    rgba(139, 184, 220, 0) 72%
  );
}

.glow-warm {
  right: -180rpx;
  bottom: 120rpx;
  width: 400rpx;
  height: 400rpx;
  background: radial-gradient(
    circle,
    rgba(241, 201, 141, 0.12) 0%,
    rgba(241, 201, 141, 0) 72%
  );
}
</style>
