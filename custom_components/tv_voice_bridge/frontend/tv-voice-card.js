import { baseStyles } from './styles.mjs';
import { localize } from './localize.mjs';
import './tv-voice-card-editor.js';

const SAMPLE_RATE = 16000;
const MAX_SECONDS = 15;
const MAX_BYTES = SAMPLE_RATE * 2 * MAX_SECONDS;
const coded = (code) => Object.assign(new Error(code), { code });

export class TVVoiceCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._state = 'idle';
    this._epoch = 0;
    this._config = {};
    this._language = 'en';
    this._onHide = () => { if (document.hidden) this._stop(true); };
    this._onEscape = (event) => { if (event.key === 'Escape') this._stop(true); };
    this._onPageHide = () => this._stop(true);
    this._onDisconnect = () => this._stop(true, 'errors.disconnected', true);
    this.shadowRoot.innerHTML = `
      <style>${baseStyles}</style>
      <ha-card part="card">
        <button part="button" type="button" aria-pressed="false" aria-describedby="voice-status">
          <ha-icon part="icon" icon="mdi:microphone"></ha-icon><span part="label"></span>
        </button>
        <div part="meter" class="meter" hidden><div part="level" class="level"></div></div>
        <p part="status" id="voice-status" role="status" aria-live="polite"></p>
      </ha-card>`;
    for (const [field, selector] of Object.entries({ button: 'button', label: 'span', status: 'p', icon: 'ha-icon', meter: '.meter', level: '.level' })) {
      this[`_${field}`] = this.shadowRoot.querySelector(selector);
    }
    this._button.addEventListener('pointerdown', (event) => {
      if (this._config.activation === 'toggle' || event.button !== 0 || this._state !== 'idle') return;
      event.preventDefault();
      this._pointer = event.pointerId;
      this._button.setPointerCapture(event.pointerId);
      this._start();
    });
    this._button.addEventListener('pointerup', (event) => {
      if (event.pointerId !== this._pointer) return;
      this._pointer = null;
      this._suppressClickUntil = Date.now() + 500;
      this._stop();
    });
    const cancelPointer = (event) => {
      if (event.pointerId !== this._pointer) return;
      this._pointer = null;
      this._stop(true);
    };
    this._button.addEventListener('pointercancel', cancelPointer);
    this._button.addEventListener('lostpointercapture', cancelPointer);
    this._button.addEventListener('keydown', (event) => {
      if (this._config.activation === 'toggle' || ![' ', 'Enter'].includes(event.key)) return;
      event.preventDefault();
      if (event.repeat || this._state !== 'idle') return;
      this._key = event.key;
      this._start();
    });
    this._button.addEventListener('keyup', (event) => {
      if (event.key !== this._key) return;
      event.preventDefault();
      this._key = null;
      this._suppressClickUntil = Date.now() + 500;
      this._stop();
    });
    this._button.addEventListener('blur', () => {
      if (this._key) { this._key = null; this._stop(true); }
    });
    this._button.addEventListener('contextmenu', (event) => event.preventDefault());
    this._button.addEventListener('click', (event) => {
      event.preventDefault();
      // AT/switch controls generate detail=0 clicks. Physical release must not
      // immediately start a second recording via a synthesized click.
      if (Date.now() < (this._suppressClickUntil || 0)) return;
      if (this._config.activation !== 'toggle' && event.detail !== 0) return;
      if (this._state === 'recording') this._stop();
      else if (this._state === 'idle') this._start();
    });
  }

  static getConfigElement() { return document.createElement('tv-voice-card-editor'); }
  static getStubConfig() { return { type: 'custom:tv-voice-card', activation: 'hold' }; }
  static get stylingVersion() { return 1; }
  setConfig(config) {
    if (config && 'remote' in config) throw Object.assign(coded('invalid_config'), { message: this._t('errors.invalid_config') });
    if (!config || (config.entity && !/^remote\.[a-z0-9_]+$/.test(config.entity)) ||
        (config.activation && !['hold', 'toggle'].includes(config.activation))) throw Object.assign(coded('invalid_target'), { message: this._t('errors.invalid_target') });
    if (this._state !== 'idle') this._stop(true);
    this._config = { activation: 'hold', ...config };
    this._render();
  }
  set hass(hass) {
    this._hass = hass;
    this._language = hass.locale?.language || hass.language || 'en';
    const metadata = window.customCards?.find(card => card.type === 'tv-voice-card');
    if (metadata) metadata.description = this._t('description');
    if (this._connection !== hass.connection) {
      this._connection?.removeEventListener('disconnected', this._onDisconnect);
      this._connection = hass.connection;
      this._connection?.addEventListener('disconnected', this._onDisconnect);
    }
    this._render(this._message, this._error, this._values);
  }
  getCardSize() { return 1; }
  connectedCallback() {
    this._render(this._message, this._error, this._values);
    document.addEventListener('visibilitychange', this._onHide);
    window.addEventListener('pagehide', this._onPageHide);
    window.addEventListener('keydown', this._onEscape);
    if (this._hass) this.hass = this._hass;
    this._observer = new IntersectionObserver((entries) => {
      if (!entries[0]?.isIntersecting) this._stop(true);
    });
    this._observer.observe(this);
  }
  disconnectedCallback() {
    this._stop(true);
    document.removeEventListener('visibilitychange', this._onHide);
    window.removeEventListener('pagehide', this._onPageHide);
    window.removeEventListener('keydown', this._onEscape);
    this._observer?.disconnect();
    this._connection?.removeEventListener('disconnected', this._onDisconnect);
    this._connection = null;
  }
  _t(key, values) { return localize(this._language, key, values); }
  _render(message = '', error = false, values = {}) {
    this._message = message; this._error = error; this._values = values;
    this.setAttribute('data-state', this._state);
    const recording = this._state === 'recording';
    this._button.classList.toggle('recording', recording);
    this._meter.hidden = !recording;
    this._button.disabled = this._state === 'sending';
    this._button.setAttribute('aria-pressed', String(recording));
    this._meter.setAttribute('aria-label', this._t('level'));
    this._icon.setAttribute('icon', recording ? 'mdi:stop' : 'mdi:microphone');
    this._label.textContent = this._t(recording ? (this._config.activation === 'toggle' ? 'stop' : 'release') :
      this._state === 'starting' ? 'starting' : this._state === 'sending' ? 'sending' : 'title');
    this._button.setAttribute('aria-label', this._label.textContent);
    this._status.classList.toggle('error', error);
    const feedback = Boolean(message) || this._state !== 'idle';
    this._status.setAttribute('part', feedback ? 'status feedback' : 'status hint');
    this._status.textContent = message ? this._t(message, values) :
      this._t(this._config.activation === 'toggle' ? 'toggle_hint' : 'hold_hint') + ' ' + this._t('accessible_hint');
  }

  async _start() {
    if (this._state !== 'idle') return;
    const epoch = ++this._epoch;
    this._state = 'starting';
    this._render('permission_hint');
    this._requestId = crypto.randomUUID().replaceAll('-', '');
    this._requestSent = false;
    this._token = null;
    this._sessionReady = null;
    this._bytes = new Uint8Array();
    this._capturedBytes = 0;
    this._peak = 0;
    this._acceptCapture = true;
    this._captureStopped = false;
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw coded('secure_context');
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      const context = this._context = new AudioContext();
      const resume = context.resume();
      resume.catch(() => {});
      const media = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false,
      });
      if (epoch !== this._epoch) { media.getTracks().forEach(track => track.stop()); return; }
      this._media = media;
      let resumeTimer;
      try {
        await Promise.race([resume, new Promise((_, reject) => {
          resumeTimer = setTimeout(() => reject(coded('audio_blocked')), 4000);
        })]);
      } finally { clearTimeout(resumeTimer); }
      if (epoch !== this._epoch) return;
      if (!context.audioWorklet || !window.AudioWorkletNode) throw coded('browser_unsupported');
      await context.audioWorklet.addModule(new URL('./pcm-worklet.js', import.meta.url));
      if (epoch !== this._epoch) return;
      this._processor = new window.AudioWorkletNode(context, 'tv-voice-pcm', {
        processorOptions: { targetRate: SAMPLE_RATE, maxSeconds: MAX_SECONDS },
      });
      this._captureDone = new Promise(resolve => { this._resolveCapture = resolve; });
      this._processor.port.onmessage = ({ data }) => {
        if (epoch !== this._epoch) return;
        if (data.type === 'stopped') {
          this._captureStopped = true;
          this._resolveCapture();
          if (data.limit && this._state === 'recording') this._stop();
          return;
        }
        if (data.type !== 'audio' || !this._acceptCapture) return;
        const pcm = new Uint8Array(data.bytes).subarray(0, MAX_BYTES - this._capturedBytes);
        const combined = new Uint8Array(this._bytes.length + pcm.length);
        combined.set(this._bytes); combined.set(pcm, this._bytes.length);
        this._bytes = combined;
        this._capturedBytes += pcm.length;
        this._peak = Math.max(this._peak, data.peak || 0);
        this._level.style.width = `${Math.min(100, (data.peak || 0) * 300)}%`;
      };
      this._processor.onprocessorerror = () => this._stop(true, 'errors.capture_failed', true);
      this._source = context.createMediaStreamSource(media);
      this._mute = context.createGain();
      this._mute.gain.value = 0;
      this._source.connect(this._processor);
      this._processor.connect(this._mute);
      this._mute.connect(context.destination);
      this._state = 'recording';
      this._started = Date.now();
      this._render('recording', false, { seconds: 0, limit: MAX_SECONDS });
      this._timer = setTimeout(() => this._stop(), MAX_SECONDS * 1000);
      this._ticker = setInterval(() => this._render('recording', false, {
        seconds: Math.min(MAX_SECONDS, Math.floor((Date.now() - this._started) / 1000)), limit: MAX_SECONDS,
      }), 1000);
      const hass = this._hass;
      const requestId = this._requestId;
      const entity = this._config.entity;
      this._requestSent = true;
      this._sessionReady = hass.callWS({ type: 'tv_voice_bridge/start', request_id: requestId,
        ...(entity ? { remote_entity: entity } : {}),
      }).then(async session => {
        if (epoch !== this._epoch) {
          await hass.callWS({ type: 'tv_voice_bridge/stop', session_id: session.session_id, cancel: true });
          return null;
        }
        if (session.protocol_version !== 2 || session.sample_rate !== SAMPLE_RATE ||
            !Number.isInteger(session.binary_handler_id) || session.binary_handler_id < 1 ||
            !Number.isInteger(session.chunk_bytes) || session.chunk_bytes < 2 || session.chunk_bytes > 16384 ||
            !/^[0-9a-f]{32}$/.test(session.session_id)) {
          await hass.callWS({ type: 'tv_voice_bridge/stop', session_id: session.session_id, cancel: true });
          throw coded('unsupported_version');
        }
        this._token = session.session_id;
        return session;
      }).catch(error => {
        if (epoch === this._epoch) this._stop(true, this._errorKey(error), true);
        return null;
      });
    } catch (error) {
      if (epoch === this._epoch) await this._stop(true, this._errorKey(error), true);
    }
  }

  _errorKey(error) {
    const code = error?.name === 'NotAllowedError' ? 'microphone_denied' :
      error?.name === 'NotFoundError' ? 'microphone_missing' : error?.code;
    return this._t(`errors.${code}`) !== `errors.${code}` ? `errors.${code}` : 'errors.unavailable';
  }

  async _releaseMicrophone(cancel) {
    clearTimeout(this._timer); clearInterval(this._ticker);
    const context = this._context;
    const processor = this._processor;
    const source = this._source;
    const mute = this._mute;
    this._media?.getTracks().forEach(track => track.stop());
    this._media = null;
    if (cancel) {
      this._acceptCapture = false;
      this._resolveCapture?.();
    }
    try {
      if (processor && !this._captureStopped) {
        processor.port.postMessage({ type: 'stop' });
        if (!cancel) {
          let timer;
          try {
            await Promise.race([this._captureDone, new Promise((_, reject) => {
              timer = setTimeout(() => reject(coded('capture_failed')), 500);
            })]);
          } finally { clearTimeout(timer); }
        }
      }
    } finally {
      source?.disconnect(); processor?.disconnect(); mute?.disconnect();
      if (processor) processor.port.onmessage = null;
      if (context) await context.close().catch(() => {});
      if (this._context === context) {
        this._acceptCapture = false;
        this._context = null;
        this._source = this._processor = this._mute = null;
      }
    }
  }

  _stop(cancel = false, message = '', error = false) {
    if (this._state === 'idle') return Promise.resolve();
    if (this._state === 'sending' && !cancel) return this._sending;
    cancel ||= this._state === 'starting';
    // Keep the epoch during the final worklet flush. Cancellation invalidates
    // all pending startup, audio callbacks and delivery continuations instead.
    if (cancel) ++this._epoch;
    const epoch = this._epoch;
    const hass = this._hass;
    const requestId = this._requestId;
    const requestSent = this._requestSent;
    this._state = 'sending';
    this._pointer = null; this._key = null;
    this._render(message || (this._token ? 'uploading' : 'connecting'), error);
    this._sending = (async () => {
      try {
        // Cancel startup immediately, rather than opening Gemini after the card
        // was closed while waiting for a slow handshake.
        if (cancel && requestSent) {
          hass.callWS({ type: 'tv_voice_bridge/cancel', request_id: requestId }).catch(() => {});
        }
        await this._releaseMicrophone(cancel);
        const session = cancel ? null : await this._sessionReady;
        if (epoch !== this._epoch) return;
        const token = this._token;
        if (token) {
          if (!cancel && (!this._capturedBytes || this._peak < .001)) {
            cancel = true; message = 'errors.no_audio'; error = true;
          }
          if (!cancel) {
            const connection = hass.connection;
            const socket = connection.socket;
            let sequence = 0;
            for (let offset = 0; offset < this._bytes.length; offset += session.chunk_bytes) {
              if (epoch !== this._epoch) return;
              if (!socket || connection.socket !== socket || socket.readyState !== 1) throw coded('disconnected');
              const pcm = this._bytes.subarray(offset, offset + session.chunk_bytes);
              const frame = new Uint8Array(21 + pcm.length);
              frame[0] = session.binary_handler_id;
              frame.set(Uint8Array.from(token.match(/../g), value => parseInt(value, 16)), 1);
              new DataView(frame.buffer).setUint32(17, sequence, true);
              frame.set(pcm, 21);
              socket.send(frame.buffer);
              sequence++;
              // Ack only metadata, so JSON debug logs cannot contain speech.
              const progress = await hass.callWS({ type: 'tv_voice_bridge/progress', session_id: token, sequence });
              if (progress.received_bytes !== offset + pcm.length) throw coded('delivery_failed');
            }
          }
          if (epoch !== this._epoch) return;
          const result = await hass.callWS({ type: 'tv_voice_bridge/stop', session_id: token, cancel,
            expected_bytes: this._capturedBytes });
          if (!cancel && (result?.delivery_failed || result?.forwarded_bytes !== this._capturedBytes)) throw coded('delivery_failed');
        }
      } catch (failure) {
        message = this._errorKey(failure); error = true;
        if (epoch === this._epoch && this._token) {
          try { await hass.callWS({ type: 'tv_voice_bridge/stop', session_id: this._token, cancel: true }); }
          catch { /* Disconnection also releases the connection-owned session. */ }
        }
      } finally {
        if (epoch === this._epoch) {
          // Cleanup still runs if a suspended worklet never acknowledges stop.
          this._acceptCapture = false;
          this._source?.disconnect(); this._processor?.disconnect(); this._mute?.disconnect();
          this._context?.close().catch(() => {});
          this._context = null;
          this._token = null;
          this._bytes = new Uint8Array();
          this._state = 'idle';
          this._render(message || (cancel ? 'cancelled' : 'sent'), error);
        }
      }
    })();
    return this._sending;
  }
}

if (!customElements.get('tv-voice-card')) customElements.define('tv-voice-card', TVVoiceCard);
window.customCards = window.customCards || [];
if (!window.customCards.some(card => card.type === 'tv-voice-card')) {
  window.customCards.push({ type: 'tv-voice-card', name: 'TV Voice Bridge', preview: true,
    description: localize(document.documentElement?.lang, 'description') });
}
