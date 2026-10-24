import { defineWhenReady } from './define.mjs';
import { localize } from './localize.mjs';

class TVVoiceCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }
  _render() {
    if (!this._config || !this._hass) return;
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    this.shadowRoot.replaceChildren();
    const language = this._hass.locale?.language || this._hass.language;
    const form = document.createElement('ha-form');
    form.hass = this._hass;
    form.data = { entity: this._config.entity,
      activation: this._config.activation || 'hold' };
    form.schema = [
      { name: 'entity', selector: { entity: { domain: 'remote', integration: 'androidtv_remote' } } },
      { name: 'activation', selector: { select: { options: ['hold', 'toggle'].map(value => ({
        value, label: localize(language, value),
      })) } } },
    ];
    form.computeLabel = field => localize(language, field.name);
    form.addEventListener('value-changed', event => {
      this._config = { ...this._config, ...event.detail.value };
      this.dispatchEvent(new CustomEvent('config-changed', {
        detail: { config: this._config }, bubbles: true, composed: true,
      }));
    });
    this.shadowRoot.append(form);
  }
}
defineWhenReady('tv-voice-card-editor', TVVoiceCardEditor);
