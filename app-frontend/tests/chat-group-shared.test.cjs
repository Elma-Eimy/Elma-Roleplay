const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const ts = require('typescript'), vue = require('vue');
const { parse, compileScript } = require('@vue/compiler-sfc');
const { createLoader, sourceRoot } = require('./helpers/load-ts.cjs');
const chatBubbleContent = createLoader()('utils/chatBubbleContent.ts');
function component(name, props, mocks, uni = {}) {
  const filename = path.join(sourceRoot, 'components/chat', name + '.vue');
  const script = compileScript(parse(fs.readFileSync(filename, 'utf8')).descriptor, { id: name }).content;
  const code = ts.transpileModule(script, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS } }).outputText;
  const module = { exports: {} }, scope = vue.effectScope();
  const emitted = [];
  let exposed = {};
  const state = scope.run(() => { vm.runInNewContext(code, { module, exports: module.exports, uni, console, setTimeout, clearTimeout,
    require(id) { if (id === 'vue') return vue; if (id.endsWith('.vue')) return {}; if (id in mocks) return mocks[id]; throw new Error('Unexpected: ' + id); } });
    return module.exports.default.setup(props, {
      expose(value) { exposed = value || {}; },
      emit(event, ...args) { emitted.push({ event, args }); },
    }); });
  return { state, scope, emitted, get exposed() { return exposed; } };
}
const flush = async () => { for (let i = 0; i < 8; i++) await vue.nextTick(); };
test('shared bubble in group mode is pure and cannot emit or trigger candidate switches or audio playback', () => {
  const f = component('ChatBubble', { readOnly: true, message: { id: 9, role: 'assistant', status: 'done', content: 'hello', candidates: [{id:1},{id:2}] }, userNickname: '群聊用户', characterName: '群聊角色' }, {
    '@/utils/markdown': { renderChatMarkdown: s => s },
    '@/utils/chatDisplay': { createBoundedCache: () => new Map(), formatThoughtTitle: s => s, lastNonEmptyLine: s => s },
    '@/utils/chatBubbleContent': chatBubbleContent,
  });
  f.state.switchCandidateVersion(1); f.state.playTTS(); f.state.handleLongPress();
  assert.equal(f.emitted.length, 0);
  assert.equal(f.state.replacePlaceholders('{{char}}对{{user}}说'), '群聊角色对群聊用户说');
  f.scope.stop();

  const interactive = component('ChatBubble', { readOnly: false, message: { id: 9, role: 'assistant', status: 'done', content: 'hello', candidates: [{id:11},{id:12}], active_index: 0 }, userNickname: '单聊用户', characterName: '单聊角色' }, {
    '@/utils/markdown': { renderChatMarkdown: s => s },
    '@/utils/chatDisplay': { createBoundedCache: () => new Map(), formatThoughtTitle: s => s, lastNonEmptyLine: s => s },
    '@/utils/chatBubbleContent': chatBubbleContent,
  });
  interactive.state.switchCandidateVersion(1); interactive.state.playTTS();
  assert.deepEqual(JSON.parse(JSON.stringify(interactive.emitted)), [
    { event: 'switch-candidate', args: [{ messageId: 9, candidateId: 12 }] },
    { event: 'play-tts', args: [{ id: 9, role: 'assistant', status: 'done', content: 'hello', candidates: [{id:11},{id:12}], active_index: 0 }] },
  ]);
  interactive.scope.stop();
});
test('shared memory browser scopes group requests and rejects single-chat writes and late member results', async () => {
  const requests = [], singleCalls = [];
  const props = vue.reactive({ isOpen:true, sessionId:42, groupPersonaId:1 });
  const f = component('MemoryManagerModal', props, {
    '@/api/groupSessions': { getGroupMemberMemories: (...args) => new Promise(resolve => requests.push({args, resolve})) },
    '@/api/memories': Object.fromEntries(['getSessionMemories','createSessionMemory','updateSessionMemory','deleteSessionMemory'].map(name => [name, (...args) => { singleCalls.push(args); }])),
  });
  assert.deepEqual(requests[0].args.slice(0,2), [42,1]);
  props.groupPersonaId = 2; await flush();
  requests[1].resolve({items:[{id:22,content:'member2'}],facets:{},has_more:false,offset:0}); await flush();
  requests[0].resolve({items:[{id:11,content:'member1 private'}],facets:{},has_more:false,offset:0}); await flush();
  assert.equal(f.state.memories.value[0].id,22);
  await f.state.saveInlineEdit(22); f.state.deleteMemory(22); await f.state.addMemory();
  assert.equal(singleCalls.length,0);
  props.isOpen = false; await flush(); f.scope.stop();
});

