"""Generate the OpenKrillion Endless question bank.

Sources (all open data, installed locally):
  * WordNet 3.1 (npm wordnet-db) - categories and the English dictionary
  * wordfreq (pip) - word/phrase frequency, used as the rarity proxy
  * geonamescache (pip) - countries and cities (GeoNames, CC BY 4.0)
  * pronouncing (pip) - CMU Pronouncing Dictionary, for rhymes
  * pycountry (pip) - ISO 639 language names
  * naughty-words (npm) - profanity filter

Rarity is a proxy: inside each prompt, answers are ranked by how common they
are (word frequency, or population for cities) and split into tiers.

Setup (from this folder):
  npm install --no-save --prefix . wordnet-db@3.1.14 naughty-words
  pip install -r requirements.txt
Usage: python3 generate.py OUT.jsonl [TARGET]
Then gzip it to data/endless-bank.jsonl.gz and run `npm run db:endless`.
"""
import json, random, re, sys, unicodedata, collections, math
from wordfreq import zipf_frequency
import geonamescache
import os
import wn
HERE = os.path.dirname(os.path.abspath(__file__))
NM = os.path.join(HERE, 'node_modules')

random.seed(20261115)
TARGET = int(sys.argv[2]) if len(sys.argv) > 2 else 10000
OUT = sys.argv[1]

def z(text):
    return zipf_frequency(text, 'en')

def norm(s):
    s = unicodedata.normalize('NFKD', str(s))
    s = re.sub(r'[̀-ͯ]', '', s).lower().replace('&', 'and')
    return re.sub(r'[^a-z0-9]', '', s)

def article(word):
    w = word.lower()
    if re.match(r'^(uni|use|usu|eu|one|once|u[bcfhjkqrstn][aeiou])', w): return 'a'
    if re.match(r'^(hour|honest|honou?r|heir)', w): return 'an'
    return 'an' if w[:1] in 'aeiou' else 'a'

BAD = set(json.load(open(os.path.join(NM, 'naughty-words/en.json'))))
BAD |= {'nigger', 'nigga', 'faggot', 'fag', 'retard', 'spic', 'kike', 'chink', 'gook', 'wetback', 'tranny', 'dyke',
        'coon', 'darky', 'darkie', 'jap', 'paki', 'raghead', 'towelhead', 'wop', 'dago', 'kraut', 'honky', 'cracker',
        'redskin', 'squaw', 'gyp', 'gypsy', 'injun', 'spade', 'slut', 'whore', 'cunt', 'twat', 'bitch', 'bastard',
        'cock', 'dick', 'prick', 'pussy', 'tits', 'boob', 'boobs', 'fuck', 'shit', 'piss', 'wank', 'wanker', 'bollocks',
        'arse', 'arsehole', 'asshole', 'cum', 'jizz', 'rape', 'rapist', 'nazi', 'porn', 'dildo', 'anal', 'anus', 'penis',
        'vagina', 'scrotum', 'testicle', 'masturbate', 'masturbation', 'orgasm', 'semen', 'sperm', 'erection', 'clitoris'}
BAD_GLOSS = re.compile(r'offensive|disparag|derogator|ethnic slur|\bslur\b|vulgar|obscen|term of abuse|insult|contempt', re.I)

def clean(text):
    toks = re.findall(r'[a-z]+', text.lower())
    return not any(t in BAD for t in toks) and norm(text) not in {norm(b) for b in ()}

TIER_SPLIT = [('plankton', .12), ('schooler', .23), ('rare', .30), ('deepcut', .22), ('krillion', .13)]

def tiered(items):
    """items: list of (answer, popularity, aliases). Returns answer dicts ranked into tiers."""
    seen, uniq = set(), []
    for ans, pop, aliases in sorted(items, key=lambda x: -x[1]):
        k = norm(ans)
        if not k or k in seen or not clean(ans):
            continue
        seen.add(k)
        al = []
        for a in aliases:
            ka = norm(a)
            if ka and ka not in seen and len(ka) >= 3 and clean(a):
                seen.add(ka); al.append(a)
        uniq.append((ans, pop, al))
    n = len(uniq)
    out, i = [], 0
    bounds = []
    acc = 0
    for name, frac in TIER_SPLIT:
        acc += frac; bounds.append((name, acc))
    for idx, (ans, pop, al) in enumerate(uniq):
        p = (idx + 0.5) / n
        tier = next(name for name, b in bounds if p <= b)
        if idx == 0: tier = 'plankton'
        if idx == n - 1 and n >= 5: tier = 'krillion'
        d = {'answer': ans, 'tier': tier}
        if al: d['aliases'] = al[:6]
        out.append(d)
    return out

