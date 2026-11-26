const test = require('node:test');
const assert = require('node:assert/strict');
const { createLoader } = require('./helpers/load-ts.cjs');

const loadChatRequest = () => createLoader()('utils/chatRequest.ts');
const loadChatBubbleContent = () => createLoader()('utils/chatBubbleContent.ts');

test('findLatestPersistedMessageId picks max id across messages and candidates', () => {
  const { findLatestPersistedMessageId } = loadChatRequest();
  assert.equal(findLatestPersistedMessageId([]), 0);
  assert.equal(
    findLatestPersistedMessageId([
      { id: -1, candidates: [] },
      { id: 12, candidates: [{ id: 12 }, { id: 19 }] },
      { id: 15 },
    ]),
    19
  );
});

test('buildChatRequest merges generation override, normalized sampling params, and regenerate flag', () => {
  const { buildChatRequest } = loadChatRequest();
  const payload = buildChatRequest(
    42,
    '你好',
    { generation_mode: 'preset', preset_id: 7 },
    '旅人',
    { temperature: 0.7, top_p: null, presence_penalty: 0.1, frequency_penalty: undefined, repetition_penalty: 1.05 },
    true
  );
  assert.deepStrictEqual({ ...payload }, {
    session_id: 42,
    user_message: '你好',
    generation_mode: 'preset',
    preset_id: 7,
    user_nickname: '旅人',
    temperature: 0.7,
    top_p: undefined,
    presence_penalty: 0.1,
    frequency_penalty: undefined,
    repetition_penalty: 1.05,
    is_regenerate: true,
  });

  const normalPayload = buildChatRequest(42, 'hi', { generation_mode: 'default' }, '旅人', {});
  assert.equal('is_regenerate' in normalPayload, false);
});

test('applyCandidateSnapshot syncs candidate fields and optional clientId/created_at', () => {
  const { applyCandidateSnapshot } = loadChatRequest();
  const target = {
    id: 100,
    content: 'old',
    emotion_tag: null,
    affection_change: 0,
    created_at: '2026-01-01T00:00:00Z',
    audio_path: 'old.mp3',
    clientId: 'msg-100',
    candidates: [{ id: 100 }, { id: 101 }],
    active_index: 0,
  };
  applyCandidateSnapshot(
    target,
    {
      id: 101,
      content: 'new',
      emotion_tag: 'happy',
      affection_change: 2,
      created_at: '2026-01-01T00:01:00Z',
      audio_path: '',
    },
    { syncClientId: true, syncCreatedAt: true }
  );
  assert.equal(target.id, 101);
  assert.equal(target.content, 'new');
  assert.equal(target.emotion_tag, 'happy');
  assert.equal(target.affection_change, 2);
  assert.equal(target.audio_path, null);
  assert.equal(target.created_at, '2026-01-01T00:01:00Z');
  assert.equal(target.clientId, 'msg-101');
  assert.equal(target.active_index, 1);
});

test('createAppStreamRequest constructs request descriptor with optional userMessageTempId', () => {
  const { createAppStreamRequest } = loadChatRequest();
  const req = createAppStreamRequest({
    placeholderId: 'temp-ai-1',
    userMessageTempId: 'temp-user-1',
    params: { session_id: 1, user_message: 'hi' },
    baseUrl: 'http://127.0.0.1:8000',
    apiKey: 'secret',
  });
  assert.match(req.requestId, /^req-/);
  assert.equal(req.placeholderId, 'temp-ai-1');
  assert.equal(req.userMessageTempId, 'temp-user-1');
  assert.equal(req.baseUrl, 'http://127.0.0.1:8000');
  assert.equal(req.apiKey, 'secret');
});

test('parseBubbleContent strips status/thought tags, replaces placeholders, and prefers reasoning_content', () => {
  const { parseBubbleContent } = loadChatBubbleContent();

  const fromTags = parseBubbleContent({
    content: '<thought>{{char}}在思考{{user}}</thought><status mood="happy" />你好，{{user}}！',
    isUser: false,
    characterName: '艾琳',
    userNickname: '阿明',
  });
  assert.deepStrictEqual({ ...fromTags }, {
    thought: '艾琳在思考阿明',
    reply: '你好，阿明！',
  });

  const fromReasoning = parseBubbleContent({
    content: '<thought>旧标签</thought>正式回复给{{user}}',
    reasoningContent: '独立推理：回应{{user}}',
    isUser: false,
    characterName: '艾琳',
    userNickname: '阿明',
  });
  assert.deepStrictEqual({ ...fromReasoning }, {
    thought: '独立推理：回应阿明',
    reply: '旧标签正式回复给阿明',
  });

  const userMsg = parseBubbleContent({
    content: '<thought>不应隐藏</thought><status x="1"/>{{char}}你好',
    isUser: true,
    characterName: '艾琳',
    userNickname: '阿明',
  });
  assert.deepStrictEqual({ ...userMsg }, {
    thought: '',
    reply: '<thought>不应隐藏</thought>艾琳你好',
  });
});
