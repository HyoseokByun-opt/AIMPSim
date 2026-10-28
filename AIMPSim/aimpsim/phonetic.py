"""Spelling and pronunciation matching for Korean and English words.

People type fast: "애폭시" for 에폭시, "실리까" for 실리카, "alumna" for
alumina, "sillica" for silica. A word is matched against the lexicon on
three levels, the best of which counts:

1. the letters as written (Korean decomposed into jamo, so that one wrong
   vowel costs one jamo, not a whole syllable);
2. a phonetic key in the same script - Korean: ㅐ = ㅔ, tense and aspirated
   consonants as their plain ones (ㄲ ㅋ -> ㄱ), final consonants as they
   sound (ㅅ ㅈ ㅊ ㅌ ㅎ -> ㄷ), a silent ㅇ dropped; English: ph = f,
   c before e/i/y = s, ck = k, doubled letters once, a final silent e;
3. a coarse key shared by both scripts (consonant classes K T P S J L M N H
   and five vowels), so that a Korean transliteration finds an English name
   and the other way round; an epenthetic ㅡ (그라파이트) is dropped.

The distance is the Damerau-Levenshtein distance (a swap of two neighbours
costs one), as a similarity 1 - d / longer length.
"""
from __future__ import annotations

import functools
import re
import unicodedata

CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
JONG = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ",
        "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]

_HANGUL = re.compile(r"[가-힣]")


def has_hangul(s):
    return bool(_HANGUL.search(s or ""))


