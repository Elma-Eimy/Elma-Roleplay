import { computed, ref, watch } from "vue";
import { getGroupPortraits, setGroupPortrait } from "@/api/groupSessions";
import { getPortraits } from "@/api/portraits";
import type { CharacterPortrait } from "@/types/portraits";
import type { GroupCurrentState, GroupPortraitChange, GroupPortraitsResponse, GroupSessionMember } from "@/types/groupSessions";

interface Context {
  id: () => number | null;
  active: () => boolean;
  capture: () => () => boolean;
  blocked: () => boolean;
  current: () => GroupCurrentState | null;
  members: () => GroupSessionMember[];
  invalidate: () => void;
  refresh: () => Promise<boolean>;
}
interface Options { rows: CharacterPortrait[]; loading: boolean; error: string; hasMore: boolean }
const stamp = (state: GroupCurrentState | null) => JSON.stringify([state?.group_revision,
  state?.latest?.round_id, state?.latest?.candidate_id, state?.latest?.candidate_revision, state?.latest?.confirmed]);

export function useGroupPortraits(context: Context) {
  const portraitData = ref<GroupPortraitsResponse | null>(null), loadingPortraits = ref(false);
  const portraitWriting = ref(false), portraitError = ref("");
  const portraitOptions = ref<Record<number, Options>>({});
  let epoch = 0, readVersion = 0;
  const canChoosePortrait = computed(() => !!portraitData.value?.can_update && !portraitWriting.value
    && !loadingPortraits.value && !context.blocked());
  function clearRead() {
    readVersion++; portraitData.value = null; loadingPortraits.value = false;
    portraitOptions.value = {}; portraitError.value = "";
  }
  watch(() => stamp(context.current()), clearRead, { flush: "sync" });
  function ticket() {
    const current = context.capture(), saved = epoch, id = context.id();
    return () => context.active() && saved === epoch && id === context.id() && current();
  }
  function pausePortraits() { epoch++; clearRead(); portraitWriting.value = false; }
  async function loadPortraits() {
    if (!context.active() || !context.id() || !context.current() || context.blocked() || portraitWriting.value || loadingPortraits.value) return;
    const validContext = ticket(), version = ++readVersion, expected = stamp(context.current());
    const valid = () => validContext() && version === readVersion && expected === stamp(context.current());
    portraitData.value = null; loadingPortraits.value = true; portraitError.value = "";
    try {
      const result = await getGroupPortraits(context.id()!);
      if (!valid()) return;
      if (result.session_id !== context.id() || stamp(result.current) !== expected) {
        portraitError.value = "剧情已更新，请刷新立绘后再选择。"; return;
      }
      portraitData.value = result;
    } catch { if (valid()) portraitError.value = "立绘读取失败，请刷新重试；旧服务器或离线模式可能不支持群聊立绘。"; }
    finally { if (valid()) loadingPortraits.value = false; }
  }
  async function loadPortraitOptions(personaId: number, more = false) {
    if (!canChoosePortrait.value || !context.active()) return;
    const member = context.members().find(row => row.persona_id === personaId);
    if (!member) return;
    const previous = portraitOptions.value[personaId];
    if (previous?.loading || (more && !previous?.hasMore)) return;
    const options: Options = { rows: more ? previous.rows : [], loading: true, error: "", hasMore: false };
    portraitOptions.value[personaId] = options;
    const saved = portraitOptions.value[personaId], validContext = ticket();
    const valid = () => validContext() && portraitOptions.value[personaId] === saved;
    try {
      const page = await getPortraits(member.character.id, saved.rows.length);
      if (!valid()) return;
      saved.rows = [...saved.rows, ...page.portraits].filter((row, index, all) => all.findIndex(item => item.id === row.id) === index);
      saved.hasMore = page.has_more && page.portraits.length > 0;
    } catch { if (valid()) { saved.error = "素材读取失败，请重试。"; saved.hasMore = more; } }
    finally { if (valid()) saved.loading = false; }
  }
  async function choosePortrait(personaId: number, portraitId: number | null) {
    if (!canChoosePortrait.value || !context.active() || !context.id()
      || !context.members().some(row => row.persona_id === personaId)) return;
    const state = context.current()!, latest = state.latest;
    const body: GroupPortraitChange = { portrait_id: portraitId, expected_group_revision: state.group_revision,
      observed_round_id: latest?.round_id ?? null, observed_candidate_id: latest?.candidate_id ?? null,
      observed_candidate_revision: latest?.candidate_revision ?? null };
    const valid = ticket(), id = context.id()!;
    portraitWriting.value = true;
    context.invalidate();
    let failed = false;
    try { await setGroupPortrait(id, personaId, body); }
    catch { failed = true; }
    finally {
      if (valid()) {
        portraitWriting.value = false;
        if (await context.refresh() && valid()) await loadPortraits();
        if (valid() && failed) portraitError.value = "立绘变更未能确认，请核对刷新后的选择；不会自动重发。";
      }
    }
  }
  async function refreshPortraits() {
    if (!context.active() || context.blocked() || portraitWriting.value || loadingPortraits.value) return;
    const valid = ticket();
    if (await context.refresh() && valid()) await loadPortraits();
  }
  return { portraitData, loadingPortraits, portraitWriting, portraitError, portraitOptions, canChoosePortrait,
    loadPortraits, refreshPortraits, loadPortraitOptions, choosePortrait, pausePortraits };
}