def nice(word):
    return word[:1].upper() + word[1:]

prompts = {}  # family -> list
BAD_FRAGMENTS = ('SEX', 'PORN', 'RAPE', 'NAZI', 'FUCK', 'SHIT', 'CUM', 'ANAL', 'ANUS', 'TIT', 'DICK', 'COCK', 'PISS',
                 'SLUT', 'WHORE', 'NIG', 'FAG', 'CUNT', 'TWAT', 'BITCH', 'PENI', 'VAGIN', 'ORGASM', 'SPERM', 'SEMEN', 'BOOB',
                 'ERECT', 'NUDE', 'NAKED', 'KILL', 'MURDER', 'SUICID', 'DRUG', 'COCAIN', 'HEROIN', 'TORTUR', 'SLAVE')
def add(family, text, items, min_n=6, max_n=500, min_top=3.0, pop_is_zipf=True):
    if not clean(text) or any(f in text.upper() for f in BAD_FRAGMENTS):
        return
    answers = tiered(items)
    if not (min_n <= len(answers) <= max_n):
        return
    if pop_is_zipf:
        top = sorted((p for _, p, _ in items), reverse=True)
        if len(top) < 3 or top[2] < min_top:
            return
    prompts.setdefault(family, []).append({'family': family, 'text': text, 'answers': answers})

# ---------------------------------------------------------------- WordNet
syn, senses = wn.load()
def descendants(off, syms):
    out, stack, seen = [], [off], {off}
    while stack:
        o = stack.pop()
        for s, t in syn[o]['ptrs']:
            if s in syms and t not in seen:
                seen.add(t); out.append(t); stack.append(t)
    return out

GOOD_LEX = {'noun.animal', 'noun.artifact', 'noun.food', 'noun.plant', 'noun.object', 'noun.body', 'noun.substance',
            'noun.location', 'noun.person', 'noun.shape', 'noun.quantity', 'noun.phenomenon', 'noun.communication',
            'noun.act', 'noun.event', 'noun.group', 'noun.cognition', 'noun.time'}
# abstract domains only allowed for these hand-picked heads
ABSTRACT_OK = {'noun.act': {'sport', 'game', 'dance', 'ball game', 'board game', 'card game', 'contact sport', 'team sport',
                            'outdoor game', 'martial art', 'exercise', 'swimming stroke', 'crime', 'surgery', 'hobby', 'art', 'craft',
                            'gymnastics', 'skiing', 'race', 'riding', 'fishing', 'hunting', 'job', 'occupation', 'trade', 'profession'},
               'noun.communication': {'language', 'dialect', 'alphabet', 'letter', 'music genre', 'musical composition', 'song', 'dance music',
                                      'popular music', 'jazz', 'rock', 'folk music', 'poem', 'novel', 'play', 'film', 'magazine', 'newspaper',
                                      'book', 'dictionary', 'punctuation', 'symbol', 'sign', 'signal', 'code', 'programming language',
                                      'computer language', 'language unit', 'word', 'greeting', 'sacred text', 'scripture', 'prayer',
                                      'hymn', 'opera', 'drama', 'comedy', 'genre', 'literary genre', 'Romance language', 'Germanic language',
                                      'Slavic language', 'Semitic', 'Indo-European language', 'natural language', 'African language',
                                      'Sino-Tibetan language', 'Amerind', 'Austronesian language', 'artificial language', 'musical notation',
                                      'note', 'chord', 'scale', 'interval', 'tempo', 'dance step', 'cartoon', 'comic strip', 'painting',
                                      'map', 'chart', 'title', 'nickname', 'pseudonym', 'oath', 'swearing', 'abbreviation', 'acronym'},
               'noun.event': {'storm', 'celebration', 'holiday', 'festival', 'party', 'contest', 'competition', 'sport event',
                              'game', 'race', 'tournament', 'battle', 'war', 'disaster', 'catastrophe', 'explosion', 'sound',
                              'noise', 'natural disaster'},
               'noun.group': {'religion', 'church', 'religious order', 'army', 'military unit', 'band', 'orchestra',
                              'family', 'tribe', 'dynasty', 'political party', 'team', 'club', 'organization', 'gang', 'social class',
                              'flock', 'herd', 'school', 'pack', 'Native American', 'ethnic group'},
               'noun.cognition': {'science', 'natural science', 'social science', 'branch of knowledge', 'discipline',
                                  'medicine', 'mathematics', 'philosophy', 'theology', 'art', 'fine arts', 'architecture',
                                  'engineering', 'biology', 'physics', 'chemistry', 'psychology', 'linguistics', 'religion',
                                  'belief', 'doctrine', 'theory', 'myth', 'superstition', 'architectural style', 'style',
                                  'school', 'art movement', 'movement', 'humanistic discipline', 'geometry', 'algebra'},
               'noun.time': {'month', 'day', 'weekday', 'season', 'holiday', 'era', 'geological period', 'period',
                             'time unit', 'calendar month', 'Gregorian calendar month', 'Jewish calendar month', 'Islamic calendar month',
                             'Hindu calendar month', 'festival', 'feast day', 'zodiac', 'sign of the zodiac', 'meal'}}
