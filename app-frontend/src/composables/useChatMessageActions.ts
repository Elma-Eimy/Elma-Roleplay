import { ref } from "vue";
import type { Ref } from "vue";
import { createSession } from "@/api/sessions";
import { useChatStore } from "@/store/chatStore";
import type { ChatMessage } from "@/store/chatStore";
import { usePersonaStore } from "@/store/personaStore";
import { useAudioPlayer } from "@/composables/useAudioPlayer";

export function useChatMessageActions(
  currentSessionId: Ref<number | null>,
  scrollToBottom: () => Promise<void>
) {
  const chatStore = useChatStore();
  const personaStore = usePersonaStore();
  const { playMessageTTS } = useAudioPlayer();
  const editingMessageId = ref<number | null>(null);
  const editMessageContent = ref("");

  const cancelEdit = () => {
    editingMessageId.value = null;
    editMessageContent.value = "";
  };

  const saveEdit = async () => {
    if (editingMessageId.value === null) return;
    await chatStore.editMessage(
      editingMessageId.value,
      editMessageContent.value
    );
    cancelEdit();
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
    uni.showModal({
      title: "删除消息",
      content: "确定要删除此消息吗？",
      confirmColor: "#D9655D",
      cancelColor: "#7C8983",
      success: async (modalResult) => {
        if (modalResult.confirm) {
          await chatStore.deleteMessageById(message.id);
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
    if (!message?.id) return;

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

    uni.showActionSheet({
      itemList,
      success: (result) => {
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
    });
  };

  return {
    editingMessageId,
    editMessageContent,
    onMessageLongPress,
    cancelEdit,
    saveEdit,
  };
}
