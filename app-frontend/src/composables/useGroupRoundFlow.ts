import { computed, ref, watch } from "vue";
import { getBaseUrl, USE_MOCK } from "@/api/config";
import { getGroupRounds, getGroupRequest, getGroupCandidates, getGroupCandidate,
  sendGroupRound, regenerateGroupRound, resumeGroupRound, selectGroupCandidate, discardGroupRound } from "@/api/groupSessions";
import type { GroupRound, GroupCurrentState, GroupCandidateSummary, GetGroupCandidateResponse,
  GroupOperationKind, GroupObservedCommand, GroupRoundCommand, GroupAcceptedOperation, GetGroupRoundsResponse, GroupGenerationOptions } from "@/types/groupSessions";

interface Context {
  id: () => number | null;
  active: () => boolean;
  capture: () => () => boolean;
  blocked: () => boolean;
  generation?: (id: number) => Promise<GroupGenerationOptions>;
}
interface PendingRequest { request_id: string; kind: GroupOperationKind; rejected?: boolean }

function historyStamp(state: GroupCurrentState | undefined | null): string {
  const latest = state?.latest;
  return JSON.stringify([state?.group_revision, latest?.round_id, latest?.candidate_id,
    latest?.candidate_revision, latest?.confirmed]);
}

function errorMessage(cause: unknown): string {
  const raw = cause instanceof Error ? cause.message : String(cause);
  const body = raw.match(/\{.*\}$/s);
  if (body) {
    try {
      const detail = JSON.parse(body[0]).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) return "输入内容不符合要求，请检查长度并刷新后重试。";
    } catch {}
  }
  return raw;
}

// 请求 ID 仅用于幂等定位；三个目标平台均可使用，不依赖浏览器 crypto。
function requestId(): string {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, letter => {
    const digit = Math.floor(Math.random() * 16);
    return (letter === "x" ? digit : (digit & 3) | 8).toString(16);
  });
}

