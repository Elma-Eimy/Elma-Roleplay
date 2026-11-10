import { computed, onScopeDispose, ref } from "vue";
import { getBaseUrl, USE_MOCK } from "@/api/config";
import { getCharacters, getCharacter } from "@/api/characters";
import { greetingOptions, getCardGreetings } from "@/utils/characterCard";
import type { GreetingOption } from "@/utils/characterCard";
import { getSessions } from "@/api/sessions";
import { createGroupSession, deleteGroupSession, getGroupSession, getGroupSessions } from "@/api/groupSessions";
import { onServerChange } from "@/utils/connectionEvents";
import type { CreateGroupSessionParams, GroupCharacterOption, GroupSessionDetail, GroupGenerationOptions } from "@/types/groupSessions";
import { useGroupRoundFlow } from "@/composables/useGroupRoundFlow";
import { useGroupPortraits } from "@/composables/useGroupPortraits";
import type { SessionSummary } from "@/types/sessions";

function message(cause: unknown): string {
  const raw = cause instanceof Error ? cause.message : String(cause);
  const payload = raw.match(/\{.*\}$/s);
  if (payload) {
    try {
      const detail = JSON.parse(payload[0]).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) return "填写内容不符合要求，请检查成员来源和文本长度。";
    } catch {}
  }
  return raw;
}

function usePageScope(reset: (reason: "hide" | "server" | "dispose") => void) {
  let version = 0;
  let active = false;
  let disposed = false;
  const unsubscribe = onServerChange(() => { version++; reset("server"); });
  onScopeDispose(() => {
    disposed = true;
    active = false;
    version++;
    unsubscribe();
    reset("dispose");
  });
  return {
    activate() { if (disposed || active) return false; active = true; version++; return true; },
    invalidate() { version++; },
    deactivate() { active = false; version++; reset("hide"); },
    active: () => active && !disposed,
    capture() {
      const token = version;
      const server = getBaseUrl();
      return () => active && !disposed && version === token && getBaseUrl() === server;
    },
  };
}

export function useGroupSessionList() {
  const groups = ref<GroupSessionDetail[]>([]);
  const loading = ref(false);
  const error = ref("");
  const total = ref(0);
  const hasMore = ref(false);
  let requestVersion = 0;
  let nextOffset = 0;
  const scope = usePageScope(reason => {
    requestVersion++;
    loading.value = false;
    if (reason === "server" || reason === "dispose") {
      groups.value = [];
      total.value = 0;
      nextOffset = 0;
      hasMore.value = false;
      error.value = "";
      if (scope.active()) void load();
    }
  });
  async function load(more = false) {
    if (!scope.active() || loading.value || (more && !hasMore.value)) return;
    const current = scope.capture();
    const token = ++requestVersion;
    const valid = () => current() && token === requestVersion;
    loading.value = true;
    error.value = "";
    try {
      const page = await getGroupSessions(20, more ? nextOffset : 0);
      if (!valid()) return;
      const items = more ? [...groups.value, ...page.sessions] : page.sessions;
      groups.value = items.filter((group, index) => items.findIndex(item => item.session_id === group.session_id) === index);
      total.value = page.total;
      nextOffset = page.offset + page.sessions.length;
      hasMore.value = page.has_more && page.sessions.length > 0;
    } catch (cause) { if (valid()) error.value = message(cause); }
    finally { if (valid()) loading.value = false; }
  }
  return { groups, loading, error, total, hasMore, load,
    show() { if (scope.activate()) void load(); }, hide: scope.deactivate };
}

interface DraftMember {
  character: GroupCharacterOption;
  mode: "card" | "single_snapshot";
  sourceSessionId: number | null;
  sources: SessionSummary[];
  sourceOffset: number;
  hasMoreSources: boolean;
  loadingSources: boolean;
  pendingSourcePage: "first" | "more" | null;
  sourceError: string;
  sourceVersion: number;
  greetings: GreetingOption[];
  greetingIndex: number;
  greetingContent: string;
  greetingLoaded: boolean;
  greetingError: string;
  loadingGreeting: boolean;
  greetingVersion: number;
}

