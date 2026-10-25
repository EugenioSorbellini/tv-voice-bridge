// Voice card (tv-voice-card.js) with stubbed DOM, microphone, AudioContext, worklet and
// Home Assistant connection. Each block below is one scenario; the stub server answers
// start, progress and stop like the bridge, and records every JSON call and binary frame.
import assert from 'node:assert/strict';
import { mock } from 'node:test';

class Element {
  constructor() { this.classList = { toggle() {} }; this.listeners = {}; this.style = {}; }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  setPointerCapture(id) { this.capturedPointer = id; }
}
class HTMLElement {
  setAttribute(name, value) { this[name] = value; }
  attachShadow() {
    const elements = {};
    this.shadowRoot = { querySelector(name) { return elements[name] ||= new Element(); } };
  }
  toggleAttribute() {}
}
globalThis.HTMLElement = HTMLElement;
globalThis.document = { hidden: false, addEventListener() {}, removeEventListener() {} };
globalThis.window = { isSecureContext: true };
const registry = () => {
  const elements = new Map();
  const waiting = new Map();
  return {
    define(name, type) {
      if (elements.has(name)) throw new Error(`${name} already defined`);
      elements.set(name, type);
      waiting.get(name)?.forEach(resolve => resolve(type));
    },
    get(name) { return elements.get(name); },
    whenDefined(name) {
      return elements.has(name) ? Promise.resolve(elements.get(name))
        : new Promise(resolve => waiting.set(name, [...(waiting.get(name) || []), resolve]));
    },
  };
};
// Registration into the registry HA really uses.
// Loads the card with a native registry, then swaps in a second registry, as HA's
// scoped-registry polyfill does, before HA's root element is defined.
// Verifies: nothing is defined before the HA app; the card and its editor land in the
// registry that is current when home-assistant is defined, not in the original native
// one; the card exposes stylingVersion 1.
const native = registry();
globalThis.customElements = native;
// Hold define.mjs's fallback timer; tests/test_tv_voice_define.mjs covers it.
const realSetTimeout = globalThis.setTimeout;
globalThis.setTimeout = () => 0;
const { TVVoiceCard: Card } = await import('../custom_components/tv_voice_bridge/frontend/tv-voice-card.js');
globalThis.setTimeout = realSetTimeout;
const { localize, languages } = await import('../custom_components/tv_voice_bridge/frontend/localize.mjs');
await new Promise(resolve => setImmediate(resolve));
assert.equal(native.get('tv-voice-card'), undefined, 'Nothing is defined before the HA app.');
const polyfill = registry();
globalThis.customElements = polyfill;
native.define('home-assistant', class {});
polyfill.define('home-assistant', class {});
await new Promise(resolve => setImmediate(resolve));
assert.equal(polyfill.get('tv-voice-card'), Card, 'The card lands in the registry the app installed.');
assert.ok(polyfill.get('tv-voice-card-editor'));
assert.equal(native.get('tv-voice-card'), undefined);
assert.equal(Card.stylingVersion, 1);
// Initial state.
// Verifies: a freshly configured card is idle and its status uses the hint part.
{
  const card = new Card();
  card.setConfig({});
  assert.equal(card['data-state'], 'idle');
  assert.equal(card._status.part, 'status hint');
}
let media;
function makeMedia() {
  const stream = { stopped: false, getTracks() { return [{ stop() { stream.stopped = true; } }]; } };
  return media = stream;
}
let context;
let processor;
class AudioContext {
  constructor() { context = this; this.closed = false; this.audioWorklet = { addModule: async () => {} }; }
  async resume() {}
  async close() { this.closed = true; }
  node() { return { connect() {}, disconnect() {} }; }
  createMediaStreamSource() { return this.node(); }
  createGain() { return { ...this.node(), gain: {} }; }
}
class Worklet {
  constructor() {
    processor = this;
    this.port = { postMessage: message => {
      if (message.type === 'stop') queueMicrotask(() => this.port.onmessage?.({ data: { type: 'stopped' } }));
    } };
  }
  connect() {}
  disconnect() {}
  audio(length = 8192) {
    const bytes = new Uint8Array(length).fill(10);
    this.port.onmessage?.({ data: { type: 'audio', bytes: bytes.buffer, peak: .1 } });
  }
}
window.AudioContext = AudioContext;
window.AudioWorkletNode = Worklet;
let getUserMedia = async () => makeMedia();
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { mediaDevices: { getUserMedia: (...args) => getUserMedia(...args) } } });
const token = '0123456789abcdef0123456789abcdef';
const session = { session_id: token, binary_handler_id: 3, chunk_bytes: 8192, max_seconds: 15, sample_rate: 16000, protocol_version: 2 };
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
const press = (card, name, event = {}) => card._button.listeners[name]({ preventDefault() {}, ...event });
function create({ start = Promise.resolve(session), failProgress = false, stall = '', language = 'it' } = {}) {
  const calls = [];
  const frames = [];
  const connection = { addEventListener() {}, removeEventListener() {}, socket: { readyState: 1, send: frame => frames.push(new Uint8Array(frame)) } };
  const card = new Card();
  let cancelled = false;
  card.setConfig({ entity: 'remote.test_tv' });
  card.hass = { connection, locale: { language }, callWS: async message => {
    calls.push(message);
    if (message.type.endsWith('/cancel')) cancelled = true;
    if (stall && message.type.endsWith('/' + stall)) return new Promise(() => {});
    if (message.type.endsWith('/start')) return start;
    if (message.type.endsWith('/stop') && cancelled) throw { code: 'session_ended' };
    if (message.type.endsWith('/progress')) {
      if (failProgress) throw { code: 'delivery_failed' };
      return { received_bytes: frames.reduce((sum, frame) => sum + frame.length - 21, 0) };
    }
    return { forwarded_bytes: frames.reduce((sum, frame) => sum + frame.length - 21, 0) };
  } };
  return { card, calls, frames };
}

