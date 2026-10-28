import { ref, watch, onScopeDispose } from "vue";
import type { Ref } from "vue";
import { createSession } from "@/api/sessions";
import { useChatSettingsStore } from "@/store/chatSettingsStore";
import { useChatStore } from "@/store/chatStore";
import type { ChatMessage } from "@/store/chatStore";
import { usePersonaStore } from "@/store/personaStore";
import { useAudioPlayer } from "@/composables/useAudioPlayer";
import { getBaseUrl } from "@/api/config";
import { onServerChange } from "@/utils/connectionEvents";

export function useChatMessageActions(
  currentSessionId: Ref<number | null>,
  scrollToBottom: () => Promise<void>
) {
  const chatStore = useChatStore();
  const personaStore = usePersonaStore();
  const { playMessageTTS } = useAudioPlayer();
  const editingMessageId = ref<number | null>(null);
  const editMessageContent = ref("");
  const editError = ref("");
  const isSavingEdit = ref(false);
  let editVersion = 0;
  let isMessageActionSheetOpen = false;

  const cancelEdit = () => {
    editVersion++;
    editingMessageId.value = null;
    editMessageContent.value = "";
    editError.value = "";
    isSavingEdit.value = false;
  };

  const saveEdit = async () => {
    if (editingMessageId.value === null || isSavingEdit.value) return;
    const id = editingMessageId.value, content = editMessageContent.value;
    const version = editVersion, sessionId = currentSessionId.value, endpoint = getBaseUrl();
    const current = () => version === editVersion && editingMessageId.value === id &&
      sessionId === currentSessionId.value && endpoint === getBaseUrl();
    isSavingEdit.value = true;
    editError.value = "";
    try {
      const result = await chatStore.editMessage(id, content);
      if (!current()) return;
      if (result.status === "success" && editMessageContent.value === content) cancelEdit();
      else if (result.status === "error") editError.value = result.message;
    } finally {
      if (current()) isSavingEdit.value = false;
    }
  };

  const createBranchFromMessage = (message: ChatMessage) => {
    uni.showModal({
      title: "创建分支会话",
      content: "确定要在此消息节点截断并开启一条新的分支故事会话吗？",
      confirmColor: "#70AE9B",
      cancelColor: "#7C8983",
      success: async (modalResult) => {
        const sessionId = currentSessionId.value;
        const character = personaStore.activeCharacter;
        if (!modalResult.confirm || sessionId === null || !character) return;

        try {
          uni.showLoading({ title: "正在创建分支..." });
          const branch = await createSession({
            character_id: character.id,
            parent_session_id: sessionId,
            title: `${character.name} (分支故事)`,
            start_message_id: message.id,
          });
          useChatSettingsStore().inheritSession(sessionId, branch.session_id);
          uni.hideLoading();
          uni.showToast({ title: "分支创建成功", icon: "success" });
          setTimeout(() => {
            uni.redirectTo({
              url: `/pages/chat/chat?sessionId=${branch.session_id}`,
            });
          }, 1000);
        } catch (error) {
          uni.hideLoading();
          console.error(error);
          uni.showToast({ title: "创建分支失败", icon: "none" });
        }
      },
    });
  };

  const deleteMessage = (message: ChatMessage) => {
    const version = editVersion;
    const sessionId = currentSessionId.value, endpoint = getBaseUrl();
    uni.showModal({
      title: "删除消息",
      content: "确定要删除此消息吗？",
      confirmColor: "#D9655D",
      cancelColor: "#7C8983",
      success: async (modalResult) => {
        if (modalResult.confirm && version === editVersion && sessionId === currentSessionId.value && endpoint === getBaseUrl()) {
          const result = await chatStore.deleteMessageById(message.id);
          if (result.status === "error") uni.showToast({ title: result.message, icon: "none" });
        }
      },
    });
  };

  const regenerateLatestReply = async () => {
    const sessionId = currentSessionId.value;
    if (sessionId === null) return;

    try {
      await chatStore.regenerateChatMessage(sessionId);
      await scrollToBottom();
    } catch (error) {
      console.error("Failed to regenerate response", error);
    }
  };

  const onMessageLongPress = (message: ChatMessage) => {
    if (!message?.id || isMessageActionSheetOpen) return;
    const version = editVersion, sessionId = currentSessionId.value, endpoint = getBaseUrl();

    const itemList = ["复制内容"];
    if (message.role === "assistant") {
      itemList.push("朗读消息");
    }
    itemList.push("编辑消息", "创建分支（多宇宙）");

    const isLatestAssistant =
      message.id === chatStore.lastAssistantMessage?.id;
    if (message.role === "assistant" && isLatestAssistant) {
      itemList.push("重新生成回复");
    }
    itemList.push("删除此消息");

    isMessageActionSheetOpen = true;
    try {
      uni.showActionSheet({
        itemList,
        success: (result) => {
          if (version !== editVersion || sessionId !== currentSessionId.value || endpoint !== getBaseUrl()) return;
          const action = itemList[result.tapIndex];
          if (action === "复制内容") {
            uni.setClipboardData({
              data: message.content,
              success: () =>
                uni.showToast({ title: "复制成功", icon: "none" }),
            });
          } else if (action === "朗读消息") {
            void playMessageTTS(message);
          } else if (action === "编辑消息") {
            cancelEdit();
            editingMessageId.value = message.id;
            editMessageContent.value = message.content;
          } else if (action === "创建分支（多宇宙）") {
            createBranchFromMessage(message);
          } else if (action === "删除此消息") {
            deleteMessage(message);
          } else if (action === "重新生成回复") {
            void regenerateLatestReply();
          }
        },
        complete: () => {
          isMessageActionSheetOpen = false;
        },
      });
    } catch (error) {
      isMessageActionSheetOpen = false;
      throw error;
    }
  };

  watch(currentSessionId, cancelEdit, { flush: "sync" });
  const unsubscribe = onServerChange(cancelEdit);
  onScopeDispose(() => { unsubscribe(); cancelEdit(); });

  return {
    editingMessageId,
    editMessageContent,
    editError,
    isSavingEdit,
    onMessageLongPress,
    cancelEdit,
    saveEdit,
  };
}
