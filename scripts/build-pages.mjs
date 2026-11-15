// Builds a fully static copy of OpenKrillion for GitHub Pages (or any static host).
// The game runs in the browser via public/static-api.mjs; no Worker or database.
//
//   npm run build && PAGES_BASE=/your-repo-name/ node scripts/build-pages.mjs [outDir]
//
// PAGES_BASE is the URL path the site is served from: "/<repo>/" for a project
// site, "/" for a user site or a custom domain.
import { cp, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { gunzipSync } from 'node:zlib';
import { join } from 'node:path';
import { homePage, infoPage } from '../src/html.mjs';
import { documents } from '../src/docs.mjs';

const out = process.argv[2] || 'output/pages';
const base = ('/' + (process.env.PAGES_BASE || '/').replace(/^\/+|\/+$/g, '') + '/').replace('//', '/');
const env = { STATIC_SITE: 'true', LOCAL_DEVELOPMENT: process.env.PAGES_TEST === 'true' ? 'true' : 'false' };

await rm(out, { recursive: true, force: true });
await mkdir(out, { recursive: true });
await cp('public', out, { recursive: true });
const page = (path, html) => mkdir(join(out, path), { recursive: true }).then(() => writeFile(join(out, path, 'index.html'), html));
await page('', homePage('en', env));
await page('zh', homePage('zh', env));
await page('about', infoPage('/about'));
await page('privacy', infoPage('/privacy'));
for (const [path, text] of Object.entries(documents())) await writeFile(join(out, path), text);
await writeFile(join(out, 'robots.txt'), 'User-agent: *\nAllow: /\n');
await writeFile(join(out, '.nojekyll'), '');

// Question bank: small shards so a dive only downloads what it needs.
const SHARD = 50;
const rows = gunzipSync(await readFile('data/endless-bank.jsonl.gz')).toString('utf8').trim().split('\n').map(l => JSON.parse(l));
const groupOf = f => ({ word: 'word', phrase: 'word', wordnet: 'category', geo: 'geo' })[f.split('-')[0]] || 'word';
const groups = {}, shards = [];
for (const r of rows) {
  const n = Number(r.id.slice(1));
  (groups[groupOf(r.family)] ||= []).push(n);
  const s = Math.floor((n - 1) / SHARD);
  (shards[s] ||= {})[r.id] = { id: r.id, text: r.text, answers: r.answers };
}
await mkdir(join(out, 'bank'), { recursive: true });
await writeFile(join(out, 'bank/index.json'), JSON.stringify({ count: rows.length, shardSize: SHARD, groups }));
await Promise.all(shards.map((s, i) => writeFile(join(out, `bank/shard-${String(i).padStart(3, '0')}.json`), JSON.stringify(s))));

// Point root-relative links at the Pages base path.
const rewrite = text => text
  .replace(/(["'`(])\/\?lang=zh/g, `$1${base}zh/`)
  .replace(/(["'`(])\/\?lang=en/g, `$1${base}`)
  .replace(/href="\/"/g, `href="${base}"`)
  .replace(/(["'`(])\/(assets\/|app\.mjs|style\.css|llms\.txt|llms-full\.txt|pricing\.md|models\.md|about\b|privacy\b)/g, `$1${base}$2`);
async function walk(dir) {
  for (const e of await readdir(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isDirectory()) { if (e.name !== 'bank') await walk(p); }
    else if (/\.(html|mjs|css)$/.test(e.name)) await writeFile(p, rewrite(await readFile(p, 'utf8')));
  }
}
if (base !== '/') await walk(out);
await cp(join(out, 'index.html'), join(out, '404.html'));
console.log(`Static site with ${rows.length} prompts in ${shards.length} shards → ${out} (base ${base})`);