// Release before the TV is ready.
// Presses with pointer 7, captures one 8192-byte chunk while start is still pending,
// ignores a pointerup from another pointer, then releases; only afterwards does start
// succeed.
// Verifies: data-state, aria-pressed and CSS parts follow idle -> recording -> sending
// -> idle; the pointer is captured; microphone and audio context close on release;
// stray lostpointercapture and click events don't restart recording; the single frame
// carries handler id 3, the session token and sequence 0 followed by exactly the
// captured audio; no JSON message contains audio; stop is sent with cancel: false and
// the success status is shown.
{
  let ready;
  const { card, calls, frames } = create({ start: new Promise(resolve => { ready = resolve; }) });
  press(card, 'pointerdown', { button: 0, pointerId: 7 });
  await flush();
  assert.equal(card._state, 'recording');
  assert.equal(card['data-state'], 'recording');
  assert.equal(card._button['aria-pressed'], String(true));
  assert.equal(card._status.part, 'status feedback');
  assert.equal(card._button.capturedPointer, 7);
  processor.audio();
  const captured = card._buffer.slice(0, card._capturedBytes);
  assert.equal(frames.length, 0);
  press(card, 'pointerup', { pointerId: 99 });
  assert.equal(card._state, 'recording');
  press(card, 'pointerup', { pointerId: 7 });
  await flush();
  assert.ok(media.stopped && context.closed);
  assert.equal(card._state, 'sending');
  assert.equal(card['data-state'], 'sending');
  press(card, 'lostpointercapture', { pointerId: 7 });
  press(card, 'click', { detail: 1 });
  ready(session);
  await card._sending;
  assert.equal(card._state, 'idle');
  assert.equal(card['data-state'], 'idle');
  assert.equal(card._button['aria-pressed'], String(false));
  assert.equal(calls.find(call => call.type.endsWith('/start')).remote_entity, 'remote.test_tv');
  assert.deepEqual(frames[0].subarray(21), captured);
  assert.equal(frames[0][0], 3);
  assert.equal(Buffer.from(frames[0].subarray(1, 17)).toString('hex'), token);
  assert.equal(new DataView(frames[0].buffer).getUint32(17, true), 0);
  assert.ok(calls.every(call => !('audio' in call)), 'JSON control messages never contain audio');
  assert.equal(calls.at(-1).cancel, false);
  assert.match(card._status.textContent, /Audio inviato/);
}

