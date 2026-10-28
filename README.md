<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/aimpsim_logo_dark.png">
    <img src="docs/images/aimpsim_logo_light.png" alt="AIMPSim - MPSim with requests in words" width="62%">
  </picture>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.2.0-8250df" alt="version 0.2.0">
  <a href="https://github.com/HyoseokByun-opt/MPSim"><img src="https://img.shields.io/badge/MPSim-5.6.3-0b62c4" alt="MPSim 5.6.3 inside"></a>
  <img src="https://img.shields.io/badge/local%20model-Qwen3.5--2B%20%C2%B7%20offline-6e40c9" alt="local model Qwen3.5-2B, offline">
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011%20x64-555555" alt="Windows 10 | 11 x64">
  <img src="https://img.shields.io/badge/license-MIT-2da44e" alt="MIT licence">
  <a href="#verification"><img src="https://img.shields.io/badge/tests-every%20input%20checked-2da44e" alt="tests"></a>
</p>

<p align="center">
  <b>AIMPSim</b> is <a href="https://github.com/HyoseokByun-opt/MPSim">MPSim</a> with an <b>AI</b> tab: type the case the
  way you would say it, and it becomes an MPSim run, a DOE study, a calibration or an optimisation - read by a local
  language model, checked against the sentence by rules, summarised before anything runs.
</p>

<p align="center">
  <a href="https://hyoseokbyun-opt.github.io/AIMPSim/">Website</a> ·
  <a href="#how-a-request-is-read">How it reads</a> ·
  <a href="#what-the-ai-tab-reads">What it reads</a> ·
  <a href="#the-local-model">The model</a> ·
  <a href="#verification">Verification</a> ·
  <a href="#installation">Installation</a> ·
  <a href="AIMPSim/docs/GUIDE_KO.md">Guide (Korean)</a>
</p>

<p align="center">
  <img src="docs/images/aimpsim_tab.png" alt="The AI tab: a casual request with a correction, the summary of what will run, and the questions with their recommended answers" width="100%">
</p>

> 에폭시에 알루미나 55%, 아니 60%로 해줘. 열이 얼마나 잘 빠지는지 봐줘<br>
> epoxy with alumina, 55%, actually make that 60%, thermal conductivity<br>
> 알루미나랑 질화붕소 중에 에폭시에 30% 넣었을 때 어느 쪽이 열전도도 더 높은지 비교해줘

Before anything runs, the tab shows what was read from the sentence, what was calculated or corrected, where the
model and the rules read differently, which settings were chosen for the problem and why, and the RVE MPSim plans
for it. **Run** starts it; **Open in the tabs to edit** puts the case into MPSim's tabs instead. Everything runs on the
PC itself, offline.

## Two editions

| | MPSim | AIMPSim |
|---|---|---|
| Analyses, solvers, checks, guides | the same | the same |
| AI tab (requests in words) | - | yes |
| Local language model | - | included (Qwen3.5-2B, Apache 2.0; llama.cpp, MIT) |
| Repository | HyoseokByun-opt/MPSim | HyoseokByun-opt/AIMPSim |

Every change of MPSim is published to both repositories, so AIMPSim always carries the latest MPSim. The reading
engine lives in the folder `AIMPSim/`; everything else is MPSim. Install and start AIMPSim exactly as MPSim
(`1_INSTALL.bat` or the offline package, then `2_RUN_LOCAL.bat`); the user guide of MPSim applies unchanged, and
[AIMPSim/docs/GUIDE_KO.md](AIMPSim/docs/GUIDE_KO.md) describes the AI tab.

## How a request is read

