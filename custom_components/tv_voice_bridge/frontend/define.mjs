// HA imports extra modules in parallel with its app bundle, which may replace window.customElements
// with a scoped-registry polyfill that ignores elements defined before it. Define once the app has
// registered its root element, so the definition lands in the registry dashboards look up.
const appReady = Promise.race(['home-assistant', 'hc-main'].map(name => customElements.whenDefined(name)));

export const defineWhenReady = (name, type) => appReady.then(() => {
  if (!customElements.get(name)) customElements.define(name, type);
});