// Microphone permission.
// Releases while the permission prompt is still open, then grants it; afterwards the
// browser denies permission (NotAllowedError).
// Verifies: a late grant after release stops the stream and closes the audio context
// without contacting Home Assistant; a denial shows the localized "microphone not
// allowed" message.
{
  let permission;
  getUserMedia = () => new Promise(resolve => { permission = resolve; });
  const { card, calls } = create();
  const start = card._start();
  await card._stop();
  permission(makeMedia());
  await start;
  assert.ok(media.stopped && context.closed);
  assert.equal(calls.length, 0);
  getUserMedia = async () => { throw Object.assign(new Error(), { name: 'NotAllowedError' }); };
  await card._start();
  assert.match(card._status.textContent, /Microfono non consentito/);
  getUserMedia = async () => makeMedia();
}

// Full-length recording.
// Captures 59 chunks of 8192 bytes, more than 15 seconds, then releases.
// Verifies: the card keeps exactly 480000 bytes and uploads all of them in 59 frames
// (58 full and a 4864-byte tail), then shows the success status. The four-frame upload
// window is checked in the streaming and cancellation blocks, not here.
{
  const { card, frames } = create();
  await card._start();
  for (let i = 0; i < 59; i++) processor.audio();
  assert.equal(card._capturedBytes, 480000);
  await card._stop();
  assert.equal(frames.reduce((sum, frame) => sum + frame.length - 21, 0), 480000);
  assert.equal(frames.length, 59);
  assert.match(card._status.textContent, /Audio inviato/);
}

// 15-second cap on the main thread.
// With fake timers and start still pending, records one chunk and advances time.
// Verifies: the card is still recording at 14.999 s and stops at 15 s, closing the
// microphone and audio context, even though the TV hasn't answered start yet.
{
  mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] });
  let ready;
  const { card } = create({ start: new Promise(resolve => { ready = resolve; }) });
  await card._start(); processor.audio();
  mock.timers.tick(14999); assert.equal(card._state, 'recording');
  mock.timers.tick(1); await flush(); assert.equal(card._state, 'sending');
  assert.ok(media.stopped && context.closed);
  ready(session); await card._sending;
  mock.timers.reset();
}

// Cancel while start is pending.
// Records, releases and then cancels before start answers; start succeeds afterwards.
// Verifies: a cancel command is sent; after the late start no frame is uploaded; the
// card returns to idle and releases the recording buffer.
{
  let ready;
  const { card, calls, frames } = create({ start: new Promise(resolve => { ready = resolve; }) });
  await card._start(); processor.audio();
  const sending = card._stop();
  await card._stop(true);
  assert.ok(calls.some(call => call.type.endsWith('/cancel')));
  ready(session); await sending; await flush();
  assert.equal(card._state, 'idle');
  assert.equal(frames.length, 0);
  assert.equal(card._buffer, null, 'recording released');
}

// Server error codes.
// Makes progress fail with delivery_failed, then maps an unknown code with a server
// message.
// Verifies: delivery_failed shows the localized "not delivered" message; an unknown
// code falls back to errors.unavailable, the server's text is never used, and only the
// code is logged.
{
  const { card } = create({ failProgress: true, language: 'en' });
  const warn = mock.method(console, 'warn', () => {});
  await card._start(); processor.audio(); await card._stop();
  assert.match(card._status.textContent, /not delivered/);
  assert.equal(card._errorKey({ code: 'unknown_code', message: 'PRIVATE SERVER DETAIL' }), 'errors.unavailable');
  assert.deepEqual(warn.mock.calls.map(call => call.arguments), [['tv-voice-card: unmapped error', 'unknown_code']]);
  warn.mock.restore();
}