1. **The model reads it.** Every message, a follow-up with the request so far, goes to the local model, which
   answers in a fixed JSON form (materials, contents or amounts, shapes and sizes, material values given, analyses,
   the task, DOE ranges, measurements, settings). It understands what rules cannot: a correction ("55%, no, 60%"),
   a word taken back ("not alumina", "skip the thermal part"), a property described instead of named ("how well
   heat gets out", "will it flow"), a purpose ("for a TIM", "a 5G substrate").
2. **The rules check it.** A material must be named in the sentence (as written, by spelling or by sound); a number
   must be in the sentence or follow from its numbers by a calculation that is shown (4:6 -> 60 %, 150 g in 100 g
   -> 60 wt%, 500 nm -> 0.5 um, a quarter -> 25 %); a material value must be the user's own; an analysis needs a
   word that points to it. Whatever fails is dropped and asked for.
3. **The rules fill in.** What the rules read exactly and the model left out comes back, unless the sentence takes
   something back. A size the rules read with its unit stands.
4. **The summary shows it.** Where the model and the rules read differently, the model's reading is used and the
   difference is listed; calculations, dropped values and material values given are listed too.
5. **The questions follow** as before: what only the user can give, with recommended answers for the rest.

Without the model (no model in `AIMPSim/llm/`, or `{"llm": "off"}` in `aimpsim_config.json`) the rules read requests
alone, as in 0.1.

## What the AI tab reads

| Item | Examples | Rule |
|---|---|---|
| Matrix | 에폭시, 실리콘 수지, PI, BT 레진, epoxy, silicone | a resin word after it, or the polymer of the library; else the material without a content ("알루미늄에 SiC 50%") |
| Fillers | 구형 알루미나, 판상 BN, 은 플레이크, glass fibre | every material of the MPSim library (68), by Korean and English names, formulae and common abbreviations |
| Content | 55%, 55 vol%, 55 부피%, 30 wt%, 30 중량%, 30 phr, 0.55, 0.55만큼, 오십오 퍼센트, 영점오오, 1/3, 삼분의 일, 절반, fifty five percent | see below |
| Size | 5um, 5 µm, 5 마이크로, 5미크론, 오 마이크로, 500 nm, 입경 5, D50 5 | a number after a size word without a unit is taken in µm, and the summary says so |
| Shape | 구형, 판상, 플레이크, 섬유, 불규칙, 파쇄, 큐브; spherical, flake, fibre, irregular | platelets as oblate spheroids (aspect 0.2, or 1/AR), fibres as cylinders (10 diameters, or AR), irregular grains as random polyhedra |
| Analyses | 열전도도, 전기전도도, 유전율, Dk/Df, CTE, 탄성계수, 점도, 흡습, EMI 차폐, 투자율, 휨, 줄 발열, ... | all 21 MPSim analyses; "전도도" alone is asked (thermal or electrical) |
| Task | 40~60%, 40, 50, 60%, 40/50/60%, 5단계, 10%씩 → DOE; measurements + 보정 → calibration; 최대/최소 + a range → optimisation; 구조만 → structure only | |
| Settings | 빠르게 / 표준 / 정확하게; 코어 8개, 동시에 2개, 3번 반복, seed 5, 3방향, RVE 40um, 복셀 0.5um | |
| Follow-ups | "55%", "구형이고 5마이크로", "알루미나 말고 질화붕소로", "CTE도 추가", "CTE는 빼줘", "함량은 40%로", "boron nitride instead of alumina" | a further message changes the request before it |
| Casual wording | "에폭시에 알루미나 반 정도 섞으면 열이 얼마나 잘 빠질까?", "열전도도는 필요없고 CTE만", "epoxy with alumina, 55%, actually make that 60%", "에폭시에알루미나55%넣고열전도도" | read by the model, checked by the rules |
| Amounts | "수지 100g에 알루미나 150g", "100 parts epoxy, 150 parts alumina", "4대6" | the weight or volume percent, the calculation shown |
| Material values | "k가 25 W/mK인 알루미나", "epoxy (k 0.2, E 3 GPa)", "실리카 유전율은 3.8로" | the user's value over the library's, both shown |
| Comparisons | "알루미나랑 질화붕소 중 어느 쪽이 ...", "alumina vs boron nitride" | each on its own (separate runs), never one mixture; asked first |

**Contents.** A number with a percent sign or word (%, 퍼센트, 프로, percent) is a percent. A number of 1 or less
without a unit is a fraction (0.55 → 55 %); a number above 1 and up to 100 without a unit, said of a material, is a
percent. a/b is a fraction when b is 12 or less (1/3, 3/4); otherwise it is a list of levels (30/40/50). The basis is
the unit's (vol%, wt%, 부피%, 중량%, v/v, w/w) or a basis word in the sentence (부피비, 중량 기준, by weight, volume
fraction); phr is converted to wt% with the resin's 100 parts. When the matrix is given ("에폭시 40%에 실리카"), a
single filler takes the rest. A number belongs to the material of its clause ("에폭시 수지 45%와 알루미나 55%",
"epoxy with 30 vol% silica", "55 vol%의 알루미나", "(플레이크, 10 마이크로)"). A content outside 0-100 % is asked again;
fillers adding up to 100 % or more are refused.

