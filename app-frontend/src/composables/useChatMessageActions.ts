import { ref, computed, watch, onScopeDispose } from "vue";
import type { Ref } from "vue";
import { createSession } from "@/api/sessions";
import { useChatSettingsStore } from "@/store/chatSettingsStore";
import { useChatStore } from "@/store/chatStore";
import type { ChatMessage } from "@/store/chatStore";
import { usePersonaStore } from "@/store/personaStore";
import { useAudioPlayer } from "@/composables/useAudioPlayer";
import { getBaseUrl } from "@/api/config";
import { onServerChange } from "@/utils/connectionEvents";
import type { ActionSheetItem } from "@/components/common/AppActionSheet.vue";

export type MessageActionKey =
  | "copy"
  | "tts"
  | "edit"
  | "branch"
  | "regenerate"
  | "delete";

interface PendingActionContext {
  version: number;
  sessionId: number | null;
  endpoint: string;
}

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
  const actionSheetMessage = ref<ChatMessage | null>(null);
  let editVersion = 0;
  let isMessageActionSheetOpen = false;
  let actionContext: PendingActionContext | null = null;

  const isContextValid = (ctx: PendingActionContext | null): boolean =>
    Boolean(
      ctx &&
        ctx.version === editVersion &&
        ctx.sessionId === currentSessionId.value &&
        ctx.endpoint === getBaseUrl()
    );

  const closeActionSheet = () => {
    actionSheetMessage.value = null;
    actionContext = null;
    isMessageActionSheetOpen = false;
  };

  const cancelEdit = () => {
    editVersion++;
    closeActionSheet();
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

  const copyMessageContent = (message: ChatMessage) => {
    if (!message?.content) return;
    uni.setClipboardData({
      data: message.content,
      success: () => uni.showToast({ title: "复制成功", icon: "none" }),
    });
  };

  const buildItemsForMessage = (message: ChatMessage): ActionSheetItem[] => {
    const items: ActionSheetItem[] = [
      { key: "copy", label: "复制内容", icon: "/static/icons/char_list.svg" },
    ];
    if (message.role === "assistant") {
      items.push({ key: "tts", label: "朗读消息", icon: "/static/icons/tts_play.svg" });
    }
    items.push(
      { key: "edit", label: "编辑消息", icon: "/static/icons/char_pencil.svg" },
      { key: "branch", label: "创建分支（多宇宙）", icon: "/static/icons/char_branch.svg" }
    );
    const isLatestAssistant = message.id === chatStore.lastAssistantMessage?.id;
    if (message.role === "assistant" && isLatestAssistant && !chatStore.isLoading) {
      items.push({ key: "regenerate", label: "重新生成回复", icon: "/static/icons/drawer_sync.svg" });
    }
    items.push({ key: "delete", label: "删除此消息", icon: "/static/icons/drawer_trash.svg", danger: true });
    return items;
  };

  const actionSheetItems = computed<ActionSheetItem[]>(() =>
    actionSheetMessage.value ? buildItemsForMessage(actionSheetMessage.value) : []
  );

  const runAction = (action: MessageActionKey | string, message: ChatMessage) => {
    if (action === "copy" || action === "复制内容") {
      copyMessageContent(message);
    } else if (action === "tts" || action === "朗读消息") {
      void playMessageTTS(message);
    } else if (action === "edit" || action === "编辑消息") {
      cancelEdit();
      editingMessageId.value = message.id;
      editMessageContent.value = message.content;
    } else if (action === "branch" || action === "创建分支（多宇宙）") {
      createBranchFromMessage(message);
    } else if (action === "delete" || action === "删除此消息") {
      deleteMessage(message);
    } else if (action === "regenerate" || action === "重新生成回复") {
      void regenerateLatestReply();
    }
  };

  const selectActionSheetItem = (key: string) => {
    const message = actionSheetMessage.value;
    const ctx = actionContext;
    closeActionSheet();
    if (!message || !isContextValid(ctx)) return;
    runAction(key, message);
  };

  const onMessageLongPress = (message: ChatMessage) => {
    if (!message?.id || isMessageActionSheetOpen) return;
    const ctx: PendingActionContext = {
      version: editVersion,
      sessionId: currentSessionId.value,
      endpoint: getBaseUrl(),
    };
    const items = buildItemsForMessage(message);
    const itemList = items.map((item) => item.label);

    isMessageActionSheetOpen = true;
    actionContext = ctx;
    actionSheetMessage.value = message;

    // 仅在 Node 离线测试（非浏览器/小程序/App 宿主）且注入了 showActionSheet 替身时保留回调路径。
    const host = globalThis as Record<string, unknown>;
    if (
      !("window" in host) &&
      !("wx" in host) &&
      !("plus" in host) &&
      typeof uni !== "undefined" &&
      typeof uni.showActionSheet === "function"
    ) {
      try {
        uni.showActionSheet({
          itemList,
          success: (result) => {
            if (!isContextValid(ctx)) return;
            closeActionSheet();
            const action = itemList[result.tapIndex];
            if (action) runAction(action, message);
          },
          complete: () => {
            isMessageActionSheetOpen = false;
          },
        });
      } catch (error) {
        closeActionSheet();
        throw error;
      }
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
    actionSheetMessage,
    actionSheetItems,
    onMessageLongPress,
    selectActionSheetItem,
    closeActionSheet,
    copyMessageContent,
    regenerateLatestReply,
    cancelEdit,
    saveEdit,
  };
}