// Unmapped failures.
// The microphone fails with OverconstrainedError (with private text), then with
// NotReadableError; an error code containing a space is mapped too.
// Verifies: the unmapped error shows the generic message followed by its name, never
// its text, and logs the name with console.warn; NotReadableError shows the "in use by
// another app" message; a code with a space falls back to errors.unavailable with no
// name shown; Home Assistant is never contacted.
{
  const { card, calls } = create({ language: 'en' });
  const warn = mock.method(console, 'warn', () => {});
  getUserMedia = async () => { throw Object.assign(new Error('PRIVATE DEVICE DETAIL'), { name: 'OverconstrainedError' }); };
  await card._start();
  assert.match(card._status.textContent, /Cannot connect to TV voice\. .*\(OverconstrainedError\)$/);
  assert.doesNotMatch(card._status.textContent, /PRIVATE/);
  assert.equal(warn.mock.calls[0].arguments[1], 'OverconstrainedError');
  getUserMedia = async () => { throw Object.assign(new Error(), { name: 'NotReadableError' }); };
  await card._start();
  assert.match(card._status.textContent, /in use by another app/);
  assert.equal(card._errorKey({ code: 'not found', message: 'x' }), 'errors.unavailable');
  assert.equal(card._errorDetail, '', 'identifiers with spaces are not shown');
  assert.equal(calls.length, 0);
  warn.mock.restore();
  getUserMedia = async () => makeMedia();
}

// Request timeouts while the socket stays open.
// For each of start, progress and stop, the stub never answers that request; fake
// timers advance 20 s for start and 10 s for the others.
// Verifies: the card returns to idle with the button enabled, releases the buffer,
// closes the microphone and audio context, shows "timed out" and sends cancel; when
// start finally answers late, no session is adopted and no frame is uploaded.
for (const phase of ['start', 'progress', 'stop']) {
  mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] });
  let ready;
  const { card, calls, frames } = create({ language: 'en',
    ...(phase === 'start' ? { start: new Promise(resolve => { ready = resolve; }) } : { stall: phase }),
  });
  await card._start(); await flush(); processor.audio();
  const sending = card._stop(); await flush();
  assert.equal(card._state, 'sending');
  mock.timers.tick(phase === 'start' ? 20000 : 10000);
  await flush(); await sending; await card._sending;
  assert.equal(card._state, 'idle');
  assert.equal(card._button.disabled, false);
  assert.equal(card._buffer, null, 'recording released');
  assert.ok(media.stopped && context.closed);
  assert.match(card._status.textContent, /timed out/);
  assert.ok(calls.some(call => call.type.endsWith('/cancel')));
  if (ready) {
    ready(session); await flush();
    assert.equal(card._token, null);
    assert.equal(frames.length, 0, 'a late start cannot upload discarded audio');
  }
  mock.timers.reset();
}

// Cancel without a reply.
// Cancels a recording while the cancel command never answers, once plainly and once
// with the capture_failed error as the reason.
// Verifies: the card returns to idle and releases the buffer without waiting; it shows
// the given reason (or "cancelled"); exactly one cancel and no stop is sent.
for (const message of ['', 'errors.capture_failed']) {
  const { card, calls } = create({ language: 'en', stall: 'cancel' });
  await card._start(); await flush(); processor.audio();
  await card._stop(true, message, Boolean(message));
  assert.equal(card._state, 'idle');
  assert.equal(card._buffer, null, 'recording released');
  assert.equal(card._message, message || 'cancelled');
  assert.equal(calls.filter(call => call.type.endsWith('/cancel')).length, 1);
  assert.ok(!calls.some(call => call.type.endsWith('/stop')));
}
// Cancel during upload.
// Holds every progress acknowledgement, captures six chunks and releases, then cancels
// (cancel never answers) and finally delivers the held acknowledgements.
// Verifies: only four frames are in flight before acknowledgements; cancel returns the
// card to idle and releases the buffer; late acknowledgements don't resume the upload;
// the status shows "cancelled".
{
  const acknowledgements = [];
  const { card, frames } = create({ language: 'en' });
  const original = card._hass.callWS;
  card._hass.callWS = message => {
    if (message.type.endsWith('/progress')) {
      return new Promise(resolve => acknowledgements.push(() => resolve({ received_bytes: message.sequence * 8192 })));
    }
    if (message.type.endsWith('/cancel')) return new Promise(() => {});
    return original(message);
  };
  await card._start(); await flush();
  for (let i = 0; i < 6; i++) processor.audio();
  const sending = card._stop(); await flush();
  assert.equal(frames.length, 4, 'outstanding frames are bounded by the upload window');
  await card._stop(true); await sending;
  assert.equal(card._state, 'idle');
  assert.equal(card._buffer, null, 'recording released');
  acknowledgements.forEach(acknowledge => acknowledge()); await flush();
  assert.equal(frames.length, 4, 'late acknowledgements cannot resume a cancelled upload');
  assert.equal(card._message, 'cancelled');
}

