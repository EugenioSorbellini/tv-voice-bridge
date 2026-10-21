import assert from 'node:assert/strict';
import { PCMResampler } from '../custom_components/tv_voice_bridge/frontend/pcm.mjs';

let Processor;
globalThis.AudioWorkletProcessor = class {
  constructor() { this.messages = []; this.port = { postMessage: message => this.messages.push(message) }; }
};
globalThis.registerProcessor = (_, type) => { Processor = type; };
await import('../custom_components/tv_voice_bridge/frontend/pcm-worklet.js');
for (const rate of [44100, 48000]) {
  globalThis.sampleRate = rate;
  const worklet = new Processor({ processorOptions: { targetRate: 16000, maxSeconds: 15 } });
  const input = new Float32Array(128).fill(.25);
  for (let i = 0; i < Math.ceil(rate * 16 / 128); i++) worklet.process([[input]]);
  const audio = worklet.messages.filter(message => message.type === 'audio');
  assert.equal(audio.reduce((sum, message) => sum + message.bytes.byteLength, 0), 480000);
  assert.equal(worklet.messages.filter(message => message.type === 'stopped').length, 1);
  assert.equal(worklet.messages.at(-1).limit, true);
  assert.deepEqual(Buffer.concat(audio.map(message => Buffer.from(message.bytes))),
    Buffer.from(new PCMResampler(rate, 16000).push(new Float32Array(rate * 15).fill(.25))));
}
globalThis.sampleRate = 48000;
const worklet = new Processor({ processorOptions: {} });
worklet.process([[new Float32Array(128).fill(.5)]]);
assert.equal(worklet.messages.length, 0, 'small tail remains buffered while recording');
worklet.port.onmessage({ data: { type: 'stop' } });
assert.ok(worklet.messages[0].bytes.byteLength > 0, 'release flushes the tail');
assert.equal(worklet.messages.at(-1).type, 'stopped');
const count = worklet.messages.length;
worklet.process([[new Float32Array(128).fill(.5)]]);
assert.equal(worklet.messages.length, count, 'no recording after release');
console.log('AudioWorklet: exact PCM, autonomous 15s cap at 44.1/48kHz, tail flush and stop passed.');
