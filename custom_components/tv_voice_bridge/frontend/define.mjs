// HA imports extra modules in parallel with its app bundle, which may replace window.customElements
// with a scoped-registry polyfill that ignores elements defined before it. Define once the app has
// registered its root element, so the definition lands in the registry dashboards look up.
// The timeout still defines the card if a future frontend renames its root element.
export const APP_READY_TIMEOUT_MS = 10000;

const appReady = Promise.race([
  ...['home-assistant', 'hc-main'].map(name => customElements.whenDefined(name)),
  new Promise(resolve => setTimeout(resolve, APP_READY_TIMEOUT_MS)),
]);

export const defineWhenReady = (name, type) => appReady.then(() => {
  if (!customElements.get(name)) customElements.define(name, type);
});