// Streaming while recording.
// Holds progress acknowledgements and captures two half chunks, then five full chunks,
// acknowledging one; then releases and acknowledges the rest.
// Verifies: half a chunk isn't sent; a full chunk is sent while still recording; at most
// four frames are unacknowledged and one acknowledgement lets the next frame go; stop
// isn't sent while recording; in the end six frames with sequences 0-5 carry 6 x 8192
// bytes, stop's expected_bytes matches, and the success status shows.
{
  const acknowledgements = [];
  const { card, calls, frames } = create({ language: 'en' });
  const original = card._hass.callWS;
  card._hass.callWS = message => {
    if (message.type.endsWith('/progress')) {
      return new Promise(resolve => acknowledgements.push(() => resolve({ received_bytes: message.sequence * 8192 })));
    }
    return original(message);
  };
  await card._start(); await flush();
  processor.audio(4096); await flush();
  assert.equal(frames.length, 0, 'partial chunks wait for more audio');
  processor.audio(4096); await flush();
  assert.equal(card._state, 'recording');
  assert.equal(frames.length, 1, 'a full chunk is sent before release');
  for (let i = 0; i < 5; i++) processor.audio();
  await flush();
  assert.equal(frames.length, 4);
  acknowledgements.shift()(); await flush();
  assert.equal(frames.length, 5);
  assert.ok(!calls.some(call => call.type.endsWith('/stop')), 'nothing is submitted while recording');
  const sending = card._stop();
  for (let i = 0; i < 10; i++) { acknowledgements.splice(0).forEach(acknowledge => acknowledge()); await flush(); }
  await sending;
  assert.equal(frames.length, 6);
  assert.deepEqual(frames.map(frame => new DataView(frame.buffer).getUint32(17, true)), [0, 1, 2, 3, 4, 5]);
  assert.equal(frames.reduce((sum, frame) => sum + frame.length - 21, 0), 6 * 8192);
  assert.equal(calls.at(-1).expected_bytes, 6 * 8192);
  assert.match(card._status.textContent, /sent/i);
}

// Upload failure while recording.
// Makes progress fail with delivery_failed and captures one chunk.
// Verifies: recording stops without a release, the microphone and audio context close,
// the card shows "not delivered" and sends cancel.
{
  const { card, calls } = create({ language: 'en', failProgress: true });
  await card._start(); await flush();
  processor.audio();
  for (let i = 0; i < 5 && card._state === 'recording'; i++) await flush();
  await card._sending;
  assert.equal(card._state, 'idle');
  assert.ok(media.stopped && context.closed);
  assert.match(card._status.textContent, /not delivered/);
  assert.ok(calls.some(call => call.type.endsWith('/cancel')));
}

// Silent recording.
// Captures one chunk of silence (peak 0), which is streamed, then releases.
// Verifies: the frame was uploaded, but the final stop is sent with cancel: true, so
// the bridge forwards nothing to the TV.
{
  const { card, calls, frames } = create({ language: 'en' });
  await card._start(); await flush();
  processor.port.onmessage({ data: { type: 'audio', bytes: new Uint8Array(8192).buffer, peak: 0 } });
  await flush();
  await card._stop();
  assert.equal(frames.length, 1);
  assert.equal(calls.at(-1).type, 'tv_voice_bridge/stop');
  assert.equal(calls.at(-1).cancel, true);
}

