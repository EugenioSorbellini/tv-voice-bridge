import assert from 'node:assert/strict';

// Without HA's root element, the card is still defined after the fallback timeout.
const elements = new Map();
globalThis.customElements = {
  define(name, type) { elements.set(name, type); },
  get(name) { return elements.get(name); },
  whenDefined: () => new Promise(() => {}),
};
const timers = [];
globalThis.setTimeout = (callback, ms) => timers.push({ callback, ms });
const { defineWhenReady, APP_READY_TIMEOUT_MS } = await import('../custom_components/tv_voice_bridge/frontend/define.mjs');
class Card {}
const defined = defineWhenReady('test-card', Card);
await new Promise(resolve => setImmediate(resolve));
assert.equal(elements.get('test-card'), undefined, 'Waits for the HA app first.');
assert.deepEqual(timers.map(timer => timer.ms), [APP_READY_TIMEOUT_MS]);
timers[0].callback();
await defined;
assert.equal(elements.get('test-card'), Card);
await defineWhenReady('test-card', class {});
assert.equal(elements.get('test-card'), Card, 'An existing definition is kept.');
console.log('Card definition: waits for the HA app, falls back after its timeout, keeps existing definitions.');