BAD_HEAD = re.compile(r'\b(genus|family|order|class|phylum|subclass|suborder|superfamily|subfamily|division|kingdom|'
                      r'tribe of|taxon|subphylum|superorder|infraorder|cohort|variety|form)\b')
SENSITIVE_HEADS = {'criminal', 'murderer', 'killer', 'terrorist', 'slave', 'prostitute', 'drug', 'narcotic', 'poison', 'weapon',
                   'explosive', 'gun', 'firearm', 'bomb', 'torture', 'execution', 'disease', 'illness', 'disorder', 'cancer',
                   'mental disorder', 'deformity', 'abnormality', 'person', 'woman', 'man', 'adult', 'female', 'male',
                   'unpleasant person', 'bad person', 'lover', 'sexual', 'sex', 'racist', 'bigot', 'homosexual', 'dictator',
                   'tyrant', 'assassin', 'thief', 'swindler', 'gangster', 'drug addict', 'addict', 'alcoholic', 'mistress',
                   'pervert', 'deviant', 'misfit', 'idiot', 'fool', 'simpleton', 'weakling', 'coward', 'disreputable person',
                   'wrongdoer', 'evildoer', 'offender', 'ammunition', 'projectile', 'missile', 'torpedo', 'chemical weapon',
                   'toxin', 'venom', 'soldier', 'mercenary', 'spy', 'informer', 'deity', 'god', 'goddess', 'religious person',
                   'ethnic group', 'Native American', 'race', 'people', 'tribe', 'religion', 'sect', 'cult', 'church'}

HEAD_BLOCK = set(open(os.path.join(HERE, 'head_block.txt')).read().split('\n')) if os.path.exists(os.path.join(HERE, 'head_block.txt')) else set()
JARGON = re.compile(r'\b(phenomenon|quantity|definite|indefinite|vascular|instrumentality|implement|artifact|object|entity|'
                    r'matter|unit|whole|part|portion|component|constituent|element|structure|system|process|attribute|'
                    r'state|condition|abstraction|relation|measure|property|substance|material|compound|mixture|agent|'
                    r'organism|being|living thing|individual|social group|group|collection|arrangement|area|region|'
                    r'district|location|point|position|place|space|line|surface|body|formation|device|equipment|'
                    r'apparatus|mechanism|covering|creation|product|representation|communication|act|activity|'
                    r'event|happening|change|action|ability|skill|knowledge|content|idea|concept|feeling|emotion|'
                    r'phenomena|natural object|geological|celestial|chemical|electrical|biological|physical|social|'
                    r'medical|legal|financial|commercial|official|administrative|political|religious|military|'
                    r'young|male|female|adult|worker|expert|leader|person|people|someone|somebody|human|stuff|thing|'
                    r'kind|sort|type|form|variety|class|category|piece|item|article|case|set|series|layer|sheet)\b')

def phrase_pop(w):
    return z(w) if ' ' not in w else z(w) * 0.92  # phrases are naturally rarer; light correction

RANK = {}
for lemma, offs_ in senses.items():
    for r, o in enumerate(offs_):
        RANK[(lemma.lower(), o)] = r

def sense_pop(w, off):
    # A word scores as "common" only when this is a main meaning of it:
    # "pen" is a female swan, but nobody says it for "name a bird".
    r = RANK.get((w.lower(), off), 3)
    return phrase_pop(w) - 1.4 * min(r, 3)

