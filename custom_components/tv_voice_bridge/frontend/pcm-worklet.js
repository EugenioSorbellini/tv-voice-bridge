import { PCMResampler } from './pcm.mjs';

// PCM capture and its 15-second cap run off the UI thread.
class TVVoicePCM extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const { targetRate = 16000, maxSeconds = 15 } = options.processorOptions || {};
    this.resampler = new PCMResampler(sampleRate, targetRate);
    this.maxBytes = targetRate * 2 * Math.min(15, maxSeconds);
    this.total = 0;
    this.active = true;
    this.buffer = new Uint8Array(2048);
    this.used = 0;
    this.peak = 0;
    this.port.onmessage = ({ data }) => {
      if (data.type === 'stop') this.finish();
    };
  }
  flush() {
    if (!this.used) return;
    const bytes = this.buffer.slice(0, this.used);
    this.port.postMessage({ type: 'audio', bytes: bytes.buffer, peak: this.peak }, [bytes.buffer]);
    this.used = 0;
    this.peak = 0;
  }
  finish(limit = false) {
    if (!this.active) return;
    this.active = false;
    this.flush();
    this.port.postMessage({ type: 'stopped', limit });
  }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (!this.active || !input) return true;
    const pcm = this.resampler.push(input).subarray(0, this.maxBytes - this.total);
    for (const value of input) this.peak = Math.max(this.peak, Math.abs(value));
    this.total += pcm.length;
    for (let offset = 0; offset < pcm.length;) {
      const count = Math.min(this.buffer.length - this.used, pcm.length - offset);
      this.buffer.set(pcm.subarray(offset, offset + count), this.used);
      this.used += count;
      offset += count;
      if (this.used === this.buffer.length) this.flush();
    }
    if (this.total >= this.maxBytes) this.finish(true);
    return true;
  }
}
registerProcessor('tv-voice-pcm', TVVoicePCM);