def syllables(s):
    """(initial, vowel, final) of each Hangul syllable; other characters as
    (char, '', '')."""
    out = []
    for ch in s:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7A3:
            c = o - 0xAC00
            out.append((CHO[c // 588], JUNG[(c % 588) // 28], JONG[c % 28]))
        else:
            out.append((ch, "", ""))
    return out


def jamo(s):
    """The jamo sequence of a string (other characters kept)."""
    return "".join(a + b + c for a, b, c in syllables(s))


# ---- Korean phonetic key (same script) ------------------------------------
_K_CHO = {"ㄲ": "ㄱ", "ㅋ": "ㄱ", "ㄸ": "ㄷ", "ㅌ": "ㄷ", "ㅃ": "ㅂ", "ㅍ": "ㅂ", "ㅆ": "ㅅ", "ㅉ": "ㅈ", "ㅊ": "ㅈ",
          "ㅇ": ""}
_K_JUNG = {"ㅐ": "ㅔ", "ㅒ": "ㅖ", "ㅙ": "ㅞ", "ㅚ": "ㅞ", "ㅢ": "ㅣ"}
_K_JONG = {"ㄲ": "ㄱ", "ㅋ": "ㄱ", "ㄳ": "ㄱ", "ㄺ": "ㄱ", "ㄵ": "ㄴ", "ㄶ": "ㄴ", "ㅅ": "ㄷ", "ㅆ": "ㄷ", "ㅈ": "ㄷ",
           "ㅊ": "ㄷ", "ㅌ": "ㄷ", "ㅎ": "ㄷ", "ㄼ": "ㄹ", "ㄽ": "ㄹ", "ㄾ": "ㄹ", "ㅀ": "ㄹ", "ㄻ": "ㅁ", "ㅍ": "ㅂ",
           "ㅄ": "ㅂ", "ㄿ": "ㅂ"}


def ko_key(s):
    out = []
    for a, b, c in syllables(s):
        if not b:
            out.append(a)
            continue
        out.append(_K_CHO.get(a, a) + _K_JUNG.get(b, b) + _K_JONG.get(c, c))
    return "".join(out)


# ---- English phonetic key (same script) -----------------------------------
def en_key(s):
    w = re.sub(r"[^a-z]", "", (s or "").lower())
    if len(w) > 3 and w.endswith("e") and w[-2] not in "aeiou":
        w = w[:-1]
    w = (w.replace("ph", "f").replace("ck", "k").replace("qu", "kw").replace("q", "k")
         .replace("x", "ks").replace("z", "s").replace("y", "i"))
    w = re.sub(r"c(?=[eiy])", "s", w).replace("c", "k")
    return re.sub(r"(.)\1+", r"\1", w)


# ---- coarse key shared by both scripts ------------------------------------
_C_CHO = {"ㄱ": "K", "ㄲ": "K", "ㅋ": "K", "ㄷ": "T", "ㄸ": "T", "ㅌ": "T", "ㅂ": "P", "ㅃ": "P", "ㅍ": "P",
          "ㅅ": "S", "ㅆ": "S", "ㅈ": "J", "ㅉ": "J", "ㅊ": "J", "ㄹ": "L", "ㅁ": "M", "ㄴ": "N", "ㅎ": "H", "ㅇ": ""}
_C_JUNG = {"ㅏ": "A", "ㅑ": "A", "ㅘ": "A", "ㅐ": "E", "ㅒ": "E", "ㅔ": "E", "ㅖ": "E", "ㅙ": "E", "ㅚ": "E", "ㅞ": "E",
           "ㅓ": "O", "ㅕ": "O", "ㅗ": "O", "ㅛ": "O", "ㅝ": "O", "ㅜ": "U", "ㅠ": "U", "ㅡ": "", "ㅣ": "I",
           "ㅟ": "I", "ㅢ": "I"}
_C_JONG = {"ㄱ": "K", "ㄲ": "K", "ㅋ": "K", "ㄴ": "N", "ㄷ": "T", "ㅅ": "T", "ㅆ": "T", "ㅈ": "T", "ㅊ": "T",
           "ㅌ": "T", "ㅎ": "T", "ㄹ": "L", "ㅁ": "M", "ㅂ": "P", "ㅍ": "P", "ㅇ": "N"}


def coarse_ko(s):
    out = []
    for a, b, c in syllables(s):
        if not b:
            out.append(coarse_en(a))
            continue
        out.append(_C_CHO.get(a, "") + _C_JUNG.get(b, "") + "".join(_C_JONG.get(x, "") for x in c))
    return re.sub(r"(.)\1+", r"\1", "".join(out))


def coarse_en(s):
    w = re.sub(r"[^a-z]", "", (s or "").lower())
    if len(w) > 3 and w.endswith("e") and w[-2] not in "aeiou":
        w = w[:-1]
    rep = [("tion", "SON"), ("sh", "S"), ("ch", "J"), ("ph", "P"), ("th", "T"), ("ck", "K"), ("qu", "KU"),
           ("ng", "N"), ("x", "KS")]
    for a, b in rep:
        w = w.replace(a, b)
    w = re.sub(r"c(?=[eiy])", "S", w)
    table = {"b": "P", "p": "P", "f": "P", "v": "P", "d": "T", "t": "T", "k": "K", "c": "K", "g": "K", "q": "K",
             "s": "S", "z": "S", "j": "J", "l": "L", "r": "L", "m": "M", "n": "N", "h": "H", "w": "U", "y": "I",
             "a": "A", "e": "E", "i": "I", "o": "O", "u": "U"}
    w = "".join(table.get(ch, ch) for ch in w)
    return re.sub(r"(.)\1+", r"\1", w)


def coarse(s):
    return coarse_ko(s) if has_hangul(s) else coarse_en(s)


# ---- distance ---------------------------------------------------------------
def dl_distance(a, b):
    """Damerau-Levenshtein (optimal string alignment) distance."""
    la, lb = len(a), len(b)
    if not la:
        return lb
    if not lb:
        return la
    prev2 = None
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if prev2 is not None and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[lb]


def sim(a, b):
    if not a or not b:
        return 0.0
    return 1.0 - dl_distance(a, b) / max(len(a), len(b))


def squash(s):
    """Lower case, compatibility forms folded, no spaces, hyphens or dots."""
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[\s\-_.·,/()\[\]'\"]+", "", s)


@functools.lru_cache(maxsize=200000)
def keys(s):
    """The squashed word and its keys, computed once per word."""
    w = squash(s)
    h = has_hangul(w)
    return (w, h, jamo(w) if h else w, ko_key(w) if h else en_key(w), coarse(w))


def _close(a, b, floor=0.55):
    """sim(a, b), or 0 when the lengths alone keep it below `floor`."""
    la, lb = len(a), len(b)
    if not la or not lb or abs(la - lb) > (1.0 - floor) * max(la, lb):
        return 0.0
    return sim(a, b)


@functools.lru_cache(maxsize=400000)
def similarity(word, alias):
    """How alike a typed word and a lexicon alias are (0-1), by the best of
    the letters, the phonetic key and the cross-script key."""
    w, hw, lw, pw, cw = keys(word)
    a, ha, la, pa, ca = keys(alias)
    if not w or not a:
        return 0.0
    if w == a:
        return 1.0
    if hw == ha:
        return max(_close(lw, la), 0.97 * _close(pw, pa))
    return 0.9 * _close(cw, ca)