def synset_items(offs, proper):
    items = []
    for o in offs:
        s = syn[o]
        if BAD_GLOSS.search(s['gloss']):
            continue
        words = [w for w in s['words'] if not re.search(r'\d', w)]
        if not words:
            continue
        if proper:
            words = [w for w in words if w[:1].isupper()]
        else:
            words = [w for w in words if w[:1].islower()]
        if not words:
            continue
        words = [w for w in words if len(w) <= 40 and w.count(' ') <= 3]
        if not words:
            continue
        # display the most familiar lemma; others become aliases
        best = max(words, key=lambda w: (sense_pop(w, o), len(w)))
        if proper:
            # prefer the most familiar multi-word name ("Bob Hope", not "Leslie Townes Hope"); surnames stay as aliases
            multi = [w for w in words if ' ' in w and not re.search(r'\b(Baron|Baroness|Lord|Lady|Earl|Viscount|Duke|of Lodsworth)\b', w)]
            best = max(multi or words, key=lambda w: (phrase_pop(w), -len(w)))
            if best.startswith('Sir '):
                words = words + [best]; best = best[4:]
        pop = max(sense_pop(w, o) for w in words)
        items.append((nice(best), pop, [w for w in words if w != best]))
    return items

cat_count = 0
head_seen = set()
big_categories = {}  # head -> items, for letter splits
for off, s in syn.items():
    head = s['words'][0]
    lex = s['lex']
    if lex not in GOOD_LEX or not head[:1].islower() or BAD_HEAD.search(head) or BAD_GLOSS.search(s['gloss']):
        continue
    if lex in ABSTRACT_OK and head not in ABSTRACT_OK[lex]:
        continue
    if head in SENSITIVE_HEADS or not clean(head):
        continue
    if senses.get(head.lower(), [None])[0] != off:  # must be the word's main sense
        continue
    if z(head) < 3.6 or head in head_seen or any(z(t) < 3.3 for t in head.split()) or JARGON.search(head):
        continue
    inst = descendants(off, {'~i'})
    hypo = descendants(off, {'~'})
    hypo_inst = [t for o in hypo for (sy, t) in syn[o]['ptrs'] if sy == '~i']
    instances = inst + hypo_inst
    if len(instances) >= 8 and len(instances) >= len(hypo) * 0.5:
        items = synset_items(set(instances), proper=True)
        text = f'Name {article(head)} {head}'
        family = 'wordnet-instance'
    else:
        items = synset_items(set(hypo), proper=False)
        text = f'Name a type of {head}'
        family = 'wordnet-type'
    offs_list = set(instances) if family == 'wordnet-instance' else set(hypo)
    main = sum(1 for o in offs_list if any(RANK.get((w.lower(), o), 9) == 0 for w in syn[o]['words']))
    if offs_list and main / len(offs_list) < 0.55:
        continue
    if head in HEAD_BLOCK:
        continue
    if len(items) > 500:
        big_categories[head] = (items, family)
        continue
    before = len(prompts.get(family, []))
    add(family, text, items, min_n=6, max_n=500, min_top=2.8)
    if len(prompts.get(family, [])) > before:
        head_seen.add(head)

# Broad categories split by first letter: "Name an animal that starts with B"

LETTER_OK = {'city', 'tree', 'scientist', 'writer', 'bird', 'fish', 'clothing', 'vehicle', 'animal', 'mammal', 'insect',
             'flower', 'fruit', 'vegetable', 'food', 'dish', 'dessert', 'beverage', 'sport', 'musical instrument', 'tool',
             'painter', 'composer', 'poet', 'island', 'river', 'mountain', 'dog', 'plant', 'shrub', 'dance', 'game'}
for head, (items, family) in big_categories.items():
    if head in SENSITIVE_HEADS or head not in LETTER_OK:
        continue
    by_letter = collections.defaultdict(list)
    for it in items:
        k = norm(it[0])[:1]
        if k.isalpha():
            by_letter[k].append(it)
    for letter, its in by_letter.items():
        if family == 'wordnet-instance':
            text = f'Name {article(head)} {head} whose name starts with {letter.upper()}'
        else:
            text = f'Name a type of {head} that starts with {letter.upper()}'
        add(family + '-letter', text, its, min_n=6, max_n=400, min_top=2.6)

