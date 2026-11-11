const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const ts = require('typescript'), vue = require('vue');
const { parse, compileScript } = require('@vue/compiler-sfc');
const { sourceRoot } = require('./helpers/load-ts.cjs');
function component(name, props, mocks, uni = {}) {
  const filename = path.join(sourceRoot, 'components/chat', name + '.vue');
  const script = compileScript(parse(fs.readFileSync(filename, 'utf8')).descriptor, { id: name }).content;
  const code = ts.transpileModule(script, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS } }).outputText;
  const module = { exports: {} }, scope = vue.effectScope();
  const state = scope.run(() => { vm.runInNewContext(code, { module, exports: module.exports, uni, console, setTimeout, clearTimeout,
    require(id) { if (id === 'vue') return vue; if (id.endsWith('.vue')) return {}; if (id in mocks) return mocks[id]; throw new Error('Unexpected: ' + id); } });
    return module.exports.default.setup(props, { expose() {}, emit() {} }); });
  return { state, scope };
}
const flush = async () => { for (let i = 0; i < 8; i++) await vue.nextTick(); };
test('shared bubble in group mode cannot write single-chat candidates or play single-chat audio', () => {
  let actions = 0;
  const f = component('ChatBubble', { readOnly: true, message: { id: 9, role: 'assistant', status: 'done', content: 'hello', candidates: [{id:1},{id:2}] }, userNickname: '群聊用户', characterName: '群聊角色' }, {
    '@/store/chatStore': { useChatStore: () => ({ isLoading: false, switchActiveCandidate() { actions++; } }) },
    '@/store/personaStore': { usePersonaStore: () => ({ userNickname: '单聊用户' }) },
    '@/composables/useAudioPlayer': { useAudioPlayer: () => ({ activeAudioMessageId: vue.ref(null), playMessageTTS() { actions++; } }) },
    '@/utils/markdown': { renderChatMarkdown: s => s },
    '@/utils/chatDisplay': { createBoundedCache: () => new Map(), formatThoughtTitle: s => s, lastNonEmptyLine: s => s },
  });
  f.state.switchCandidateVersion(1); f.state.playTTS(); f.state.handleLongPress();
  assert.equal(actions, 0);
  assert.equal(f.state.replacePlaceholders('{{char}}对{{user}}说'), '群聊角色对群聊用户说');
  f.scope.stop();
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
  const props = vue.reactive({ isOpen:true, sessionId:42, memberContext:member(11) });
  const f = component('ChatDrawer', props, {
    '@/store/chatStore': {useChatStore: () => ({messages:[],isLoading:false})},
    '@/store/personaStore': {usePersonaStore: () => ({userNickname:'single',activeCharacter:{id:99}})},
    '@/store/chatSettingsStore': {useChatSettingsStore: () => ({})},
    '@/api/config': {getBaseUrl: () => 'isolated'}, '@/api/characters': {getAvatarUrl: s => s}, '@/api/sessions': {},
  }, {getSystemInfoSync: () => ({platform:'test'}),navigateTo: value => navigations.push(value),showToast: value => toasts.push(value)});
  f.state.openCharacterProfile(); f.state.openCharacterProfile();
  assert.equal(navigations.length,1); assert.equal(navigations[0].url,'/pages/character/detail?id=11');
  props.memberContext = member(12); await flush(); f.state.openCharacterProfile();
  assert.equal(navigations[1].url,'/pages/character/detail?id=12');
  navigations[0].fail(); navigations[0].complete();
  assert.equal(toasts.length,0); assert.equal(f.state.isOpeningProfile.value,true);
  navigations[1].complete(); assert.equal(f.state.isOpeningProfile.value,false);
  f.scope.stop();
});