test('shared drawer opens the selected group profile and ignores callbacks from an older member', async () => {
  const navigations = [], toasts = [];
  const member = id => ({ name: 'member-' + id, character: {id}, affection:18, mood:'平静', cognition:null });
  const props = vue.reactive({ isOpen:true, sessionId:42, profile:member(11) });
  const f = component('ChatDrawer', props, {
    '@/store/chatSettingsStore': {useChatSettingsStore: () => ({})},
    '@/api/config': {getBaseUrl: () => 'isolated'}, '@/api/characters': {getAvatarUrl: s => s},
  }, {getSystemInfoSync: () => ({platform:'test'}),navigateTo: value => navigations.push(value),showToast: value => toasts.push(value)});
  f.state.openCharacterProfile(); f.state.openCharacterProfile();
  assert.equal(navigations.length,1); assert.equal(navigations[0].url,'/pages/character/detail?id=11');
  props.profile = member(12); await flush(); f.state.openCharacterProfile();
  assert.equal(navigations[1].url,'/pages/character/detail?id=12');
  navigations[0].fail(); navigations[0].complete();
  assert.equal(toasts.length,0); assert.equal(f.state.isOpeningProfile.value,true);
  navigations[1].complete(); assert.equal(f.state.isOpeningProfile.value,false);
  f.scope.stop();
});

test('shared scroll shell measures viewport and emits normalized scroll metrics', () => {
  let measuredSelector = null;
  const f = component('ChatScrollShell', { scrollTop: 0, scrollIntoViewId: '', scrollWithAnimation: false }, {}, {
    createSelectorQuery: () => ({
      in() { return this; },
      select(selector) { measuredSelector = selector; return this; },
      boundingClientRect(cb) { cb({ height: 640 }); return this; },
      exec() {},
    }),
  });
  f.exposed.measureViewport();
  assert.equal(measuredSelector, '.chat-scroll-area');
  f.state.onScroll({ detail: { scrollTop: 120, scrollHeight: 1400 } });
  assert.deepEqual(JSON.parse(JSON.stringify(f.emitted)), [{ event: 'scroll-metrics', args: [{ scrollTop: 120, scrollHeight: 1400, viewportHeight: 640 }] }]);
  f.state.onScroll({ detail: {} });
  assert.equal(f.emitted.length, 1);
  f.scope.stop();
});