# ---------------------------------------------------------------- dictionary + word puzzles
base_words = set()
for pos in ['noun', 'verb', 'adj', 'adv']:
    with open(f'{wn.DICT}/index.{pos}', encoding='latin-1') as f:
        for line in f:
            if line.startswith('  '): continue
            w = line.split()[0]
            if re.fullmatch(r'[a-z]{3,15}', w):
                base_words.add((w, pos))
# drop words that only exist capitalised in WordNet data (proper nouns)
lower_lemmas = set()
for s in syn.values():
    for w in s['words']:
        if w[:1].islower(): lower_lemmas.add(w.lower())
verbs = {w for w, p in base_words if p == 'verb'}
nouns = {w for w, p in base_words if p == 'noun' and w in lower_lemmas}
adjs = {w for w, p in base_words if p == 'adj'}
lemmas = {w for w, p in base_words if p != 'noun'} | nouns

def inflections(w, pos):
    out = []
    if pos in ('noun', 'verb'):
        if re.search(r'(s|x|z|ch|sh)$', w): out.append(w + 'es')
        elif re.search(r'[^aeiou]y$', w): out.append(w[:-1] + 'ies')
        else: out.append(w + 's')
    if pos == 'verb':
        if w.endswith('e'): out += [w + 'd', w[:-1] + 'ing']
        elif re.search(r'[^aeiou]y$', w): out += [w[:-1] + 'ied', w + 'ing']
        else:
            out += [w + 'ed', w + 'ing']
            if re.search(r'[^aeiou][aeiou][bdgklmnprt]$', w): out += [w + w[-1] + 'ed', w + w[-1] + 'ing']
    if pos == 'adj':
        if w.endswith('e'): out += [w + 'r', w + 'st']
        elif re.search(r'[^aeiou]y$', w): out += [w[:-1] + 'ier', w[:-1] + 'iest']
        else: out += [w + 'er', w + 'est']
    return out

dictionary = {}
for w in lemmas:
    dictionary[w] = z(w)
for w in nouns:
    for x in inflections(w, 'noun'):
        if z(x) >= 1.8: dictionary[x] = z(x)
for w in verbs:
    for x in inflections(w, 'verb'):
        if z(x) >= 1.8: dictionary[x] = z(x)
for w in adjs:
    if len(w) <= 7:
        for x in inflections(w, 'adj'):
            if z(x) >= 2.2: dictionary[x] = z(x)
dictionary = {w: f for w, f in dictionary.items() if w not in BAD and clean(w)}
print('dictionary words', len(dictionary), file=sys.stderr)
words = list(dictionary.items())

def word_items(ws):
    return [(nice(w), f, []) for w, f in ws]

def bucket(keyfn):
    b = collections.defaultdict(list)
    for w, f in words:
        for k in keyfn(w):
            b[k].append((w, f))
    return b

def q(s):
    return s.upper()

# starts with X ... ends with Y
b = bucket(lambda w: [(w[0], w[-1])] if len(w) >= 4 else [])
for (a, c), ws in b.items():
    pass  # too large mostly; handled with two-letter endings below
b = bucket(lambda w: [(w[:2], w[-2:])] if len(w) >= 5 else [])
for (a, c), ws in b.items():
    add('word-starts-ends', f'Name a word that starts with {q(a)} and ends with {q(c)}', word_items(ws), 8, 300, 3.0)
b = bucket(lambda w: [(w[0], w[-3:])] if len(w) >= 6 else [])
for (a, c), ws in b.items():
    add('word-starts-ends', f'Name a word that starts with {q(a)} and ends with {q(c)}', word_items(ws), 8, 300, 3.0)
# ends in suffix
b = bucket(lambda w: [w[-k:] for k in (3, 4, 5) if len(w) > k + 2])
for suf, ws in b.items():
    add('word-ending', f'Name a word that ends in -{suf.upper()}', word_items(ws), 10, 350, 3.2)
# starts with prefix
b = bucket(lambda w: [w[:k] for k in (3, 4) if len(w) > k + 2])
for pre, ws in b.items():
    add('word-prefix', f'Name a word that starts with {q(pre)}', word_items(ws), 10, 350, 3.2)
