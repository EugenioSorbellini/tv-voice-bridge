import assert from 'node:assert/strict';
import { PCMResampler } from '../custom_components/tv_voice_bridge/frontend/pcm.mjs';

for (const target of [8000, 16000]) {
for (const rate of [16000, 44100, 48000]) {
  const input = Float32Array.from({ length: rate }, (_, i) => Math.sin(i * .07));
  const whole = new PCMResampler(rate, target).push(input);
  assert.equal(whole.length, target * 2, `one second at ${rate} -> ${target}`);
  const split = new PCMResampler(rate, target);
  const chunks = [];
  for (let start = 0; start < input.length; start += 127) chunks.push(split.push(input.subarray(start, start + 127)));
  const combined = Buffer.concat(chunks.map(c => Buffer.from(c)));
  assert.deepEqual(combined, Buffer.from(whole), `sample continuity at ${rate}`);
}
}
const clipped = new PCMResampler(8000, 8000).push(new Float32Array([-2, 2, NaN]));
assert.deepEqual([...clipped], [0, 128, 255, 127, 0, 0]);
assert.throws(() => new PCMResampler(0));
console.log('PCM resampling: sample counts, buffer boundaries, clipping and endian order passed.');