test('single chat and group detail share chatTheme.css, ChatScrollShell, ChatBubble, and ChatActionBar without removed shells or single-chat chat.css', () => {
  const singleCss = fs.readFileSync(path.join(sourceRoot, 'pages/chat/chat.css'), 'utf8');
  const singlePage = fs.readFileSync(path.join(sourceRoot, 'pages/chat/chat.vue'), 'utf8');
  const groupDetail = fs.readFileSync(path.join(sourceRoot, 'pages/group/detail.vue'), 'utf8');
  const messageList = fs.readFileSync(path.join(sourceRoot, 'components/chat/ChatMessageList.vue'), 'utf8');
  const utterances = fs.readFileSync(path.join(sourceRoot, 'components/chat/GroupUtterances.vue'), 'utf8');
  assert.match(singleCss, /@import\s+["']\.\.\/\.\.\/components\/chat\/chatTheme\.css["']/);
  assert.match(groupDetail, /@import\s+["']\.\.\/\.\.\/components\/chat\/chatTheme\.css["']/);
  assert.doesNotMatch(groupDetail, /@import\s+["']\.\.\/chat\/chat\.css["']/);
  assert.doesNotMatch(groupDetail, /chatDrawer\.css/);
  assert.match(singlePage, /<SingleChatDrawer\b/);
  assert.match(groupDetail, /<ChatScrollShell\b/);
  assert.match(groupDetail, /<ChatBubble\b/);
  assert.match(groupDetail, /<ChatActionBar\b/);
  assert.match(groupDetail, /<GroupChatDrawer\b/);
  assert.match(groupDetail, /<GroupCandidateModal\b/);
  assert.match(utterances, /<ChatBubble\b/);
  assert.match(messageList, /<ChatScrollShell\b/);
  assert.doesNotMatch(groupDetail, /ChatTranscriptMessage|ChatEmptyState|GroupMemberStates/);
  assert.doesNotMatch(messageList, /ChatEmptyState/);
});

test('group candidate modal resolves selected status, candidate labels and preview portraits', () => {
  const f = component('GroupCandidateModal', {
    isOpen: true,
    group: { session_id: 1, title: '群聊', user_nickname: '旅人', shared_setting: null, created_at: '', updated_at: '', can_generate: true, members: [] },
    current: { group_revision: 1, latest: { round_id: 5, candidate_id: 22, candidate_revision: 1, confirmed: false }, active_operation: null, capabilities: { can_send: true, can_regenerate: true, can_select: true, can_discard: true } },
    candidateRoundId: 5,
    candidates: [{ candidate_id: 21, version: 1, revision: 1, status: 'awaiting_confirmation', checkpoint: 'done', protocol_version: 2, selected: false, finish_reason: 'wait_user', error_code: null, can_select: true, can_resume: false }],
    loadingCandidates: false,
    candidatesError: '',
    hasMoreCandidates: false,
    preview: {
      can_generate: true,
      round: { round_id: 5, round_index: 1, user_content: 'hello', selected_candidate_id: 22, confirmed: false, discarded_at: null, created_at: '' },
      candidate: { candidate_id: 21, version: 1, revision: 1, status: 'failed', checkpoint: 'role_generation', protocol_version: 2, selected: false, finish_reason: null, error_code: 'resource_paused', can_select: false, can_resume: true },
      current: { group_revision: 1, latest: null, active_operation: null, capabilities: { can_send: true, can_regenerate: true, can_select: true, can_discard: true } },
      utterances: [],
      state_preview: { candidate_id: 21, members: [{ persona_id: 1, affection_score: 10, current_mood: '开心', role_state: { scene: '', characters: {} }, portrait: { persona_id: 1, portrait_id: 9, image_path: 'p9.png' } }] },
    },
    loadingPreview: false,
    previewError: '',
    submitting: false,
    deleting: false,
    locked: false,
    canGenerate: true,
  }, {});
  assert.equal(f.state.isSelected(22), true);
  assert.equal(f.state.isSelected(21), false);
  assert.equal(f.state.candidateStatus('failed', 'resource_paused'), '已暂停');
  assert.equal(f.state.candidateStatus('failed', 'timeout'), '未完成');
  assert.equal(f.state.candidateStatus('awaiting_confirmation', null), '完整结果');
  assert.deepEqual(JSON.parse(JSON.stringify(f.state.previewPortraits.value)), [{ persona_id: 1, portrait_id: 9, image_path: 'p9.png' }]);
  f.scope.stop();
});

test('group utterances fold avatar and name only for consecutive utterances from the same speaker', () => {
  const f = component('GroupUtterances', {
    utterances: [
      { item_id: 1, speaker_persona_id: 10, speaker_name: '甲', content: '一' },
      { item_id: 2, speaker_persona_id: 10, speaker_name: '甲', content: '二' },
      { item_id: 3, speaker_persona_id: 20, speaker_name: '乙', content: '三' },
      { item_id: 4, speaker_persona_id: 10, speaker_name: '甲', content: '四' },
    ],
    members: [
      { persona_id: 10, slot: 1, character: { avatar_path: 'a.png' } },
      { persona_id: 20, slot: 2, character: { avatar_path: 'b.png' } },
    ],
  }, {
    '@/api/characters': { getAvatarUrl: path => path },
  });
  assert.equal(f.state.shouldShowSpeaker(0), true);
  assert.equal(f.state.shouldShowSpeaker(1), false);
  assert.equal(f.state.shouldShowSpeaker(2), true);
  assert.equal(f.state.shouldShowSpeaker(3), true);
  f.scope.stop();
});

test('memory item card formats labels, source ranges, and propagates inline edits', () => {
  const f = component('MemoryItemCard', {
    item: {
      id: 7,
      content: '喜欢下雨天散步',
      memory_type: 'Preference',
      importance_score: 0.8,
      is_local: true,
      source_start_message_id: 12,
      source_message_id: 15,
    },
    isEditing: true,
    editingContent: '原始内容',
    editable: true,
  }, {});
  assert.equal(f.state.getMemoryTypeLabel('Preference'), '偏好');
  assert.equal(f.state.getMemoryTypeLabel('unknown_type'), '其他');
  assert.equal(f.state.formatMemorySource({ source_start_message_id: 12, source_message_id: 15 }), '消息 #12–#15');
  assert.equal(f.state.formatMemorySource({ source_message_id: 15 }), '消息 #15');
  f.state.draftContent.value = '修改后的记忆';
  assert.deepEqual(JSON.parse(JSON.stringify(f.emitted)), [
    { event: 'update:editing-content', args: ['修改后的记忆'] },
  ]);
  f.scope.stop();
});