# contains a trigram/quadgram (not at the start or the end)
b = bucket(lambda w: list({w[i:i + k] for k in (3, 4) for i in range(1, len(w) - k)}))
for g, ws in b.items():
    if len(set(g)) == 1: continue
    add('word-contains', f'Name a word containing {q(g)} somewhere in the middle', word_items(ws), 10, 300, 3.2)
# exact length with start letters
b = bucket(lambda w: [(len(w), w[:2])] if 5 <= len(w) <= 8 else [])
for (n, pre), ws in b.items():
    add('word-length', f'Name a {n}-letter word that starts with {q(pre)}', word_items(ws), 8, 300, 3.2)
# double letters
b = bucket(lambda w: list({(w[i], w[0]) for i in range(len(w) - 1) if w[i] == w[i + 1]}))
for (d, first), ws in b.items():
    add('word-double', f'Name a word that starts with {q(first)} and contains a double {q(d)} ({q(d * 2)})', word_items(ws), 8, 300, 3.2)
# only one vowel type
for v in 'aeiou':
    for first in 'bcdfghjklmnprstw':
        ws = [(w, f) for w, f in words if w[0] == first and len(w) >= 5 and set(re.findall('[aeiouy]', w)) == {v}]
        add('word-vowel', f'Name a word of 5+ letters starting with {q(first)} whose only vowel is {q(v)}', word_items(ws), 8, 300, 2.8)


# rhymes (CMU Pronouncing Dictionary)
import pronouncing
pronouncing.init_cmu()
rhyme_groups = collections.defaultdict(set)
for w, ph in pronouncing.pronunciations:
    if w in dictionary and "'" not in w:
        rhyme_groups[pronouncing.rhyming_part(ph)].add(w)
for w, f in sorted(words, key=lambda x: -x[1])[:6000]:
    if len(w) < 3: continue
    phs = pronouncing.phones_for_word(w)
    if not phs: continue
    group = rhyme_groups.get(pronouncing.rhyming_part(phs[0]), set()) - {w}
    # a rhyme must not just be the word with a prefix ("cat" / "bobcat" is fine, "do" / "redo" isn't)
    ws = [(x, dictionary[x]) for x in group if not x.endswith(w) and not w.endswith(x)]
    add('word-rhyme', f'Name a word that rhymes with {w.upper()}', word_items(ws), 8, 300, 3.5)

# compound words: "Name a compound word that starts with FIRE" (fireplace, firefly ...)
common = {w for w, f in words if f >= 3.9 and len(w) >= 3}
starts, ends = collections.defaultdict(list), collections.defaultdict(list)
for w, f in words:
    if len(w) < 6: continue
    for i in range(3, len(w) - 2):
        a, b = w[:i], w[i:]
        if a in common and b in common and len(b) >= 3:
            starts[a].append((w, f)); ends[b].append((w, f))
for a, ws in starts.items():
    add('word-compound', f'Name a compound word that starts with {a.upper()} (like {a.upper()} + another word)', word_items(ws), 8, 250, 2.6)
for b, ws in ends.items():
    if b.endswith('s') and b[:-1] in common: continue  # plural endings ("-overs") make false compounds
    add('word-compound', f'Name a compound word that ends with {b.upper()}', word_items(ws), 8, 250, 2.6)

# fill in the blank from WordNet two-word terms: "ICE ___" -> ice cream, ice age ...
first, last = collections.defaultdict(list), collections.defaultdict(list)
for s_ in syn.values():
    if BAD_GLOSS.search(s_['gloss']): continue
    for w in s_['words']:
        parts = w.split(' ')
        if len(parts) == 2 and all(re.fullmatch(r'[a-z]{2,}', p) for p in parts):
            first[parts[0]].append((w, phrase_pop(w) + 0.0)); last[parts[1]].append((w, phrase_pop(w)))
for a, ws in first.items():
    if z(a) >= 3.8:
        add('phrase-blank', f'Fill in the blank: {a.upper()} ___', [(nice(w), f, [w.replace(' ', '')]) for w, f in ws], 8, 250, 2.4)
for b, ws in last.items():
    if z(b) >= 3.8:
        add('phrase-blank', f'Fill in the blank: ___ {b.upper()}', [(nice(w), f, [w.replace(' ', '')]) for w, f in ws], 8, 250, 2.4)

# ---------------------------------------------------------------- geography
gc = geonamescache.GeonamesCache()
TERRITORIES = set('AS AI AQ AW AX BL BM BQ BV CC CK CW CX EH FK FO GF GG GI GL GP GS GU HK HM IM IO JE KY MF MO MP MQ MS '
                  'NC NF NU PF PM PN PR RE SH SJ SX TC TF TK UM VG VI WF YT CS AN XK'.split())
