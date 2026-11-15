import type { GroupSessionDetail } from "../types/groupSessions";
import type { SessionSummary } from "../types/sessions";

export interface HomeSingleSession extends SessionSummary {
  characterName: string;
  characterAvatar: string;
  lastMessage: string;
  lastMessageTime: string;
  unread: boolean;
}

export interface HomeStoryAvatar {
  name: string;
  avatarPath: string;
}

interface HomeStoryBase {
  key: string;
  id: number;
  title: string;
  subtitle: string;
  preview: string;
  lastMessageTime: string;
  avatars: HomeStoryAvatar[];
}

export interface HomeSingleStoryItem extends HomeStoryBase {
  kind: "single";
  singleSession: HomeSingleSession;
}

export interface HomeGroupStoryItem extends HomeStoryBase {
  kind: "group";
  groupSession: GroupSessionDetail;
}

export type HomeStoryItem = HomeSingleStoryItem | HomeGroupStoryItem;

function normalizeText(value: string | null | undefined): string {
  return value ? value.replace(/\s+/g, " ").trim() : "";
}

function timestampMs(value: string | null | undefined): number {
  if (!value) return 0;
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? 0 : ms;
}

export function decorateSingleStory(session: HomeSingleSession): HomeSingleStoryItem {
  const characterName = session.characterName || "角色";
  return {
    key: `single-${session.id}`,
    kind: "single",
    id: session.id,
    title: session.title?.trim() || `${characterName}的故事`,
    subtitle: characterName,
    preview: normalizeText(session.lastMessage) || "故事还没有写下第一句话…",
    lastMessageTime: session.lastMessageTime || session.updated_at || session.created_at,
    avatars: [{ name: characterName, avatarPath: session.characterAvatar || "" }],
    singleSession: session,
  };
}

export function resolveGroupPreview(group: GroupSessionDetail): string {
  const lastContent = normalizeText(group.last_message?.content);
  if (lastContent) {
    const speaker = group.last_message?.speaker_name
      || (group.last_message?.role === "user" ? (group.user_nickname?.trim() || "我") : "");
    return speaker ? `${speaker}: ${lastContent}` : lastContent;
  }
  const setting = normalizeText(group.shared_setting);
  if (setting) return setting;
  const greetingMember = group.members.find(member => normalizeText(member.greeting_content));
  if (greetingMember) {
    const greeting = normalizeText(greetingMember.greeting_content);
    return greetingMember.character?.name ? `${greetingMember.character.name}: ${greeting}` : greeting;
  }
  return "故事还没有写下第一句话…";
}

export function decorateGroupStory(group: GroupSessionDetail): HomeGroupStoryItem {
  const members = group.members ?? [];
  const names = members.map(member => member.character?.name).filter(Boolean);
  return {
    key: `group-${group.session_id}`,
    kind: "group",
    id: group.session_id,
    title: group.title?.trim() || "群聊故事",
    subtitle: names.join(" · ") || "群聊",
    preview: resolveGroupPreview(group),
    lastMessageTime: group.last_message?.created_at || group.updated_at || group.created_at,
    avatars: members.slice(0, 3).map(member => ({
      name: member.character?.name || "角色",
      avatarPath: member.character?.avatar_path || "",
    })),
    groupSession: group,
  };
}

export function mergeHomeStories(
  singles: HomeSingleSession[],
  groups: GroupSessionDetail[]
): HomeStoryItem[] {
  const items: HomeStoryItem[] = [
    ...singles.map(decorateSingleStory),
    ...groups.map(decorateGroupStory),
  ];
  return items.sort((a, b) => {
    const diff = timestampMs(b.lastMessageTime) - timestampMs(a.lastMessageTime);
    if (diff !== 0) return diff;
    return b.id - a.id;
  });
}
