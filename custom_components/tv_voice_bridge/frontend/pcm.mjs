// Stateful box-filter resampler: browser Float32 audio -> mono PCM16LE.
export class PCMResampler {
  constructor(sourceRate, targetRate = 16000) {
    if (!Number.isFinite(sourceRate) || !Number.isFinite(targetRate) || targetRate <= 0 || sourceRate < targetRate) {
      throw new Error("Unsupported microphone sample rate");
    }
    this.ratio = sourceRate / targetRate;
    this.sum = 0;
    this.weight = 0;
  }

  push(input) {
    const samples = [];
    for (const sample of input) {
      let remaining = 1;
      while (remaining > 1e-9) {
        const take = Math.min(remaining, this.ratio - this.weight);
        this.sum += (Number.isFinite(sample) ? sample : 0) * take;
        this.weight += take;
        remaining -= take;
        if (this.weight >= this.ratio - 1e-9) {
          const value = Math.max(-1, Math.min(1, this.sum / this.ratio));
          samples.push(Math.round(value * (value < 0 ? 32768 : 32767)));
          this.sum = 0;
          this.weight = 0;
        }
      }
    }
    const bytes = new Uint8Array(samples.length * 2);
    const view = new DataView(bytes.buffer);
    samples.forEach((sample, index) => view.setInt16(index * 2, sample, true));
    return bytes;
  }
}
