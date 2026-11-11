const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');
const { parse, compileScript } = require('@vue/compiler-sfc');
const { sourceRoot } = require('./helpers/load-ts.cjs');

function fixture() {
  const filename = path.join(sourceRoot, 'pages/group/detail.vue');
  const source = fs.readFileSync(filename, 'utf8');
  const { descriptor } = parse(source);
  const script = compileScript(descriptor, { id: 'group-display' }).content;
  const code = ts.transpileModule(script, { compilerOptions: {
    target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, esModuleInterop: true,
  } }).outputText;
  const members = [1, 2].map(id => ({ persona_id: id, character: { id: id + 10, avatar_path: `avatar${id}` }, greeting_content: id === 1 ? 'opening' : null }));
  const navigations = [], toasts = [], promptRequests = [];
  const state = Object.fromEntries(source.match(/const \{ group,([\s\S]*?)\} = state;/)[0]
    .replace(/const \{|\} = state;/g, '').split(',').map(name => [name.trim(), vue.ref(null)]));
  Object.assign(state, { group: vue.ref({ session_id: 1, members }), rounds: vue.ref([]),
    portraitData: vue.ref(null), current: vue.ref(null), loading: vue.ref(false), loadingRounds: vue.ref(false),
    operationBusy: vue.ref(false), loadPortraits() {}, loadAdoptedState() {}, hide() {}, show() {},
  });
  const scroll = Object.fromEntries(['scrollTop', 'scrollIntoViewId', 'scrollWithAnimation', 'keyboardHeight', 'hasUnreadBelow'].map(key => [key, vue.ref(0)]));
  const anchors = [];
  const focusScrolls = [], modelCalls = [], activations = [], lifecycle = {};
  Object.assign(scroll, { isAndroid: false, resetPinState() {}, followNewContent() {}, triggerPhasedScroll: () => focusScrolls.push(true),
    maintainScrollPosition: (...args) => anchors.push(args) });
  const prefs = { fontScale: 'lg', lineSpacing: 'compact', bubbleStyle: 'novel', colorTheme: 'dark' };
  const settings = { readingPrefs: prefs, selection: { model: 'chosen-model', thinking_mode: 'enabled', reasoning_effort: 'high' },
    activateSession: id => activations.push(id), refreshModels: async () => {},
    requestGeneration: async (id, options) => { modelCalls.push({ id, options }); return options; } };
  const module = { exports: {} };
  const scope = vue.effectScope();
  let view;
  scope.run(() => {
    vm.runInNewContext(code, { module, exports: module.exports, uni: {
      getSystemInfoSync: () => ({ windowWidth: 390 }), getStorageSync: () => '', setStorageSync() {},
      navigateTo: options => navigations.push(options), showToast: options => toasts.push(options),
    }, require(name) {
      if (name === 'vue') return { ...vue, getCurrentInstance: () => null };
      if (name === '@dcloudio/uni-app') return Object.fromEntries(['onLoad', 'onShow', 'onHide', 'onUnload', 'onReady', 'onResize'].map(key => [key, callback => { lifecycle[key] = callback; }]));
      if (name.endsWith('.vue')) return {};
      if (name.endsWith('/useGroupSessions')) return { useGroupSessionDetail: (_, generation) => { state.generation = generation; return state; } };
      if (name.endsWith('/useChatScroll')) return { useChatScroll: () => scroll };
      if (name.endsWith('/chatSettingsStore')) return { useChatSettingsStore: () => settings };
      if (name.endsWith('/config')) return { getBaseUrl: () => 'isolated-server' };
      if (name.endsWith('/groupSessions')) return { compileGroupMemberPrompt: (...args) => new Promise(resolve => promptRequests.push({ args, resolve })) };
      if (name.endsWith('/characters')) return { getAvatarUrl: value => value };
      if (name.endsWith('/useStoryKeepsakes')) return { STORY_PALETTES: [{}] };
      if (name.endsWith('/groupRounds')) return {};
      throw new Error(`Unexpected dependency: ${name}`);
    } }, { filename });
    view = module.exports.default.setup({}, { expose() {} });
  });
  return { view, state, scope, prefs, navigations, toasts, anchors, scroll, settings, modelCalls, activations, lifecycle, focusScrolls, promptRequests };
}

test('member prompt preview ignores a late response after leaving the group', async () => {
  const f = fixture();
  const pending = f.view.openMemberPrompt(2);
  assert.deepEqual(f.promptRequests[0].args, [1, 2]);
  f.lifecycle.onHide();
  f.promptRequests[0].resolve({ messages: [{ role: 'system', content: 'old prompt' }] });
  await pending;
  assert.equal(f.view.promptPreview.value, null);
  assert.equal(f.view.promptLoading.value, false);
  f.scope.stop();
});

test('group view uses adopted portraits, follows the speaker and keeps candidate previews separate', async () => {
  const f = fixture();
  assert.equal(f.view.hasGreetings.value, true);
  assert.equal(f.view.chatSettingsStore.readingPrefs, f.prefs);
  assert.equal(f.view.backgroundUrl.value, 'avatar1');
  f.state.rounds.value = [{ utterances: [{ speaker_persona_id: 2 }], portraits: [{ persona_id: 2, image_path: 'saved2' }] }];
  assert.equal(f.view.backgroundUrl.value, 'saved2');
  f.state.preview.value = { state_preview: { members: [{ persona_id: 2, portrait: { image_path: 'unselected' } }] } };
  assert.equal(f.view.backgroundUrl.value, 'saved2');
  f.state.portraitData.value = { members: [{ persona_id: 2, image_path: 'adopted2' }] };
  assert.equal(f.view.backgroundUrl.value, 'adopted2');
  f.view.focusedPersona.value = 1;
  assert.equal(f.view.backgroundUrl.value, 'avatar1');
  f.state.group.value = null;
  await vue.nextTick();
  assert.equal(f.view.isImmersive.value, false);
  assert.equal(f.view.focusedPersona.value, null);
  f.scope.stop();
});

