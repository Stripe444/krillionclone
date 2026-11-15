// Browser-only game service for static hosting (GitHub Pages).
// Mirrors the Worker's /api/* endpoints with localStorage instead of D1.
// Scoring runs on the player's device, so answers are visible to anyone who
// inspects the files and there are no cross-player statistics.
import { TIERS, matchAnswer, etDate, resetAt, ROUND_MS, PREVIEW_MS } from './rules.mjs';

const ROOT = new URL('./bank/', import.meta.url);
const STORE = 'ok:static:runs';
const PLAN = ['word', 'word', 'word', 'category', 'category', 'geo', '*'];
let indexPromise = null;
const shards = new Map();

const load = () => { try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch { return {}; } };
const save = runs => {
  // keep the newest 400 runs so storage stays small
  const ids = Object.keys(runs).sort((a, b) => runs[b].created_at - runs[a].created_at);
  for (const id of ids.slice(400)) delete runs[id];
  try { localStorage.setItem(STORE, JSON.stringify(runs)); } catch { /* storage full or blocked */ }
};
class ApiError extends Error {}
const fail = message => { throw new ApiError(message); };

function index() {
  indexPromise ||= fetch(new URL('index.json', ROOT)).then(r => { if (!r.ok) throw new Error('Question bank unavailable.'); return r.json(); });
  return indexPromise;
}
async function prompt(id) {
  const { shardSize } = await index();
  const n = Number(id.slice(1)), shard = Math.floor((n - 1) / shardSize);
  if (!shards.has(shard)) shards.set(shard, fetch(new URL(`shard-${String(shard).padStart(3, '0')}.json`, ROOT)).then(r => r.json()));
  return (await shards.get(shard))[id];
}
// Seeded generator so every player gets the same daily dive.
function seeded(seed) {
  let h = 1779033703 ^ seed.length;
  for (let i = 0; i < seed.length; i++) { h = Math.imul(h ^ seed.charCodeAt(i), 3432918353); h = h << 13 | h >>> 19; }
  return () => { h = Math.imul(h ^ h >>> 16, 2246822507); h = Math.imul(h ^ h >>> 13, 3266489909); h ^= h >>> 16; return (h >>> 0) / 4294967296; };
}
async function draw(random, avoid = new Set()) {
  const { groups } = await index();
  const all = Object.values(groups).flat(), picked = [];
  for (const want of PLAN) {
    const pool = want === '*' ? all : groups[want] || all;
    for (let tries = 0; tries < 60; tries++) {
      const id = 'e' + String(pool[Math.floor(random() * pool.length)]).padStart(5, '0');
      if (picked.includes(id) || (avoid.has(id) && tries < 50)) continue;
      picked.push(id); break;
    }
  }
  for (let i = picked.length - 1; i > 0; i--) { const j = Math.floor(random() * (i + 1)); [picked[i], picked[j]] = [picked[j], picked[i]]; }
  return picked;
}
const dayNumber = date => Math.floor((Date.parse(date) - Date.parse('2026-07-16')) / 86400000) + 1;
const dailyIds = date => draw(seeded('openkrillion-daily-' + date));

async function puzzle(run) {
  const prompts = await Promise.all(run.prompt_ids.map(prompt));
  return { date: run.date, dayNumber: dayNumber(run.date), sample: false, endless: run.mode === 'practice', source: 'OpenKrillion endless bank', prompts };
}
const dto = p => ({ date: p.date, dayNumber: p.dayNumber, sample: false, endless: !!p.endless, source: p.source, resetsAt: resetAt(p.date), prompts: p.prompts.map(({ id, text }) => ({ id, text })) });
async function state(run) {
  const p = await puzzle(run), results = run.answers.map(({ round, rawAnswer, answer, tier, score }) => ({ round, rawAnswer, answer, tier, score }));
  return { ...dto(p), runId: run.id, mode: run.mode, round: run.next_round, roundStart: run.round_start, pausedAt: run.paused_at || null, serverNow: Date.now(), completed: !!run.completed, results, score: results.reduce((s, r) => s + r.score, 0) };
}
function own(runs, id) { const run = runs[id]; if (!run) fail('Dive not found on this browser.'); return run; }

