// Onboards a throwaway Home Assistant, then checks on repeated dashboard loads that HA's own
// card helper creates tv-voice-card. Loading races vary between page loads, so one pass is not enough.
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
  await page.goto(`${base}/lovelace`, { waitUntil: 'load' });
  // A real dashboard exercises HA's own card lookup, the path that fails when registration breaks.
  await settled(() => document.querySelector('home-assistant').hass.callWS({
    type: 'lovelace/config/save',
    config: { views: [{ title: 'Smoke', cards: [{ type: 'custom:tv-voice-card' }] }] },
  }));
  for (let load = 1; load <= loads; load++) {
    await page.goto(`${base}/lovelace/0`, { waitUntil: 'load' });
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
        errorCard: Boolean(find(document, 'hui-error-card')),
      };
    });
    assert.deepEqual(result, { rendered: true, styling: 1, editor: true, errorCard: false }, `Dashboard load ${load}`);
    console.log(`Dashboard load ${load}/${loads}: HA rendered tv-voice-card (styling v1) without an error card.`);
  }
} finally {
  await browser.close();
}
