"""Minimal WordNet 3.x noun parser (data.noun / index.noun from the wordnet-db package)."""
import os, re
DICT = os.path.join(os.path.dirname(__file__), 'node_modules/wordnet-db/dict')
LEXNAMES = {}

def load():
    with open(os.path.join(os.path.dirname(__file__), 'lexnames')) as f:
        for line in f:
            n, name, _ = line.split()
            LEXNAMES[int(n)] = name
    syn = {}
    with open(os.path.join(DICT, 'data.noun'), encoding='latin-1') as f:
        for line in f:
            if line.startswith('  '):
                continue
            body, _, gloss = line.partition(' | ')
            t = body.split()
            off, lex = t[0], int(t[1])
            wc = int(t[3], 16)
            words = [t[4 + 2 * i] for i in range(wc)]
            i = 4 + 2 * wc
            pc = int(t[i]); i += 1
            ptrs = []
            for _ in range(pc):
                sym, toff, pos = t[i], t[i + 1], t[i + 2]
                i += 4
                if pos == 'n':
                    ptrs.append((sym, toff))
            words = [re.sub(r'\(.*?\)$', '', w).replace('_', ' ') for w in words]
            syn[off] = {'off': off, 'lex': LEXNAMES[lex], 'words': words, 'ptrs': ptrs, 'gloss': gloss.strip()}
    # first-sense lookup: lemma -> list of offsets in frequency order
    senses = {}
    with open(os.path.join(DICT, 'index.noun'), encoding='latin-1') as f:
        for line in f:
            if line.startswith('  '):
                continue
            t = line.split()
            lemma = t[0].replace('_', ' ')
            n = int(t[2]); pc = int(t[3])
            offs = t[6 + pc:6 + pc + n]
            senses[lemma] = offs
    return syn, senses
