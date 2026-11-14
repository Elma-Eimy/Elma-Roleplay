const test = require('node:test');
const assert = require('node:assert/strict');
const { createLoader } = require('./helpers/load-ts.cjs');

function fixture(platform, device = 'ios') {
  const mounts = [], unmounts = [], listeners = new Map(), removed = [];
  const vue = { ...require('vue'), onMounted: callback => mounts.push(callback), onUnmounted: callback => unmounts.push(callback) };
  const viewport = { height: 844, offsetTop: 0, scale: 1,
    addEventListener: (event, listener) => listeners.set(`viewport:${event}`, listener),
    removeEventListener: (event, listener) => removed.push([`viewport:${event}`, listener]),
  };
  const document = { activeElement: { tagName: 'TEXTAREA' }, documentElement: { clientHeight: 844 },
    addEventListener: (event, listener) => listeners.set(`document:${event}`, listener),
    removeEventListener: (event, listener) => removed.push([`document:${event}`, listener]),
  };
  const scroll = createLoader({ platform, mocks: { vue }, globals: {
    uni: { getSystemInfoSync: () => ({ platform: device }),
      onKeyboardHeightChange: callback => listeners.set('native', callback),
      offKeyboardHeightChange: callback => removed.push(['native', callback]),
    }, window: { visualViewport: viewport }, document,
    setTimeout: () => 1, clearTimeout() {},
  } })('composables/useChatScroll.ts').useChatScroll();
  mounts.forEach(callback => callback());
  return { scroll, listeners, viewport, document, removed, unmount: () => unmounts.forEach(callback => callback()) };
}

for (const [platform, device, expected] of [['APP-PLUS', 'ios', 300], ['APP-PLUS', 'android', 0], ['MP-WEIXIN', 'ios', 300]]) {
  test(`${platform}/${device}: keyboard height uses the native height field and Android does not add a second spacer`, () => {
    const f = fixture(platform, device);
    f.listeners.get('native')({ height: 300 });
    assert.equal(f.scroll.keyboardHeight.value, expected);
    f.listeners.get('native')({ height: 0 });
    assert.equal(f.scroll.keyboardHeight.value, 0);
    f.unmount();
    assert.equal(f.removed[0][1], f.listeners.get('native'));
  });
}

test('H5 adjusts for a covered visual viewport, avoids double spacing on resize and removes listeners', () => {
  const f = fixture('H5');
  f.viewport.height = 544;
  f.listeners.get('viewport:resize')();
  assert.equal(f.scroll.keyboardHeight.value, 300);
  f.document.documentElement.clientHeight = 544;
  f.listeners.get('viewport:resize')();
  assert.equal(f.scroll.keyboardHeight.value, 0);
  f.document.documentElement.clientHeight = 844;
  f.document.activeElement = null;
  f.listeners.get('document:focusout')();
  assert.equal(f.scroll.keyboardHeight.value, 0);
  f.unmount();
  assert.equal(f.removed.length, 4);
  for (const [event, listener] of f.removed) assert.equal(listener, f.listeners.get(event));
});