export function useGroupSessionCreate(onCreated: (group: GroupSessionDetail) => void) {
  const title = ref("");
  const nickname = ref("用户");
  const sharedSetting = ref("");
  const characters = ref<GroupCharacterOption[]>([]);
  const members = ref<DraftMember[]>([]);
  const loadingCharacters = ref(false);
  const hasMoreCharacters = ref(false);
  const characterError = ref("");
  const submitting = ref(false);
  const error = ref("");
  const uncertain = ref(false);
  const created = ref<GroupSessionDetail | null>(null);
  const supportsSnapshots = !USE_MOCK;
  let characterOffset = 0;
  let characterVersion = 0;
  const scope = usePageScope(reason => {
    characterVersion++;
    loadingCharacters.value = false;
    if (submitting.value && reason !== "server") {
      uncertain.value = true;
      error.value = "创建结果待确认，请先到群聊列表查看，避免重复创建。";
    }
    submitting.value = false;
    for (const member of members.value) {
      member.sourceVersion++; member.loadingSources = false;
      member.greetingVersion++; member.loadingGreeting = false;
    }
    if (reason === "server" || reason === "dispose") {
      title.value = ""; nickname.value = "用户"; sharedSetting.value = "";
      characters.value = []; members.value = []; characterOffset = 0;
      hasMoreCharacters.value = false; characterError.value = "";
      uncertain.value = false; created.value = null; error.value = "";
      if (scope.active()) void loadCharacters();
    }
  });
  const locked = computed(() => submitting.value || uncertain.value || !!created.value);
  const validation = computed(() => {
    if (!title.value.trim() || title.value.trim().length > 50) return "请填写 1–50 字的群聊标题。";
    if (!nickname.value.trim() || nickname.value.trim().length > 50) return "请填写 1–50 字的用户昵称。";
    if (sharedSetting.value.length > 20000) return "共同设定最多 20000 字。";
    if (members.value.length < 2 || members.value.length > 3) return "请选择 2–3 名角色。";
    if (members.value.some(member => member.mode === "single_snapshot" && !member.sourceSessionId)) return "请为导入成员选择来源单聊。";
    if (members.value.some(member => member.mode === "card" && !member.greetingLoaded)) return "请先完成原卡开场读取，可在失败后重试。";
    if (members.value.some(member => member.mode === "card" && member.greetingContent.length > 20000)) return "每名成员的开场最多 20000 字。";
    return "";
  });
  async function loadCharacters(more = false) {
    if (!scope.active() || loadingCharacters.value || (more && !hasMoreCharacters.value)) return;
    const current = scope.capture();
    const token = ++characterVersion;
    const valid = () => current() && token === characterVersion;
    loadingCharacters.value = true;
    characterError.value = "";
    try {
      const offset = more ? characterOffset : 0;
      const page = await getCharacters(30, offset);
      if (!valid()) return;
      characters.value = more ? [...characters.value, ...page.characters] : page.characters;
      characterOffset = offset + page.characters.length;
      hasMoreCharacters.value = page.characters.length === 30;
    } catch (cause) { if (valid()) characterError.value = message(cause); }
    finally { if (valid()) loadingCharacters.value = false; }
  }
  function toggleCharacter(character: GroupCharacterOption) {
    if (locked.value) return;
    const index = members.value.findIndex(member => member.character.id === character.id);
    if (index >= 0) members.value.splice(index, 1);
    else if (members.value.length < 3) {
      members.value.push({ character, mode: "card", sourceSessionId: null,
        sources: [], sourceOffset: 0, hasMoreSources: false, loadingSources: false, pendingSourcePage: null, sourceError: "", sourceVersion: 0,
        greetings: [], greetingIndex: 0, greetingContent: "", greetingLoaded: false, greetingError: "", loadingGreeting: false, greetingVersion: 0 });
      void loadGreetings(members.value[members.value.length - 1]);
    }
    else error.value = "最多选择 3 名角色，请先移除一名成员。";
  }
  async function loadGreetings(member: DraftMember) {
    if (!scope.active() || locked.value || member.mode !== "card" || member.loadingGreeting || !members.value.includes(member)) return;
    const current = scope.capture();
    const token = ++member.greetingVersion;
    const valid = () => current() && token === member.greetingVersion && members.value.includes(member) && member.mode === "card";
    member.loadingGreeting = true; member.greetingError = "";
    try {
      const card = await getCharacter(member.character.id);
      if (!valid()) return;
      member.greetings = greetingOptions(card.first_mes || "", getCardGreetings(card));
      member.greetingIndex = 0; member.greetingContent = member.greetings[0]?.content || "";
      member.greetingLoaded = true;
    } catch (cause) { if (valid()) member.greetingError = message(cause); }
    finally { if (valid()) member.loadingGreeting = false; }
  }
  function selectGreeting(member: DraftMember, index: number) {
    if (locked.value || member.mode !== "card" || !members.value.includes(member) || !member.greetings[index]) return;
    member.greetingIndex = index;
    member.greetingContent = member.greetings[index].content;
  }
  async function loadSources(member: DraftMember, more = false) {
    if (!scope.active() || locked.value || member.loadingSources || member.mode !== "single_snapshot" || !members.value.includes(member)
      || (more && !member.hasMoreSources)) return;
    const current = scope.capture();
    const token = ++member.sourceVersion;
    const valid = () => current() && token === member.sourceVersion && members.value.includes(member) && member.mode === "single_snapshot";
    member.loadingSources = true;
    member.pendingSourcePage = more ? "more" : "first";
    member.sourceError = "";
    try {
      const offset = more ? member.sourceOffset : 0;
      const page = await getSessions(member.character.id, 20, offset, false);
      if (!valid()) return;
      member.sources = more ? [...member.sources, ...page.sessions] : page.sessions;
      member.sourceOffset = offset + page.sessions.length;
      member.hasMoreSources = page.has_more;
    } catch (cause) { if (valid()) member.sourceError = message(cause); }
    finally { if (valid()) { member.loadingSources = false; member.pendingSourcePage = null; } }
  }
  function setMode(member: DraftMember, mode: "card" | "single_snapshot") {
    if (locked.value || !members.value.includes(member) || member.mode === mode || (mode === "single_snapshot" && !supportsSnapshots)) return;
    member.sourceVersion++;
    member.greetingVersion++; member.loadingGreeting = false;
    member.mode = mode; member.sourceSessionId = null; member.sources = [];
    member.sourceOffset = 0; member.loadingSources = false; member.pendingSourcePage = null; member.hasMoreSources = false; member.sourceError = "";
    if (mode === "single_snapshot") void loadSources(member);
    else if (!member.greetingLoaded) void loadGreetings(member);
  }
  async function submit() {
    if (!scope.active() || locked.value) return;
    error.value = validation.value;
    if (error.value) return;
    const current = scope.capture();
    const params: CreateGroupSessionParams = { title: title.value.trim(), user_nickname: nickname.value.trim(),
      shared_setting: sharedSetting.value.trim() || null,
      members: members.value.map(member => ({ character_id: member.character.id,
        ...(member.mode === "card" ? { greeting_index: member.greetings[member.greetingIndex]?.index ?? null, greeting_content: member.greetingContent } : {}),
        origin: member.mode === "card" ? { mode: "card" } : { mode: "single_snapshot", session_id: member.sourceSessionId! } })),
    };
    submitting.value = true;
    error.value = "";
    try {
      const group = await createGroupSession(params);
      if (!current()) return;
      created.value = group;
      onCreated(group);
    } catch (cause) {
      if (!current()) return;
      uncertain.value = !/\[API Error (400|403|404|409|422)\]/.test(cause instanceof Error ? cause.message : String(cause));
      error.value = uncertain.value ? "创建结果待确认，请先到群聊列表查看，避免重复创建。" : message(cause);
    } finally { if (current()) submitting.value = false; }
  }
  return { title, nickname, sharedSetting, characters, members, loadingCharacters, hasMoreCharacters,
    characterError, submitting, error, uncertain, created, locked, validation, supportsSnapshots,
    loadCharacters, toggleCharacter, setMode, loadSources, loadGreetings, selectGreeting, submit,
    show() {
      if (!scope.activate()) return;
      void loadCharacters();
      for (const member of members.value) {
        if (member.mode === "card" && !member.greetingLoaded) void loadGreetings(member);
        if (member.pendingSourcePage) void loadSources(member, member.pendingSourcePage === "more");
      }
    }, hide: scope.deactivate };
}

