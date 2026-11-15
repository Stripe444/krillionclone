// Plays two Endless dives in Chrome against a local server, answering from the bank.
// Usage: node scripts/endless-audit.mjs http://localhost:3051 output/playwright/endless
import { chromium } from 'playwright';
import { mkdir, readFile } from 'node:fs/promises';
import { gunzipSync } from 'node:zlib';
import assert from 'node:assert/strict';

const base = process.argv[2] || 'http://localhost:3051', output = process.argv[3] || 'output/playwright/endless';
await mkdir(output, { recursive: true });
const bank = new Map(gunzipSync(await readFile(new URL('../data/endless-bank.jsonl.gz', import.meta.url))).toString('utf8').trim().split('\n').map(l => JSON.parse(l)).map(r => [r.text, r]));
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const errors = [], dives = [];
const ui = page => page.evaluate(() => JSON.parse(window.render_game_to_text()));
const phase = (page, p, timeout = 20000) => page.waitForFunction(p => JSON.parse(window.render_game_to_text()).phase === p, p, { timeout });
try {
  for (const [name, viewport] of [['desktop', { width: 1440, height: 1000 }], ['mobile', { width: 390, height: 844 }]]) {
    const page = await (await browser.newContext({ viewport })).newPage();
    page.on('pageerror', e => errors.push(e.message)); page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    await page.goto(base + '/?test=1'); await page.waitForFunction(() => window.render_game_to_text);
    await page.locator('#practice-btn').click({ force: true });
    const texts = [];
    for (let i = 0; i < 7; i++) {
      if (i) { await page.locator('#next-btn').click(); }
      await phase(page, 'preview'); await page.evaluate(() => window.advanceTime(3100)); await phase(page, 'answering');
      const r = (await ui(page)).prompt;
      const prompt = bank.get(r);
      assert.ok(prompt, 'prompt not from the endless bank: ' + r);
      texts.push(r);
      // Alternate a common and a rare answer
      const answer = (i % 2 ? prompt.answers.at(-1) : prompt.answers[0]).answer;
      await page.locator('#answer').fill(answer); await page.locator('#answer').press('Enter');
      await page.waitForFunction(() => { const s = JSON.parse(window.render_game_to_text()); return s.phase === 'landed' || document.getElementById('answer-status').textContent.includes('corrects to'); });
      if ((await ui(page)).phase !== 'landed') await page.locator('#answer').press('Enter');
      await phase(page, 'landed');
      if (i === 0) await page.screenshot({ path: `${output}/${name}-round1.png` });
    }
    await page.locator('#next-btn').click(); await phase(page, 'done');
    await page.waitForTimeout(800); await page.screenshot({ path: `${output}/${name}-results.png`, fullPage: false });
    const header = await page.locator('.result-header').textContent();
    assert.match(header, /Endless/);
    const score = (await ui(page)).score;
    dives.push({ name, score, texts });
    // a second dive must draw different prompts
    await page.locator('[data-action="practice"]').first().click();
    await phase(page, 'preview');
    const again = (await ui(page)).prompt;
    assert.ok(bank.has(again) && !texts.includes(again), 'second dive did not draw a fresh prompt');
  }
} finally { await browser.close(); }
console.log(JSON.stringify({ ok: errors.length === 0, errors, dives }, null, 1));
if (errors.length) process.exit(1);