export async function call(path, data) {
  const runs = load(), date = etDate();
  const [name, query] = path.split('?'), params = new URLSearchParams(query || '');
  if (name === 'today') {
    const ids = await dailyIds(date);
    return dto(await puzzle({ date, mode: 'daily', prompt_ids: ids }));
  }
  if (name === 'health') return { ok: true, static: true };
  if (name === 'state') return state(own(runs, params.get('run')));
  if (name === 'review') {
    const run = own(runs, params.get('run'));
    if (!run.completed) fail('Finish your dive before opening the answer sheet.');
    const p = await puzzle(run);
    return { prompts: p.prompts.map(q => ({ ...q, answers: q.answers.map(a => ({ ...a, score: TIERS[a.tier].score })).sort((a, b) => b.score - a.score || a.answer.localeCompare(b.answer)) })), population: 0, betterThan: null, dist: Array(71).fill(0) };
  }
  if (name === 'start') {
    const mode = data?.practice === true ? 'practice' : 'daily';
    let run = mode === 'daily' ? Object.values(runs).find(r => r.mode === 'daily' && r.date === date) : null;
    if (!run) {
      const seen = new Set(Object.values(runs).filter(r => r.mode === 'practice').flatMap(r => r.prompt_ids));
      const ids = mode === 'daily' ? await dailyIds(date) : await draw(Math.random, seen);
      run = { id: crypto.randomUUID(), date, mode, prompt_ids: ids, next_round: 0, round_start: Date.now() + PREVIEW_MS, paused_at: null, completed: 0, created_at: Date.now(), answers: [] };
      runs[run.id] = run; save(runs);
    }
    return state(run);
  }
  if (name === 'pause') {
    const run = own(runs, data.runId);
    if (data.paused === true && !run.completed && run.round_start !== null && !run.paused_at && Date.now() <= run.round_start + ROUND_MS) run.paused_at = Date.now();
    else if (data.paused === false && run.paused_at) { run.round_start += Date.now() - run.paused_at; run.paused_at = null; }
    save(runs); return state(run);
  }
  if (name === 'next') {
    const run = own(runs, data.runId);
    if (run.paused_at) fail('Close the menu to resume your dive.');
    if (!run.completed && run.round_start === null) { run.round_start = Date.now() + PREVIEW_MS; save(runs); }
    return state(run);
  }
  if (name === 'answer') {
    const run = own(runs, data.runId);
    if (run.paused_at) fail('Close the menu to resume your dive.');
    if (run.completed || run.round_start === null || data.round !== run.next_round) return { state: await state(run), alreadyScored: true };
    const p = (await puzzle(run)).prompts[run.next_round];
    const raw = typeof data.answer === 'string' ? data.answer.trim().slice(0, 256) : '';
    const late = Date.now() > run.round_start + ROUND_MS;
    const timely = !late || (data.timeout === true && Date.now() <= run.round_start + ROUND_MS + 1500);
    const match = raw && timely ? matchAnswer(raw, p.answers) : null;
    if (!match && raw && !late && !data.timeout) return { rejected: true, message: `“${raw}”: no echo. try again` };
    if (match?.correction && data.confirm !== true && !late && !data.timeout && data.previewCorrection !== false) return { correction: match.answer, original: raw };
    const result = { round: run.next_round, rawAnswer: raw || null, answer: match?.answer || null, tier: match?.tier || null, score: match ? TIERS[match.tier].score : 0, quip: match?.quip || null, promptText: p.text };
    run.answers.push(result); run.next_round += 1; run.round_start = null; run.completed = result.round === 6 ? 1 : 0;
    save(runs);
    return { result, state: await state(run) };
  }
  if (name === 'feedback') return { ok: true };
  fail('Unknown endpoint.');
}