// Re-rendering on hass updates.
// Assigns hass five times with the same language, then once with another language.
// Verifies: the same language causes no render; a language change renders once.
{
  const { card } = create({ language: 'en' });
  let renders = 0;
  const render = card._render.bind(card);
  card._render = (...args) => { renders++; return render(...args); };
  for (let i = 0; i < 5; i++) card.hass = { ...card._hass };
  assert.equal(renders, 0);
  card.hass = { ...card._hass, locale: { language: 'it' } };
  assert.equal(renders, 1);
}

// Overall 90-second deadline.
// Each progress reply arrives after 9 s, inside the 10 s per-request limit, while a
// full 59-chunk recording uploads.
// Verifies: the overall deadline still ends the upload with "timed out", returning the
// card to idle and releasing the buffer.
{
  mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] });
  const { card } = create({ language: 'en' });
  const original = card._hass.callWS;
  // The server computes each reply when it processes the request; only delivery is slow.
  card._hass.callWS = message => {
    const reply = original(message);
    return message.type.endsWith('/progress') ? new Promise(resolve => setTimeout(() => resolve(reply), 9000)) : reply;
  };
  await card._start(); await flush();
  for (let i = 0; i < 59; i++) processor.audio();
  const sending = card._stop(); await flush();
  for (let i = 0; i < 10; i++) { mock.timers.tick(9000); await flush(); }
  await sending; await card._sending;
  assert.equal(card._state, 'idle');
  assert.equal(card._buffer, null, 'recording released');
  assert.match(card._status.textContent, /timed out/);
  mock.timers.reset();
}

// Keyboard holds.
// For Space and Enter: keydown, a repeated keydown, then keyup.
// Verifies: the key starts recording, auto-repeat is ignored and keyup sends, ending idle.
for (const key of [' ', 'Enter']) {
  const { card } = create();
  press(card, 'keydown', { key }); await flush(); processor.audio();
  press(card, 'keydown', { key, repeat: true });
  press(card, 'keyup', { key }); await card._sending;
  assert.equal(card._state, 'idle');
}
// Assistive clicks and toggle mode.
// In hold mode, sends two clicks with detail 0 (screen readers and switch access);
// then switches to activation: toggle and sends two ordinary clicks.
// Verifies: each pair starts recording and then sends, ending idle.
{
  const { card } = create();
  press(card, 'click', { detail: 0 }); await flush();
  assert.equal(card._state, 'recording');
  processor.audio(); press(card, 'click', { detail: 0 }); await card._sending;
  assert.equal(card._state, 'idle');
  card.setConfig({ activation: 'toggle' });
  press(card, 'click', { detail: 1 }); await flush(); processor.audio();
  press(card, 'click', { detail: 1 }); await card._sending;
  assert.equal(card._state, 'idle');
}
// Audio context resumed within the user gesture.
// Makes the microphone request end the gesture, and checks inside resume() that the
// gesture is still active.
// Verifies: the card calls resume() at all, and does so before requesting the
// microphone.
{
  let gesture = true;
  let resumed = false;
  window.AudioContext = class extends AudioContext { async resume() { assert.ok(gesture); resumed = true; } };
  getUserMedia = async () => { gesture = false; return makeMedia(); };
  const { card } = create(); await card._start(); await card._stop(true);
  assert.ok(resumed, 'AudioContext.resume() was called');
  window.AudioContext = AudioContext;
  getUserMedia = async () => makeMedia();
}
// Translations.
// Verifies: Italian and English have the same keys; an unsupported language (fr-FR)
// falls back to English; Italian strings interpolate seconds and limit.
const keys = object => Object.entries(object).flatMap(([key, value]) => typeof value === 'object' ? keys(value).map(child => key + '.' + child) : [key]).sort();
assert.deepEqual(keys(languages.it), keys(languages.en));
assert.equal(localize('fr-FR', 'title'), 'Speak to TV');
assert.equal(localize('it-IT', 'recording', { seconds: 2, limit: 15 }), 'Parla ora · 2 / 15 s');
console.log('Voice card: binary privacy/ownership, hold/release, late handshake, cap, worklet cleanup, accessibility and localization passed.');