test('background failures fall back to the avatar and stale errors cannot hide a new member', () => {
  const f = fixture();
  f.state.portraitData.value = { members: [{ persona_id: 1, image_path: 'portrait1' }] };
  const error = source => ({ currentTarget: { dataset: { source } } });
  f.view.onBackgroundUnavailable(error('portrait1'));
  assert.equal(f.view.backgroundUrl.value, 'avatar1');
  f.view.focusedPersona.value = 2;
  f.view.onBackgroundUnavailable(error('avatar1'));
  assert.equal(f.view.backgroundUrl.value, 'avatar2');
  assert.equal(f.view.isImmersive.value, true);
  f.view.onBackgroundUnavailable(error('avatar2'));
  assert.equal(f.view.isImmersive.value, false);
  f.scope.stop();
});

test('drawer avatars open the corresponding character once and preserve the group draft on success or failure', () => {
  const f = fixture();
  f.view.showDetails.value = true;
  f.state.draft.value = 'unfinished group message';
  f.view.openCharacterProfile(2);
  f.view.openCharacterProfile(1);
  assert.equal(f.navigations.length, 1);
  assert.equal(f.navigations[0].url, '/pages/character/detail?id=12');
  f.navigations[0].fail(); f.navigations[0].complete();
  assert.equal(f.view.showDetails.value, true);
  assert.equal(f.toasts.length, 1);
  f.view.openCharacterProfile(1);
  assert.equal(f.navigations[1].url, '/pages/character/detail?id=11');
  f.navigations[1].success(); f.navigations[1].complete();
  assert.equal(f.view.showDetails.value, false);
  assert.equal(f.state.draft.value, 'unfinished group message');
  f.scope.stop();
});

test('leaving the group invalidates old profile navigation callbacks', () => {
  const f = fixture();
  f.view.showDetails.value = true;
  f.view.openCharacterProfile(1);
  f.view.hide();
  f.view.showDetails.value = true;
  f.view.openCharacterProfile(2);
  f.navigations[0].success(); f.navigations[0].fail(); f.navigations[0].complete();
  assert.equal(f.view.showDetails.value, true);
  assert.equal(f.view.openingProfile.value, true);
  assert.equal(f.toasts.length, 0);
  f.navigations[1].complete();
  assert.equal(f.view.openingProfile.value, false);
  f.scope.stop();
});

test('empty and failed new rounds retain the last speaker and adopted portrait', () => {
  const f = fixture();
  f.state.rounds.value = [
    { round_id: 2, round_index: 2, utterances: [], portraits: [] },
    { round_id: 1, round_index: 1, utterances: [{ speaker_persona_id: 2 }], portraits: [{ persona_id: 2, image_path: 'saved2' }] },
  ];
  assert.equal(f.view.backgroundMember.value.persona_id, 2);
  assert.equal(f.view.backgroundUrl.value, 'saved2');
  f.state.portraitData.value = { members: [{ persona_id: 2, image_path: '' }] };
  assert.equal(f.view.backgroundUrl.value, 'avatar2', 'an explicit empty current image must not restore an older portrait');
  f.scope.stop();
});

test('pagination only restores the anchor after success in the same page incarnation', async () => {
  for (const outcome of ['success', 'failure', 'hide', 'switch']) {
    const f = fixture();
    f.state.rounds.value = [{ round_id: 11, round_index: 1, utterances: [] }];
    let finish;
    f.state.loadRounds = () => new Promise(resolve => { finish = resolve; });
    const pending = f.view.moreRounds();
    if (outcome === 'hide') f.view.hide();
    if (outcome === 'switch') {
      const original = f.state.group.value;
      f.state.group.value = null;
      f.state.group.value = original;
    }
    finish(outcome !== 'failure');
    await pending;
    assert.equal(f.anchors.length, outcome === 'success' ? 1 : 0, outcome);
    if (outcome === 'success') {
      assert.equal(f.anchors[0][0], 'group-round-11');
      assert.equal(f.anchors[0][1](), true);
      f.view.hide();
      assert.equal(f.anchors[0][1](), false);
    }
    f.scope.stop();
  }
});

test('group page restores its model scope and uses the shared keyboard padding and focus scroll', async () => {
  const f = fixture();
  f.lifecycle.onShow();
  assert.deepEqual(f.activations, [1]);
  f.view.showDetails.value = true;
  f.view.openModelSettings();
  assert.equal(f.view.showDetails.value, false);
  assert.equal(f.view.isModelSettingsOpen.value, true);
  assert.deepEqual(f.activations, [1, 1]);
  await f.state.generation(1);
  f.settings.selection.model = 'next-model';
  assert.equal(f.modelCalls[0].options.model, 'chosen-model');
  assert.notEqual(f.modelCalls[0].options, f.settings.selection);
  assert.equal(f.view.inputWrapperStyle.value.paddingBottom, undefined);
  f.scroll.keyboardHeight.value = 320;
  assert.equal(f.view.inputWrapperStyle.value.paddingBottom, '14rpx');
  f.view.onFocusChange(true);
  assert.equal(f.view.isFocused.value, true);
  assert.equal(f.focusScrolls.length, 1);
  f.scroll.keyboardHeight.value = 0;
  assert.equal(f.view.inputWrapperStyle.value.paddingBottom, undefined);
  f.view.isModelSettingsOpen.value = true;
  f.view.hide();
  assert.equal(f.view.isModelSettingsOpen.value, false);
  assert.equal(f.view.isFocused.value, false);
  f.scope.stop();
});
