import { ref, watch, onScopeDispose } from "vue";
import { getBaseUrl } from "@/api/config";
import { getRoleState, updateRoleState } from "@/api/roleStates";
import type { RoleStateSnapshot, RoleStatePatch, ActorState } from "@/types/roleState";

export function useRoleState(sessionId: () => number | null, generating: () => boolean) {
  const snapshot = ref<RoleStateSnapshot | null>(null);
  const busy = ref(false);
  const error = ref("");
  const editing = ref(false);
  const scene = ref("");
  const actors = ref<Array<{ name: string; posture: string; clothing: string; location: string }>>([]);
  const newName = ref("");
  let version = 0;
  let disposed = false;
  let stateServer = getBaseUrl();

  function reset() {
    version++;
    snapshot.value = null;
    busy.value = false;
    editing.value = false;
    error.value = "";
    scene.value = "";
    actors.value = [];
    newName.value = "";
  }
  function message(cause: unknown) {
    const raw = cause instanceof Error ? cause.message : "状态请求失败，请重试";
    return raw.match(/"detail"\s*:\s*"([^"]+)"/)?.[1] || raw;
  }
  async function load() {
    if (disposed || sessionId() === null || editing.value) return;
    if (stateServer !== getBaseUrl()) { stateServer = getBaseUrl(); reset(); }
    const token = ++version;
    const id = sessionId()!;
    const server = getBaseUrl();
    const valid = () => !disposed && token === version && id === sessionId() && server === getBaseUrl();
    busy.value = true;
    error.value = "";
    try {
      const result = await getRoleState(id);
      if (valid()) snapshot.value = result;
    } catch (cause) {
      if (valid()) error.value = message(cause);
    } finally {
      if (valid()) busy.value = false;
    }
  }
  function beginEdit() {
    if (!snapshot.value || busy.value || generating()) return;
    if (stateServer !== getBaseUrl()) { void load(); return; }
    scene.value = snapshot.value.state.scene || "";
    actors.value = Object.entries(snapshot.value.state.characters || {}).map(([name, state]) => ({
      name, posture: state.posture || "", clothing: state.clothing || "", location: state.location || "",
    }));
    newName.value = "";
    error.value = "";
    editing.value = true;
  }
  function addActor() {
    const name = newName.value.trim();
    if (!name || name.length > 50 || actors.value.some(actor => actor.name === name)) {
      error.value = "请填写不重复的角色名称（最多 50 字）。";
      return;
    }
    if (actors.value.length >= 8) { error.value = "最多维护 8 名角色。"; return; }
    actors.value.push({ name, posture: "", clothing: "", location: "" });
    newName.value = "";
    error.value = "";
  }
  async function cancel() {
    if (busy.value) return;
    editing.value = false;
    await load();
  }
  async function save() {
    if (!snapshot.value || busy.value || !editing.value || generating()) return;
    if (stateServer !== getBaseUrl()) { stateServer = getBaseUrl(); reset(); await load(); return; }
    if (newName.value.trim()) { error.value = "请先添加已填写的人物，或清空角色名称。"; return; }
    const patch: RoleStatePatch = {};
    const before = snapshot.value.state;
    const nextScene = scene.value.trim();
    if (nextScene !== (before.scene || "")) patch.scene = nextScene || null;
    const updated = Object.fromEntries(actors.value.map(actor => [actor.name, actor]));
    for (const name of new Set([...Object.keys(before.characters || {}), ...Object.keys(updated)])) {
      const fields: { [K in keyof ActorState]?: string | null } = {};
      for (const key of ["posture", "clothing", "location"] as const) {
        const value = updated[name]?.[key].trim() || "";
        if (value !== (before.characters?.[name]?.[key] || "")) fields[key] = value || null;
      }
      if (Object.keys(fields).length) (patch.characters ||= Object.create(null))[name] = fields;
    }
    const token = ++version;
    const id = sessionId()!;
    const server = getBaseUrl();
    const valid = () => !disposed && token === version && id === sessionId() && server === getBaseUrl();
    busy.value = true;
    error.value = "";
    try {
      const result = await updateRoleState(id, snapshot.value.revision, patch);
      if (valid()) { snapshot.value = result; editing.value = false; }
    } catch (cause) {
      if (valid()) error.value = message(cause) + "；草稿已保留，可取消并重新加载。";
    } finally {
      if (valid()) busy.value = false;
    }
  }
  watch(() => [sessionId(), getBaseUrl()], () => { stateServer = getBaseUrl(); reset(); void load(); }, { immediate: true });
  onScopeDispose(() => { disposed = true; reset(); });
  return { snapshot, busy, error, editing, scene, actors, newName, load, beginEdit, addActor, cancel, save };
}
