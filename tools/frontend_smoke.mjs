// Browser check against a real Home Assistant container, run weekly on stable and beta.
// Waits for HA to start, onboards a throwaway user, waits until the HA page references
// the card module, then creates a dashboard holding a custom:tv-voice-card and opens it
// five times in Chromium. Loading races vary between page loads, so one pass isn't enough.
// Verifies on each load: HA's own card helper renders tv-voice-card with a shadow root,
// stylingVersion 1 and its editor defined, and no error card remains after up to 20 s.
// On failure it saves a screenshot and logs the page's panel and card elements.
// Usage: node tools/frontend_smoke.mjs http://localhost:8123
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { chromium } from 'playwright';

const base = process.argv[2] || 'http://localhost:8123';
const clientId = `${base}/`;
const loads = 5;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function waitForHA() {
  // The first start installs component requirements, which can take minutes.
  for (const deadline = Date.now() + 600000; Date.now() < deadline; await sleep(3000)) {
    try {
      if ((await fetch(`${base}/api/onboarding`)).ok) return;
    } catch {}
  }
  throw new Error('Home Assistant did not start');
}

async function post(path, body, token) {
  const response = await fetch(base + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
  });
  assert.ok(response.ok, `${path}: HTTP ${response.status}`);
  return response.json();
}

async function onboard() {
  const { auth_code: code } = await post('/api/onboarding/users', {
    client_id: clientId, name: 'Smoke test', username: 'smoke',
    password: randomBytes(18).toString('base64url'), language: 'en',
  });
  const response = await fetch(`${base}/auth/token`, {
    method: 'POST',
    body: new URLSearchParams({ grant_type: 'authorization_code', code, client_id: clientId }),
  });
  assert.ok(response.ok, `/auth/token: HTTP ${response.status}`);
  const tokens = await response.json();
  await post('/api/onboarding/core_config', {}, tokens.access_token);
  await post('/api/onboarding/analytics', {}, tokens.access_token);
  await post('/api/onboarding/integration', { client_id: clientId, redirect_uri: clientId }, tokens.access_token);
  return { ...tokens, hassUrl: base, clientId, expires: Date.now() + tokens.expires_in * 1000 };
}

async function waitForModule() {
  // The onboarding API answers before integrations finish setting up.
  for (const deadline = Date.now() + 300000; Date.now() < deadline; await sleep(3000)) {
    const index = await (await fetch(`${base}/`)).text();
    if (/\/tv_voice_bridge\/frontend\/[^"']+\/tv-voice-card\.js/.test(index)) return;
  }
  throw new Error('The integration did not register its frontend module; check the Home Assistant log.');
}

await waitForHA();
const tokens = await onboard();
await waitForModule();

const browser = await chromium.launch();
try {
  const context = await browser.newContext();
  await context.addInitScript(([origin, value]) => {
    if (location.origin === origin) localStorage.setItem('hassTokens', value);
  }, [base, JSON.stringify(tokens)]);
  const page = await context.newPage();
  // Record when the card and HA's root are defined, relative to HA replacing the native registry.
  await context.addInitScript(() => {
    const native = window.customElements;
    const define = native.define.bind(native);
    window.__smokeDefinitions = [];
    native.define = (name, ...rest) => {
      if (/^(tv-voice-card|home-assistant)$/.test(name)) {
        window.__smokeDefinitions.push(`${name}${window.customElements === native ? ' (native registry)' : ' (via polyfill)'}`);
      }
      return define(name, ...rest);
    };
  });
  const ready = () => page.waitForFunction(() => document.querySelector('home-assistant')?.hass,
    null, { timeout: 60000 });
  // HA may reload or reroute while starting; evaluate again in the settled page.
  const settled = async callback => {
    for (let attempt = 1; ; attempt++) {
      try {
        await ready();
        return await page.evaluate(callback);
      } catch (error) {
        if (attempt === 3 || !/context was destroyed|navigation/i.test(error.message)) throw error;
        await page.waitForLoadState('load');
      }
    }
  };
  await page.goto(`${base}/`, { waitUntil: 'load' });
  // A real dashboard exercises HA's own card lookup, the path that fails when registration breaks.
  // Use a dedicated one: the default Overview can redirect to other panels.
  await settled(async () => {
    const { hass } = document.querySelector('home-assistant');
    await hass.callWS({ type: 'lovelace/dashboards/create', url_path: 'smoke-test', title: 'Smoke test', mode: 'storage' });
    await hass.callWS({
      type: 'lovelace/config/save', url_path: 'smoke-test',
      config: { views: [{ title: 'Smoke', cards: [{ type: 'custom:tv-voice-card' }] }] },
    });
  });
  for (let load = 1; load <= loads; load++) {
    await page.goto(`${base}/smoke-test/0`, { waitUntil: 'load' });
    const result = await settled(async () => {
      const find = (root, name) => {
        for (const element of root.querySelectorAll('*')) {
          if (element.localName === name) return element;
          const nested = element.shadowRoot && find(element.shadowRoot, name);
          if (nested) return nested;
        }
        return null;
      };
      // HA shows an error card while a custom element is missing, then replaces it once defined.
      let card = null;
      for (const deadline = Date.now() + 20000; Date.now() < deadline; await new Promise(r => setTimeout(r, 200))) {
        card = find(document, 'tv-voice-card');
        if (card?.shadowRoot && !find(document, 'hui-error-card')) break;
      }
      return {
        rendered: Boolean(card?.shadowRoot),
        styling: card?.constructor.stylingVersion,
        editor: Boolean(customElements.get('tv-voice-card-editor')),
        // Whether HA replaced the native registry; the race only matters when it does.
        polyfilled: customElements.constructor !== CustomElementRegistry
          || !/\[native code\]/.test(Function.prototype.toString.call(customElements.get)),
        errorCard: Boolean(find(document, 'hui-error-card')),
      };
    });
    const { polyfilled, ...checked } = result;
    const expected = { rendered: true, styling: 1, editor: true, errorCard: false };
    if (!(Object.entries(expected).every(([key, value]) => checked[key] === value))) {
      await page.screenshot({ path: 'smoke-failure.png' });
      console.log('Page state:', JSON.stringify(await page.evaluate(() => {
        const names = new Set();
        const walk = root => root.querySelectorAll('*').forEach(element => {
          if (/^(ha-panel|hui-|tv-)/.test(element.localName)) names.add(element.localName);
          if (element.shadowRoot) walk(element.shadowRoot);
        });
        walk(document);
        return { path: location.pathname, launchScreen: Boolean(document.getElementById('ha-launch-screen')),
          elements: [...names] };
      })));
    }
    assert.deepEqual(checked, expected, `Dashboard load ${load}`);
    console.log(`Dashboard load ${load}/${loads}: HA rendered tv-voice-card (styling v1) without an error card`
      + ` (${polyfilled ? 'scoped-registry polyfill active' : 'native registry'};`
      + ` defined: ${(await page.evaluate(() => window.__smokeDefinitions)).join(', ')}).`);
  }
} finally {
  await browser.close();
}