CONTINENT = {'AF': 'Africa', 'AS': 'Asia', 'EU': 'Europe', 'NA': 'North America', 'SA': 'South America', 'OC': 'Oceania'}
COMMON = {'Czechia': ['Czech Republic'], 'Myanmar': ['Burma'], 'Eswatini': ['Swaziland'], 'Ivory Coast': ["Cote d'Ivoire"],
          'Cabo Verde': ['Cape Verde'], 'North Macedonia': ['Macedonia'], 'Timor Leste': ['East Timor', 'Timor-Leste'],
          'United States': ['USA', 'United States of America', 'America'], 'United Kingdom': ['UK', 'Great Britain', 'Britain'],
          'Republic of the Congo': ['Congo-Brazzaville', 'Congo'], 'Democratic Republic of the Congo': ['DRC', 'DR Congo', 'Congo-Kinshasa'],
          'Turkey': ['Turkiye'], 'Vatican': ['Vatican City', 'Holy See'], 'Palestinian Territory': ['Palestine'],
          'South Korea': ['Korea', 'Republic of Korea'], 'North Korea': ['DPRK'], 'Netherlands': ['Holland', 'The Netherlands']}
countries = [c for k, c in gc.get_countries().items() if k not in TERRITORIES and c.get('population', 0) > 0]
byiso = {c['iso']: c for c in countries}
def citem(c):
    name = c['name']
    return (name, z(name), COMMON.get(name, []))
def cadd(text, cs, mn=6, mx=300, top=2.5):
    add('geo-country', text, [citem(c) for c in cs], mn, mx, top)

for cont, label in CONTINENT.items():
    cadd(f'Name a country in {label}', [c for c in countries if c['continentcode'] == cont], 6, 300)
for L in 'abcdefghijklmnopqrstuvwxyz':
    cadd(f'Name a country whose English name starts with {L.upper()}', [c for c in countries if norm(c['name']).startswith(L)])
    cadd(f'Name a country whose English name ends with the letter {L.upper()}', [c for c in countries if norm(c['name']).endswith(L)])
    cadd(f'Name a country whose capital city starts with {L.upper()}', [c for c in countries if c.get('capital') and norm(c['capital']).startswith(L)])
    for cont, label in CONTINENT.items():
        cadd(f'Name a country in {label} whose name starts with {L.upper()}', [c for c in countries if c['continentcode'] == cont and norm(c['name']).startswith(L)], 6)
for n in range(4, 15):
    cadd(f'Name a country whose English name is exactly {n} letters long (ignoring spaces)', [c for c in countries if len(norm(c['name'])) == n])
for c in countries:
    bs = [byiso[b] for b in (c.get('neighbours') or '').split(',') if b in byiso]
    if len(bs) >= 6:
        cadd(f"Name a country that shares a land border with {c['name']}", bs)
import pycountry
langs = collections.defaultdict(list)
for c in countries:
    first = (c.get('languages') or '').split(',')[0].split('-')[0]
    lang = pycountry.languages.get(alpha_2=first) if len(first) == 2 else None
    if lang: langs[lang.name].append(c)
for l, cs in langs.items():
    cadd(f'Name a country whose main language is {l}', cs)
curs = collections.defaultdict(list)
for c in countries:
    if c.get('currencyname'): curs[c['currencyname']].append(c)
for k, cs in curs.items():
    cadd(f'Name a country whose currency is called a {k.lower()}', cs)
cadd('Name an island nation', [c for c in countries if not c.get('neighbours')], 6, 300)
for cont, label in CONTINENT.items():
    cs = [c for c in countries if c['continentcode'] == cont and c.get('capital')]
    add('geo-capital', f'Name the capital city of a country in {label}', [(c['capital'], z(c['capital']), []) for c in cs], 6, 300, 2.0)

cities = list(gc.get_cities().values())
ccname = {k: v['name'] for k, v in gc.get_countries().items()}
states = gc.get_us_states()
fips2code = {v['code']: v['name'] for v in states.values()}
def city_item(c):
    al = [a for a in c.get('alternatenames', []) if a.isascii() and re.fullmatch(r"[A-Za-z .'-]{4,40}", a)]
    al = [a for a in al if norm(a) != norm(c['name'])][:4]
    return (c['name'], math.log10(max(c['population'], 1)), al)