**Typing errors.** A word that names nothing exactly is compared with every name by spelling and by sound: Korean
in jamo, vowels that sound alike (ㅐ/ㅔ) and tense or aspirated consonants (ㄲ/ㅋ/ㄱ) as one, final consonants as
they sound; English with ph = f, c = s/k and doubled letters once; and a key shared by both scripts lets 실리카
find silica. At 0.8 or more the closest name is taken and shown in the summary ("'애폭시레진' → Epoxy (0.97)"); a tie
of sounds is decided by the spelling; from 0.65 it is offered as a question. Short words need 0.9, and common words
are never matched. A known name inside an unknown word ("그래핀옥사이드" holds 그래핀) is asked about, not taken.

**Nothing is made up.** Material values are the MPSim library's, or a value the user gives in the request. A
material the library does not hold is asked about (or added in the Material tab); it is never invented. A number is
used only where the sentence says it, or follows from its numbers by a calculation the summary shows.

## What it asks, and what it decides

Asked always, even with "decide for me": the matrix, every filler and its content, the property to compute, the
range of a DOE and the measurements of a calibration. Asked with a recommended answer (pre-selected) when not said:
the content basis (vol%), the particle shape (sphere) and size (10 µm), the accuracy level and the parallel runs.
"알아서", "자동으로", "기본값으로", "decide for me" or the button **Decide for me** takes the recommendations, which
follow the problem:

- **Accuracy level** - Accurate when the loading is dense (45 vol% or more) and the property contrast high (30 or
  more), where MPSim's own study found the result most sensitive to the arrangement; Standard otherwise (within 1 %
  for moderate loadings); for a DOE, Standard from 10 cases and Fast from 30, so that it finishes.
- **Parallel runs** - one run takes every core; a study runs several cases side by side (about six cores each),
  MPSim checking the memory.
