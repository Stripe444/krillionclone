// Loads the Endless question bank (data/endless-bank.jsonl.gz) into D1.
// Usage: node scripts/load-endless.mjs --local
//        node scripts/load-endless.mjs --remote --config wrangler.production.jsonc
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { execFileSync } from 'node:child_process';

const rows = gunzipSync(readFileSync(new URL('../data/endless-bank.jsonl.gz', import.meta.url))).toString('utf8').trim().split('\n').map(l => JSON.parse(l));
// Rows are inserted grouped, so each group occupies one contiguous rowid range the server can sample from.
export const groupOf = family => ({ word: 'word', phrase: 'word', wordnet: 'category', geo: 'geo' })[String(family).split('-')[0]] || 'word';
rows.sort((a, b) => groupOf(a.family).localeCompare(groupOf(b.family)) || a.id.localeCompare(b.id));
const quote = s => `'${String(s).replace(/'/g, "''")}'`;
const lines = ['DELETE FROM bank;'];
for (const r of rows) {
  const content = JSON.stringify({ id: r.id, text: r.text, answers: r.answers });
  lines.push(`INSERT INTO bank(id,family,grp,content) VALUES(${quote(r.id)},${quote(r.family)},${quote(groupOf(r.family))},${quote(content)});`);
}
mkdirSync(new URL('../output/', import.meta.url), { recursive: true });
const file = new URL('../output/endless-bank.sql', import.meta.url).pathname;
writeFileSync(file, lines.join('\n') + '\n');
console.log(`Prepared ${rows.length} endless prompts in ${file}`);
if (process.argv.includes('--sql-only')) process.exit(0);
const args = ['wrangler', 'd1', 'execute', 'openkrillion', '--file', file, '--yes', ...process.argv.slice(2)];
execFileSync('npx', args, { stdio: 'inherit' });
