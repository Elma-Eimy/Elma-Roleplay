import { ref } from "vue";
import { getBaseUrl, getHeaders } from "@/api/config";
import { generateTTS } from "@/api/chat";

// 全局单例状态，确保整个应用生命周期中只有一个播放实例与播放状态
const activeAudioMessageId = ref<number | null>(null);
let innerAudioContext: any = null;
let activeDownloadTask: UniApp.DownloadTask | null = null;

export function useAudioPlayer() {
  function initAudioContext() {
    if (!innerAudioContext) {
      // #ifdef APP-PLUS || H5 || MP-WEIXIN
      innerAudioContext = uni.createInnerAudioContext();
      // #endif
      if (innerAudioContext) {
        innerAudioContext.onPlay(() => {
          console.log("Audio playing...");
        });
        innerAudioContext.onEnded(() => {
          console.log("Audio finished.");
          activeAudioMessageId.value = null;
        });
        innerAudioContext.onError((err: any) => {
          console.error("Audio error:", err);
          activeAudioMessageId.value = null;
          uni.showToast({ title: "语音播放失败", icon: "none" });
        });
        innerAudioContext.onStop(() => {
          console.log("Audio stopped.");
          activeAudioMessageId.value = null;
        });
      }
    }
  }

  function stopMessageTTS() {
    if (activeDownloadTask) {
      activeDownloadTask.abort();
      activeDownloadTask = null;
    }
    if (innerAudioContext && activeAudioMessageId.value !== null) {
      innerAudioContext.stop();
      activeAudioMessageId.value = null;
    }
  }

  async function playMessageTTS(message: any) {
    const messageId = message.id;
    let audioUrl = message.audio_path;

    initAudioContext();
    if (!innerAudioContext) {
      uni.showToast({ title: "您的平台不支持音频播放", icon: "none" });
      return;
    }

    // 如果当前正在播放的就是这条消息，点击则是停止播放
    if (activeAudioMessageId.value === messageId) {
      stopMessageTTS();
      return;
    }

    // 如果正在播放其他消息，先停止
    if (activeAudioMessageId.value !== null) {
      innerAudioContext.stop();
    }

    // 若音频文件路径不存在，则调用后端接口进行实时语音合成
    if (!audioUrl) {
      uni.showLoading({ title: "正在合成语音..." });
      try {
        const res = await generateTTS(messageId, message.content);
        audioUrl = res.audio_url;
        message.audio_path = audioUrl; // 响应式更新消息对象的 audio_path
        uni.hideLoading();
      } catch (e: any) {
        uni.hideLoading();
        uni.showToast({ title: e.message || "语音合成失败", icon: "none" });
        return;
      }
    }

    if (audioUrl) {
      const baseUrl = getBaseUrl().replace(/\/+$/, "");
      const isAbsoluteUrl = /^https?:\/\//i.test(audioUrl);
      const fullUrl = isAbsoluteUrl
        ? audioUrl
        : `${baseUrl}${audioUrl.startsWith("/") ? "" : "/"}${audioUrl}`;
      const requiresApiKey =
        !isAbsoluteUrl || fullUrl.startsWith(`${baseUrl}/`);
      activeAudioMessageId.value = messageId;

      // 先通过可携带认证头的下载请求获取临时文件，避免把 API Key 放入 URL。
      // 当前后端的 /audio/{filename} 必须使用 X-API-Key 请求头认证。
      activeDownloadTask = uni.downloadFile({
        url: encodeURI(fullUrl),
        header: requiresApiKey ? getHeaders() : {},
        success: (res) => {
          activeDownloadTask = null;
          if (res.statusCode === 200) {
            // 只有当当前活跃消息仍然是该条消息时才播放（防止下载期间切换或停止了播放）
            if (activeAudioMessageId.value === messageId) {
              innerAudioContext.src = res.tempFilePath;
              innerAudioContext.play();
            }
          } else {
            console.error("Audio download status error:", res.statusCode);
            uni.showToast({ title: "音频下载失败", icon: "none" });
            if (activeAudioMessageId.value === messageId) {
              activeAudioMessageId.value = null;
            }
          }
        },
        fail: (err) => {
          activeDownloadTask = null;
          if (activeAudioMessageId.value !== messageId) return;
          console.error("Audio download failed:", err);
          uni.showToast({ title: "音频下载失败", icon: "none" });
          activeAudioMessageId.value = null;
        }
      });
    } else {
      uni.showToast({ title: "未获取到有效的语音文件", icon: "none" });
    }
  }

  return {
    activeAudioMessageId,
    playMessageTTS,
    stopMessageTTS,
  };
}