export function useGroupSessionDetail(onDeleted: () => void, generation?: (id: number) => Promise<GroupGenerationOptions>) {
  const group = ref<GroupSessionDetail | null>(null);
  const loading = ref(false);
  const deleting = ref(false);
  const error = ref("");
  const serverChanged = ref(false);
  const invalidId = ref(false);
  const needsSelection = computed(() => serverChanged.value || invalidId.value);
  let sessionId: number | null = null;
  let readVersion = 0;
  const scope = usePageScope(reason => {
    readVersion++; loading.value = false; deleting.value = false;
    flow.pause();
    portraits.pausePortraits();
    if (reason === "server" || reason === "dispose") {
      group.value = null; sessionId = null;
      flow.reset();
      serverChanged.value = reason === "server";
      error.value = reason === "server" ? "服务器已变更，请返回群聊列表重新选择。" : "";
    }
  });
  const flow = useGroupRoundFlow({ id: () => sessionId, active: scope.active, capture: scope.capture, generation,
    blocked: () => loading.value || deleting.value || !group.value || portraits.portraitWriting.value });
  const portraits = useGroupPortraits({ id: () => sessionId, active: scope.active, capture: scope.capture,
    current: () => flow.current.value, members: () => group.value?.members || [],
    blocked: () => loading.value || deleting.value || flow.operationBusy.value || flow.loadingRounds.value || flow.historyStale.value,
    invalidate: flow.pause, refresh: () => flow.loadRounds() });
  function setSessionId(id: number) {
    scope.invalidate(); loading.value = false; deleting.value = false;
    readVersion++; group.value = null; error.value = ""; serverChanged.value = false;
    flow.reset();
    portraits.pausePortraits();
    sessionId = Number.isSafeInteger(id) && id > 0 ? id : null;
    invalidId.value = sessionId === null;
    if (!sessionId) error.value = "群聊编号无效，请返回列表重新选择。";
  }
  async function load() {
    if (!scope.active() || !sessionId || deleting.value) return;
    const current = scope.capture();
    const id = sessionId;
    const token = ++readVersion;
    const valid = () => current() && token === readVersion && id === sessionId;
    flow.pause();
    portraits.pausePortraits();
    loading.value = true; error.value = "";
    try {
      const result = await getGroupSession(id);
      if (valid()) group.value = result;
    } catch (cause) { if (valid()) { group.value = null; flow.pause(); error.value = message(cause); } }
    finally {
      if (valid()) {
        loading.value = false;
        if (group.value) void flow.loadRounds();
      }
    }
  }
  async function remove(confirm: () => Promise<boolean>) {
    if (!scope.active() || !flow.canDelete.value || !group.value) return;
    const current = scope.capture();
    const id = group.value.session_id;
    deleting.value = true;
    try {
      if (!await confirm() || !current() || sessionId !== id) return;
      await deleteGroupSession(id);
      if (current() && sessionId === id) { group.value = null; flow.reset(); onDeleted(); }
    } catch (cause) { if (current() && sessionId === id) error.value = message(cause); }
    finally { if (current() && sessionId === id) deleting.value = false; }
  }
  return { group, loading, deleting, error, serverChanged, needsSelection, setSessionId, load, remove,
    ...flow, ...portraits,
    show() { if (scope.activate()) void load(); }, hide: scope.deactivate };
}
