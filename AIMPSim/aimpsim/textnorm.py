"""Text normalisation before parsing.

- Unicode compatibility forms folded (full-width digits and letters, ％, µ),
  every tilde and dash between two numbers made "~", the micro sign "u".
- Korean numerals written out turned into digits - "오십오" -> 55,
  "영점오오" -> 0.55, "삼분의 일" -> 1/3, "다섯 단계" -> 5 단계 - but only
  where they are a number: a run of numeral syllables that parses as one
  (digits joined by 십 백 천 and an optional 점) and is not part of another
  word ("구형", "이상", "사이" stay as they are); a single syllable only
  before a unit or a count word ("삼 단계", "일 퍼센트").
- English number words: "fifty five" -> 55, "half" -> 0.5.
- "절반", "반반" -> 50 %.
"""
from __future__ import annotations

import re
import unicodedata

KO_DIGIT = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
KO_PLACE = {"십": 10, "백": 100, "천": 1000}
KO_NATIVE = {"하나": 1, "한": 1, "둘": 2, "두": 2, "셋": 3, "세": 3, "넷": 4, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7,
             "여덟": 8, "아홉": 9, "열": 10, "스무": 20, "스물": 20}
# what may follow a written-out number
UNIT_WORDS = ("퍼센트", "프로", "퍼", "마이크로", "마이크론", "미크론", "나노", "밀리", "단계", "수준", "레벨", "개",
              "번", "회", "코어", "스레드", "쓰레드", "부피", "중량", "케이스", "가지", "배", "도")
PARTICLE_AFTER = ("만큼", "정도", "쯤", "이", "가", "을", "를", "은", "는", "에", "의", "로", "으로", "와", "과", "까지",
                  "부터", "에서", "씩", "%")
EN_NUM = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
          "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
          "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
          "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}

_NUMERAL_RUN = re.compile(r"[영공일이삼사오육칠팔구십백천점]+")


def parse_ko_number(s):
    """A Sino-Korean numeral ('오십오', '영점오', '천이백') as a float, or
    None when the run is not one number."""
    whole, dot, frac = s.partition("點" if "點" in s else "점")
    if dot and not frac:
        return None
    value, cur, last = 0, None, 10 ** 9
    if not whole and not frac:
        return None
    for ch in whole:
        if ch in KO_DIGIT:
            if cur is not None:
                return None                       # two digits with no place between
            cur = KO_DIGIT[ch]
        elif ch in KO_PLACE:
            p = KO_PLACE[ch]
            if p >= last:
                return None
            value += (cur if cur is not None else 1) * p
            cur, last = None, p
        else:
            return None
    if cur is not None:
        value += cur
    if frac:
        if any(ch not in KO_DIGIT for ch in frac):
            return None
        return float(f"{value}." + "".join(str(KO_DIGIT[ch]) for ch in frac))
    return float(value)


def _fmt(v):
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def _num_any(s):
    try:
        return float(s)
    except ValueError:
        return parse_ko_number(s)


def korean_numerals(text):
    # "삼분의 일" / "3분의 1" -> 1/3 (before the runs, which would see "삼분")
    def frac(m):
        d, n = _num_any(m.group(1)), _num_any(m.group(2))
        return m.group(0) if d is None or n is None or d == 0 else f"{_fmt(n)}/{_fmt(d)}"
    text = re.sub(r"(?<![가-힣])([영공일이삼사오육칠팔구십백천점\d.]+)\s*분의\s*([영공일이삼사오육칠팔구십백천점\d.]+)",
                  frac, text)
    out, i = [], 0
    for m in _NUMERAL_RUN.finditer(text):
        a, b = m.span()
        prev = text[a - 1] if a > 0 else " "
        if "가" <= prev <= "힣":
            continue                                  # inside a word
        rest = text[b:].lstrip()
        nxt = text[b] if b < len(text) else " "
        run = m.group()
        v = parse_ko_number(run)
        if v is None:
            continue
        follows_unit = rest.startswith(UNIT_WORDS) or rest[:1] in ("%", "~", "-")
        if "가" <= nxt <= "힣" and not text[b:].startswith(UNIT_WORDS + PARTICLE_AFTER):
            continue                                  # the run is the start of another word
        if len(run) == 1 and not follows_unit:
            continue                                  # one syllable: a number only before a unit
        out.append(text[i:a])
        out.append(_fmt(v))
        i = b
    out.append(text[i:])
    text = "".join(out)
    # "3분의 1" / "삼분의 일" -> 1/3
    text = re.sub(r"(\d+(?:\.\d+)?)\s*분의\s*(\d+(?:\.\d+)?)", lambda m: f"{m.group(2)}/{m.group(1)}", text)
    # native counts before a count word: "다섯 단계" -> "5 단계"
    text = re.sub(r"(?<![가-힣])(" + "|".join(sorted(KO_NATIVE, key=len, reverse=True)) + r")\s*"
                  r"(단계|수준|레벨|개|번|가지|케이스|코어|회)",
                  lambda m: f"{KO_NATIVE[m.group(1)]} {m.group(2)}", text)
    # halves
    text = re.sub(r"반반", "50% 50%", text)
    text = re.sub(r"절반", "50%", text)
    return text


def english_numbers(text):
    words = list(EN_NUM) + ["hundred", "half"]

    def conv(m):
        toks = re.split(r"[\s-]+", m.group(0).lower())
        if toks == ["half"]:
            return "0.5"
        total, cur = 0, 0
        for t in toks:
            if t == "hundred":
                cur = (cur or 1) * 100
            elif t in EN_NUM:
                cur += EN_NUM[t]
            elif t == "and":
                continue
        return str(total + cur)
    pat = r"\b(?:" + "|".join(words) + r")(?:[\s-]+(?:and[\s-]+)?(?:" + "|".join(words) + r"))*\b"
    return re.sub(pat, conv, text, flags=re.IGNORECASE)


def normalize(text):
    """The text with compatibility forms folded, ranges marked and numbers
    written out turned into digits; case kept."""
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("µ", "u").replace("μ", "u").replace("㎛", "um").replace("㎚", "nm").replace("㎜", "mm")
    t = re.sub(r"[‐-―−]", "-", t)
    t = re.sub(r"[~∼〜～]", "~", t)
    # a decimal comma: "0,55" (a thousands comma has three digits after it)
    t = re.sub(r"(?<!\d)(\d),(\d{1,2})(?!\d)", r"\1.\2", t)
    t = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t)
    t = korean_numerals(t)
    t = english_numbers(t)
    # a dash between two numbers is a range: "40-60%" (not "SU-8", "FR-4")
    t = re.sub(r"(?<![A-Za-z\-])(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", r"\1~\2", t)
    return re.sub(r"[ \t]+", " ", t).strip()