export function useGroupRoundFlow(context: Context) {
  const rounds = ref<GroupRound[]>([]);
  const loadingRounds = ref(false), roundsError = ref(""), hasMoreRounds = ref(false);
  const current = ref<GroupCurrentState | null>(null);
  const canGenerate = ref(false), draft = ref("");
  const storageReady = ref(true);
  const visibleHistoryStamp = ref<string | null>(null);
  const submitting = ref(false), recovering = ref(false), operationError = ref(""), notice = ref("");
  const pending = ref<PendingRequest | null>(null);
  const candidates = ref<GroupCandidateSummary[]>([]);
  const candidateRoundId = ref<number | null>(null), loadingCandidates = ref(false), candidatesError = ref("");
  const hasMoreCandidates = ref(false), preview = ref<GetGroupCandidateResponse | null>(null);
  const loadingPreview = ref(false), previewError = ref("");
  const adoptedState = ref<GetGroupCandidateResponse | null>(null);
  const loadingAdoptedState = ref(false), adoptedStateError = ref("");
  let adoptedStateVersion = 0;
  let epoch = 0, historyVersion = 0, candidateVersion = 0, previewVersion = 0;
  let roundOffset = 0, candidateOffset = 0, retryMore = false;
  let submittedContent: string | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const operationBusy = computed(() => submitting.value || recovering.value || !!pending.value || !!current.value?.active_operation);
  const historyStale = computed(() => !!current.value && visibleHistoryStamp.value !== historyStamp(current.value));
  const canDelete = computed(() => !operationBusy.value && !context.blocked() && !loadingRounds.value && !roundsError.value
    && visibleHistoryStamp.value !== null && storageReady.value && !historyStale.value);
  const locked = computed(() => operationBusy.value || context.blocked() || loadingRounds.value || !!roundsError.value || !current.value || !storageReady.value || historyStale.value);
  const canSend = computed(() => !locked.value && canGenerate.value && !!current.value?.capabilities.can_send);
  const canRegenerate = computed(() => !locked.value && canGenerate.value && !!current.value?.capabilities.can_regenerate);
  const canDiscard = computed(() => !locked.value && !!current.value?.capabilities.can_discard);

  function invalidateAdoptedState() {
    adoptedStateVersion++; adoptedState.value = null;
    loadingAdoptedState.value = false; adoptedStateError.value = "";
  }
  watch([() => historyStamp(current.value), () => operationBusy.value], invalidateAdoptedState, { flush: "sync" });

  async function loadAdoptedState() {
    const latest = current.value?.latest;
    if (!context.active() || !context.id() || context.blocked() || operationBusy.value
      || historyStale.value || !latest?.candidate_id || loadingAdoptedState.value) return;
    const stamp = historyStamp(current.value), validContext = ticket(), version = ++adoptedStateVersion;
    const valid = () => validContext() && version === adoptedStateVersion && stamp === historyStamp(current.value);
    adoptedState.value = null; loadingAdoptedState.value = true; adoptedStateError.value = "";
    try {
      const result = await getGroupCandidate(context.id()!, latest.round_id, latest.candidate_id);
      if (!valid()) return;
      if (stamp !== historyStamp(result.current) || result.candidate.candidate_id !== latest.candidate_id
        || result.candidate.revision !== latest.candidate_revision || result.round.round_id !== latest.round_id
        || result.round.selected_candidate_id !== latest.candidate_id
        || result.state_preview.candidate_id !== latest.candidate_id) {
        adoptedStateError.value = "剧情已有更新，请刷新发言后重新读取成员状态。";
        return;
      }
      adoptedState.value = result;
    } catch (cause) { if (valid()) adoptedStateError.value = errorMessage(cause); }
    finally { if (valid()) loadingAdoptedState.value = false; }
  }

  function clearTimer() { if (timer !== null) clearTimeout(timer); timer = null; }
  function ticket() {
    const generation = epoch, id = context.id(), valid = context.capture();
    return () => context.active() && generation === epoch && id === context.id() && valid();
  }
  function storageKey() { return `group_request:${encodeURIComponent(getBaseUrl())}:${context.id()}`; }
  function remember(value: PendingRequest | null) {
    if (value) uni.setStorageSync(storageKey(), value);
    else uni.removeStorageSync(storageKey());
    pending.value = value;
  }
  function restore() {
    if (pending.value || USE_MOCK) return;
    try {
      const saved = uni.getStorageSync(storageKey());
      if (saved && typeof saved.request_id === "string" && /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(saved.request_id)
        && ["send", "regenerate", "resume", "select", "discard"].includes(saved.kind)) pending.value = saved;
      storageReady.value = true;
    } catch { storageReady.value = false; operationError.value = "无法读取本机请求记录，请恢复本机存储后重新进入。"; }
  }
  function observe(state: GroupCurrentState | undefined, available?: boolean) {
    if (state && current.value && state.group_revision < current.value.group_revision) return false;
    if (state && current.value && state.group_revision === current.value.group_revision) {
      const previous = current.value;
      if (state.latest?.candidate_id === previous.latest?.candidate_id
        && (state.latest?.candidate_revision ?? 0) < (previous.latest?.candidate_revision ?? 0)) return false;
      if (state.active_operation?.operation_id === previous.active_operation?.operation_id
        && (state.active_operation?.revision ?? 0) < (previous.active_operation?.revision ?? 0)) return false;
    }
    current.value = state ?? null;
    canGenerate.value = !USE_MOCK && available === true;
    return true;
  }
  function pause() {
    invalidateAdoptedState();
    epoch++; historyVersion++; candidateVersion++; previewVersion++; clearTimer();
    loadingRounds.value = loadingCandidates.value = loadingPreview.value = false;
    submitting.value = recovering.value = false;
    current.value = null; canGenerate.value = false;
    visibleHistoryStamp.value = null;
    candidateRoundId.value = null; candidates.value = []; candidateOffset = 0; hasMoreCandidates.value = false;
    preview.value = null; candidatesError.value = previewError.value = "";
  }
  function reset() {
    pause(); rounds.value = []; roundOffset = 0; hasMoreRounds.value = false; roundsError.value = "";
    candidates.value = []; candidateRoundId.value = null; candidateOffset = 0; hasMoreCandidates.value = false;
    preview.value = null; candidatesError.value = previewError.value = "";
    draft.value = ""; submittedContent = null; storageReady.value = true; pending.value = null; operationError.value = notice.value = "";
  }
  function schedule() {
    clearTimer();
    if (context.active() && pending.value) timer = setTimeout(() => { void recover(); }, 1500);
  }
  async function loadRounds(more = false, fromRecovery = false): Promise<boolean> {
    if (!context.active() || !context.id() || context.blocked() || loadingRounds.value || submitting.value
      || (recovering.value && !fromRecovery) || (more && !hasMoreRounds.value)) return false;
    const validContext = ticket(), version = ++historyVersion;
    const valid = () => validContext() && version === historyVersion;
    loadingRounds.value = true; roundsError.value = ""; retryMore = more;
    try {
      const page: GetGroupRoundsResponse = await getGroupRounds(context.id()!, 20, more ? roundOffset : 0);
      if (!valid()) return false;
      if (!observe(page.current, page.can_generate)) { roundsError.value = "读取到较早状态，请重新查询。"; return false; }
      const rows = more ? [...rounds.value, ...page.rounds] : page.rounds;
      rounds.value = rows.filter((row, index) => rows.findIndex(item => item.round_id === row.round_id) === index);
      if (!more) visibleHistoryStamp.value = historyStamp(page.current);
      roundOffset = page.offset + page.rounds.length; hasMoreRounds.value = page.has_more && page.rounds.length > 0;
      if (!fromRecovery) {
        restore();
        if (!pending.value && page.current?.active_operation) {
          const active = page.current.active_operation;
          pending.value = { request_id: active.request_id, kind: active.kind };
        }
      }
      return true;
    } catch (cause) { if (valid()) roundsError.value = errorMessage(cause); return false; }
    finally {
      if (valid()) {
        loadingRounds.value = false;
        if (!fromRecovery && pending.value) void recover();
      }
    }
  }
  async function loadCandidates(roundId: number, more = false) {
    if (!context.active() || !context.id() || submitting.value || (more && (loadingCandidates.value || !hasMoreCandidates.value))) return;
    if (candidateRoundId.value !== roundId) {
      candidates.value = []; candidateOffset = 0; hasMoreCandidates.value = false;
      previewVersion++; preview.value = null; loadingPreview.value = false; previewError.value = "";
    }
    candidateRoundId.value = roundId;
    const validContext = ticket(), version = ++candidateVersion;
    const valid = () => validContext() && version === candidateVersion && candidateRoundId.value === roundId;
    loadingCandidates.value = true; candidatesError.value = "";
    try {
      const page = await getGroupCandidates(context.id()!, roundId, 20, more ? candidateOffset : 0);
      if (!valid() || !observe(page.current, page.can_generate)) return;
      const rows = more ? [...candidates.value, ...page.candidates] : page.candidates;
      candidates.value = rows.filter((row, index) => rows.findIndex(item => item.candidate_id === row.candidate_id) === index);
      candidateOffset = page.offset + page.candidates.length; hasMoreCandidates.value = page.has_more && page.candidates.length > 0;
    } catch (cause) { if (valid()) candidatesError.value = errorMessage(cause); }
    finally { if (valid()) loadingCandidates.value = false; }
  }
  async function viewCandidate(roundId: number, candidateId: number) {
    if (!context.active() || !context.id() || submitting.value || candidateRoundId.value !== roundId) return;
    const validContext = ticket(), version = ++previewVersion;
    const valid = () => validContext() && version === previewVersion && candidateRoundId.value === roundId;
    preview.value = null; loadingPreview.value = true; previewError.value = "";
    try {
      const result = await getGroupCandidate(context.id()!, roundId, candidateId);
      if (valid() && observe(result.current, result.can_generate)) preview.value = result;
    } catch (cause) { if (valid()) previewError.value = errorMessage(cause); }
    finally { if (valid()) loadingPreview.value = false; }
  }
  async function refreshViews(valid: () => boolean) {
    if (!await loadRounds(false, true) || !valid()) return false;
    const rid = candidateRoundId.value, cid = preview.value?.candidate.candidate_id;
    const viewVersion = previewVersion;
    if (rid && rounds.value.some(row => row.round_id === rid)) {
      await loadCandidates(rid);
      if (!valid()) return false;
      if (cid && previewVersion === viewVersion) await viewCandidate(rid, cid);
    } else if (rid) {
      candidateVersion++; previewVersion++; candidateRoundId.value = null;
      candidates.value = []; preview.value = null;
    }
    return valid();
  }
  async function recover() {
    if (!context.active() || !context.id() || recovering.value || submitting.value || context.blocked()) return;
    if (!pending.value && current.value?.active_operation) {
      const active = current.value.active_operation;
      pending.value = { request_id: active.request_id, kind: active.kind };
    }
    if (!pending.value) return;
    clearTimer();
    const valid = ticket(), request = pending.value;
    recovering.value = true; operationError.value = "";
    try {
      if (request.rejected) {
        if (!await refreshViews(valid)) return;
        remember(null);
        operationError.value = "上次请求未被接受，本机记录已清理，可以修正后重新操作。";
        return;
      }
      const result = await getGroupRequest(context.id()!, request.request_id);
      if (!valid() || pending.value?.request_id !== request.request_id) return;
      observe(result.current, result.can_generate);
      if (request.kind === "send" && submittedContent !== null && draft.value === submittedContent) draft.value = "";
      const terminal = result.status === "succeeded" || result.status === "failed";
      if (!await refreshViews(valid)) return;
      if (terminal) {
        remember(null);
        notice.value = result.error_code === 'resource_paused' ? '本次执行已暂停，已保存的回复可继续。'
          : result.status === "failed" ? "本次执行未完成，已保存前缀可查看。可显式继续、重新生成或撤回。"
          : request.kind === "discard" ? "这轮已撤回，不再进入后续剧情。" : "操作已完成，当前采用内容以最新轮次为准。";
        const active = current.value?.active_operation;
        if (active) pending.value = { request_id: active.request_id, kind: active.kind };
      }
      if (pending.value) schedule();
    } catch (cause) {
      if (valid()) operationError.value = request.rejected
        ? "上次请求未被接受，但本机存储清理失败，请恢复存储后重新查询。"
        : `结果待确认，请重新查询，勿重复发送。${errorMessage(cause)}`;
    } finally { if (valid()) recovering.value = false; }
  }
  async function resumeRound(round: GroupRound, confirm?: () => Promise<boolean>) {
    if (operationBusy.value || loadingCandidates.value || context.blocked()) return;
    const valid = ticket(), targetId = round.pending_candidate?.error_code === 'resource_paused'
      ? round.pending_candidate.candidate_id : round.candidate_id;
    await loadCandidates(round.round_id);
    if (!valid() || current.value?.latest?.round_id !== round.round_id) return;
    if (candidatesError.value) { operationError.value = candidatesError.value; return; }
    const candidate = candidates.value.find(row => row.candidate_id === targetId);
    if (candidate?.can_resume) await command('resume', candidate, confirm);
    else operationError.value = '当前进度已变化，请刷新消息后再继续。';
  }
  async function command(kind: GroupOperationKind, candidate?: GroupCandidateSummary, confirm?: () => Promise<boolean>) {
    if (!context.active() || !context.id() || locked.value || USE_MOCK) return;
    if (kind === "send" && (!canSend.value || !draft.value.trim() || [...draft.value].length > 20000)) return;
    if (kind === "regenerate" && !canRegenerate.value || kind === "discard" && !canDiscard.value) return;
    const state = current.value!, latest = state.latest;
    if (kind !== "send" && (!latest || latest.confirmed)) return;
    if (kind === "select" || kind === "resume") {
      if (candidateRoundId.value !== latest?.round_id || !candidate || loadingCandidates.value || candidatesError.value) return;
      if (kind === "select" && (!candidate.can_select || candidate.candidate_id === latest?.candidate_id || !state.capabilities.can_select)) return;
      if (kind === "resume" && (!candidate.can_resume || !canGenerate.value)) return;
    }
    const valid = ticket(), id = context.id()!;
    submitting.value = true; operationError.value = ""; notice.value = ""; clearTimer();
    const content = draft.value;
    const targetId = candidate?.candidate_id, targetRevision = candidate?.revision;
    const body: GroupObservedCommand = { client_request_id: requestId(), expected_group_revision: state.group_revision,
      observed_round_id: latest?.round_id ?? null, observed_candidate_id: latest?.candidate_id ?? null,
      observed_candidate_revision: latest?.candidate_revision ?? null };
    let sent = false, rejected = false;
    try {
      if (confirm && (!await confirm() || !valid())) return;
      if (!valid()) return;
      let generation: GroupGenerationOptions = {};
      if ((kind === 'send' || kind === 'regenerate') && context.generation) {
        try { generation = { ...await context.generation(id) }; }
        catch {
          if (valid()) operationError.value = '模型配置尚未加载，请检查连接后重试。';
          return;
        }
        if (!valid()) return;
      }
      remember({ request_id: body.client_request_id, kind });
      if (kind === "send") submittedContent = content;
      // 后续恢复仅使用 GET。接受回执的旧版本不回写到当前选择。
      sent = true;
      let receipt: GroupAcceptedOperation;
      if (kind === "send") receipt = await sendGroupRound(id, { ...body, ...generation, user_content: content });
      else if (kind === "regenerate") receipt = await regenerateGroupRound(id, latest!.round_id, { ...body, ...generation } as GroupRoundCommand);
      else if (kind === "discard") receipt = await discardGroupRound(id, latest!.round_id, body as GroupRoundCommand);
      else {
        const target = { ...body as GroupRoundCommand, target_candidate_id: targetId!, target_candidate_revision: targetRevision! };
        receipt = kind === "resume" ? await resumeGroupRound(id, latest!.round_id, target) : await selectGroupCandidate(id, latest!.round_id, target);
      }
      if (!valid()) return;
      if (kind === "send" && draft.value === content) draft.value = "";
      notice.value = `请求已接受，正在查询${receipt.status === "queued" ? "后台进展" : "当前结果"}。`;
    } catch (cause) {
      if (!valid()) return;
      rejected = /\[API Error (400|403|404|409|422)\]/.test(cause instanceof Error ? cause.message : String(cause));
      if (sent && rejected) {
        submittedContent = null;
        try { remember(null); }
        catch {
          const record = { request_id: body.client_request_id, kind, rejected: true };
          pending.value = record;
          try { uni.setStorageSync(storageKey(), record); } catch {}
          operationError.value = "请求已被拒绝，但本机记录未能清理，请恢复本机存储后重新查询。";
          return;
        }
      }
      operationError.value = !sent ? "无法保存本机请求记录，本次未发送。请恢复本机存储后重试。"
        : rejected ? errorMessage(cause) : "提交结果待确认，请查询结果，勿重复发送。";
    } finally {
      if (valid()) {
        submitting.value = false;
        if (sent && !rejected) void recover();
        else if (sent) { current.value = null; void loadRounds(); }
      }
    }
  }
  return { rounds, loadingRounds, roundsError, hasMoreRounds, loadRounds, retryRounds: () => loadRounds(retryMore),
    current, canGenerate, draft, submitting, recovering, operationError, notice, pending, operationBusy, locked, historyStale, canDelete,
    canSend, canRegenerate, canDiscard, recover, command, resumeRound, candidates, candidateRoundId, loadingCandidates, candidatesError,
    hasMoreCandidates, loadCandidates, preview, loadingPreview, previewError, viewCandidate,
    adoptedState, loadingAdoptedState, adoptedStateError, loadAdoptedState, pause, reset };
}