- **Directions** - z, or x, y and z when particles are aligned.
- **Shape and size** - spheres of 10 µm (MPSim's default); conduction without an interface resistance does not depend
  on the absolute size.

The summary marks every value that was not said with `*`.

## The local model

Qwen3.5-2B (1.2 GB, 4-bit Q4_K_M, Apache 2.0, the Qwen team) and llama.cpp's server (`llama-server`, build b11606, MIT) are
in `AIMPSim/llm/` of the offline package; `AIMPSim\GET_AI_MODEL.bat` downloads both for an installation from the
source and checks their SHA-256. AIMPSim finds them without any setting.

- It starts when the AI tab is opened and reads its instructions once (under a minute); a request then takes
  3-4 s on a laptop CPU (Intel Core Ultra 5 125H). It uses 4 threads, so that the solvers keep their
  cores, and about 2 GB of memory. It listens on 127.0.0.1 only, on a free port, and ends with MPSim.
- `AIMPSim/aimpsim_config.json` overrides it (see `aimpsim_config.example.json`): another GGUF model, a server
  already running (`url`), or `{"llm": "off"}` for the rules alone.
- Its answer is held to a JSON schema by the server, and checked as described above before anything of it is used.

**Why this model.** Four small models with an open licence were read through the same checks on the 50 held-out
requests (none of them used to tune anything before), on the same laptop CPU, with the same checks (those of
the comparison; the release's checks, written after it, read more of them - see Verification):

| Model (4-bit GGUF) | File | Right | Asked | Wrong | Per request |
|---|---|---|---|---|---|
| **Qwen3.5-2B** (Apache 2.0) | 1.2 GB | 38 | 9 | 3 | 2.7 s |
| Qwen3.5-4B (Apache 2.0) | 2.6 GB | 42 | 7 | 1 | 6.9 s |
| Gemma 4 E2B (Apache 2.0) | 2.6 GB | 37 | 9 | 4 | 7.8 s |
| Granite 4.2 3B (Apache 2.0) | 2.1 GB | 37 | 9 | 4 | 14.2 s |

The larger Qwen reads a little more without a question, at two and a half times the time and twice the size (more
than GitHub's 2 GiB per release file); the checks keep the smaller one from reading wrongly. It can be chosen
instead: `AIMPSim\GET_AI_MODEL.bat --model qwen3.5-4b` (`--list` shows the others).

## Verification

The AI tab is checked on the inputs it makes, not on the analyses (those are MPSim's, checked by its own self-test,
`5_SELF_TEST.bat`, 88 problems with known solutions). Every request below has its answer written down; a reading is
right, asked (left open and asked - safe), or wrong (read as something else).

**Requests as people write them** (`python AIMPSim/tests/freeform.py`, with `--llm <llama-server> <model>` for the
model): roundabout wording, corrections, words taken back, spacing, Korean and English mixed, typing errors, amounts,
material values, sizes, settings, studies, calibrations, vague amounts and requests that are not requests.

| Set | Rules alone | Qwen3.5-2B + checks |
|---|---|---|
| 114 requests the checks were developed on | 45 / 35 / 34 | 106 / 7 / 1 |
| 50 held out, then used for changes | 23 / 14 / 13 | 44 / 6 / 0 |
| 40 held out, then used for changes | 19 / 9 / 12 | 39 / 1 / 0 |
| 30 written last (three fixes followed their first reading) | 14 / 6 / 10 | 27 / 1 / 2 |

(right / asked / wrong). The last 30 were first read before any change came from them: Qwen3.5-2B 25 / 3 / 2, Qwen3.5-4B 27 / 3 / 0, the rules alone 14 / 6 / 10. Reading with the model takes
3-4 s per request (median).

**Requests written to rule** (they must not get worse with the model):
- `python AIMPSim/tests/run_tests.py` - 118 hand-written requests, 98 inputs validated by MPSim, conversations of
  several messages (rules alone and model-first through a stand-in server), and the checks on made-up model answers
  (invented materials, numbers and material values, broken answers, no answer). Rules alone: 118/118; read through
  Qwen3.5-2B: 118/118 (98/98 inputs accepted by MPSim); through Qwen3.5-4B: 118/118.
- `python AIMPSim/tests/exhaustive.py` - generated requests, each with its answer: every alias of every material,
  every way of writing a content, size, shape, analysis, DOE, calibration, optimisation goal and setting, pairs of
  fillers, Korean word orders and particles, typing errors made from every alias, and random combinations. Rules
  alone, 5,002 requests: no input wrong, nothing missed, 132 asked. A sample of 20 per kind read through Qwen3.5-2B
  (309 requests): 279 right, 29 asked (28 of them by design: sentences that are not requests and unknown names), 1 wrong (a matrix named by a misspelt long name, fixed after the run and checked on the model's answer), none missed.

## Installation

**PC without internet.** Download `AIMPSim-0.2.0-offline-win64.zip` from the
[latest release](https://github.com/HyoseokByun-opt/AIMPSim/releases/latest): MPSim with the AI tab, the model and its
server, the Python runtime, every wheel and openEMS. Unzip to a short path such as `C:\AIMPSim`, run
`1_INSTALL_OFFLINE.bat`, then `2_RUN_LOCAL.bat`. For the larger model, unzip
`AIMPSim-0.2.0-model-qwen3.5-4b-part1of2.zip` and `...part2of2.zip` into the same folder; the AI tab uses it from then on.

**PC with internet and conda.**

```bat
git clone https://github.com/HyoseokByun-opt/AIMPSim.git C:\AIMPSim
cd C:\AIMPSim
1_INSTALL.bat
AIMPSim\GET_AI_MODEL.bat
2_RUN_LOCAL.bat
```

`GET_AI_MODEL.bat` downloads llama-server and Qwen3.5-2B and checks their SHA-256; `--model qwen3.5-4b` takes the larger
model, `--list` shows the others. MPSim's user guides apply unchanged
([English](https://github.com/HyoseokByun-opt/MPSim/releases/latest/download/MPSim-User-Guide-EN.pdf),
[Korean](https://github.com/HyoseokByun-opt/MPSim/releases/latest/download/MPSim-User-Guide-KO.pdf)); the AI tab is
described in [AIMPSim/docs/GUIDE_KO.md](AIMPSim/docs/GUIDE_KO.md).

## Licence

MIT (see LICENSE). AIMPSim is MPSim with the AI tab; the open-source projects MPSim builds on are listed in its
[README](https://github.com/HyoseokByun-opt/MPSim#license). The local model is Qwen3.5-2B (or -4B) by the Qwen team,
Apache License 2.0 (its licence is in `AIMPSim/llm/models/`), run by llama.cpp (MIT, `AIMPSim/llm/bin/LICENSE-llama.cpp`).

**Declaration of AI assistance.** The code and the tests were written with the assistance of Claude (Anthropic;
Claude Code with Claude Opus 5.5), an AI assistant, working under the author's direction. The author reviewed the
output and takes full responsibility for the content; commits written with its help carry a `Co-Authored-By: Claude`
trailer.