bycountry = collections.defaultdict(list)
for c in cities: bycountry[c['countrycode']].append(c)
THE = {'United States', 'United Kingdom', 'Netherlands', 'Philippines', 'Czech Republic', 'Dominican Republic', 'Central African Republic',
       'Bahamas', 'Gambia', 'Maldives', 'Seychelles', 'United Arab Emirates', 'Democratic Republic of the Congo', 'Republic of the Congo', 'Comoros', 'Marshall Islands', 'Solomon Islands'}
def cname(cc):
    n = ccname.get(cc, cc)
    return ('the ' + n) if n in THE else n
for cc, cs in bycountry.items():
    if cc not in ccname: continue
    if len(cs) >= 8:
        add('geo-city', f'Name a city in {cname(cc)}', [city_item(c) for c in cs], 8, 500, pop_is_zipf=False)
    if len(cs) >= 40:
        bl = collections.defaultdict(list)
        for c in cs:
            k = norm(c['name'])[:1]
            if k.isalpha(): bl[k].append(c)
        for L, xs in bl.items():
            add('geo-city-letter', f'Name a city in {cname(cc)} that starts with {L.upper()}', [city_item(c) for c in xs], 8, 400, pop_is_zipf=False)
us = collections.defaultdict(list)
for c in bycountry['US']:
    us[c['admin1code']].append(c)
for code, cs in us.items():
    if code in fips2code:
        add('geo-us-city', f'Name a city or town in {fips2code[code]}', [city_item(c) for c in cs], 8, 500, pop_is_zipf=False)
st = list(states.values())
for L in 'abcdefghijklmnopqrstuvwxyz':
    pass
add('geo-us-state', 'Name a U.S. state', [(s['name'], z(s['name']), [s['code']]) for s in st], 6, 60, 2.0)

# ---------------------------------------------------------------- select
fam_sizes = {k: len(v) for k, v in prompts.items()}
print(json.dumps(fam_sizes, indent=1), file=sys.stderr)
print('total candidates', sum(fam_sizes.values()), file=sys.stderr)

# Quotas keep a lively mix. Unused quota is redistributed proportionally.
QUOTA = {'wordnet-type': 2600, 'wordnet-instance': 400, 'wordnet-type-letter': 1300, 'wordnet-instance-letter': 300,
         'geo-country': 450, 'geo-capital': 30, 'geo-city': 160, 'geo-city-letter': 500, 'geo-us-city': 50, 'geo-us-state': 1,
         'word-starts-ends': 1300, 'word-ending': 1000, 'word-prefix': 800, 'word-contains': 700, 'word-length': 500,
         'word-double': 200, 'word-vowel': 110, 'word-rhyme': 2000, 'word-compound': 1500, 'phrase-blank': 1500}
for k, v in prompts.items():
    seen_k, uniq = set(), []
    for p in v:
        if p['text'] not in seen_k:
            seen_k.add(p['text']); uniq.append(p)
    random.shuffle(uniq); prompts[k] = uniq
chosen, seen_text = [], set()
remaining = TARGET
take = {k: min(QUOTA.get(k, 0), len(v)) for k, v in prompts.items()}
short = TARGET - sum(take.values())
while short > 0:
    spare = {k: len(prompts[k]) - take[k] for k in prompts if len(prompts[k]) > take[k]}
    if not spare: break
    tot = sum(spare.values())
    for k, s in spare.items():
        extra = min(s, max(1, round(short * s / tot)))
        take[k] += extra; short -= extra
        if short <= 0: break
while sum(take.values()) > TARGET:
    k = max(take, key=lambda k: take[k] - QUOTA.get(k, 0))
    take[k] -= 1
for k, n in take.items():
    for p in prompts[k][:n]:
        key = p['text']
        if key in seen_text: continue
        seen_text.add(key); chosen.append(p)
random.shuffle(chosen)
with open(OUT, 'w') as f:
    for i, p in enumerate(chosen, 1):
        p['id'] = f'e{i:05d}'
        f.write(json.dumps({'id': p['id'], 'family': p['family'], 'text': p['text'], 'answers': p['answers']}, ensure_ascii=False) + '\n')
print('wrote', len(chosen), json.dumps(collections.Counter(p['family'] for p in chosen)), file=sys.stderr)
