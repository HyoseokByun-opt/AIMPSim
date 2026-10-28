# AIMPSim

**MPSim with requests in words.** AIMPSim is the AI edition of [MPSim](https://github.com/HyoseokByun-opt/MPSim):
the same program, solvers and checks, with an **AI** tab (between Home and Material) where a request in Korean or
English sets up the case:

> 에폭시에 구형 알루미나 55 vol%, 입경 5 µm, 열전도도 구해줘
> epoxy with 60 vol% spherical silica 4 um, thermal conductivity and CTE, accurate

The request becomes an MPSim run, a DOE study, a calibration against measurements, or a DOE followed by its
optimum. Before anything runs, the tab shows a summary: what was read from the sentence, what was corrected or
assumed, which settings were chosen for the problem and why, and the RVE MPSim plans for it. **Run** starts it;
**Open in the tabs to edit** puts the case into MPSim's tabs instead. AIMPSim works offline.

<p align="center">
  <img src="docs/images/aimpsim_tab.png" alt="The AI tab: a request, the summary of what will run, and the questions with their recommended answers" width="100%">
</p>

## Two editions

| | MPSim | AIMPSim |
|---|---|---|
| Analyses, solvers, checks, guides | the same | the same |
| AI tab (requests in words) | - | yes |
| Optional local language model | - | yes (llama.cpp, see below) |
| Repository | HyoseokByun-opt/MPSim | HyoseokByun-opt/AIMPSim |

Every change of MPSim is published to both repositories, so AIMPSim always carries the latest MPSim. The reading
engine lives in the folder `AIMPSim/`; everything else is MPSim. Install and start AIMPSim exactly as MPSim
(`1_INSTALL.bat` or the offline package, then `2_RUN_LOCAL.bat`); the user guide of MPSim applies unchanged, and
[AIMPSim/docs/GUIDE_KO.md](AIMPSim/docs/GUIDE_KO.md) describes the AI tab.

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

**Nothing is made up.** Material values are the MPSim library's. A material the library does not hold is asked
about (or added in the Material tab); it is never invented. A number is used only where the sentence says it.

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

## Optional local model

For sentences the rules cannot read, a small model can help: llama.cpp's server (`llama-server`, MIT licence) with a
GGUF model file, both copied to the offline PC. Write `AIMPSim/aimpsim_config.json` (see
`aimpsim_config.example.json`):

```json
{"llm": {"server_exe": "C:/llama/llama-server.exe", "model": "C:/models/model-Q4_K_M.gguf",
         "port": 8089, "threads": 4, "timeout_s": 60}}
```

AIMPSim starts the server on 127.0.0.1 when it is first needed, with few threads so that the solvers keep their
cores. The model is asked only when the rules leave the matrix, the fillers or the analyses open. Its answer is held
to a JSON schema; its material and analysis names go through the same lexicon as typed words; a number is kept only
if the sentence holds it; an answer of the wrong shape is ignored; and whatever it filled is marked "AI guess - check
it". A model with an open licence (Apache 2.0, MIT) of 2-4 billion parameters runs on a CPU. Without a model, the
rules read every request.

## Verification

The AI tab is checked on the inputs it makes, not on the analyses (those are MPSim's, checked by its own self-test,
`5_SELF_TEST.bat`, 88 problems with known solutions).

- `python AIMPSim/tests/run_tests.py` - 118 hand-written requests (Korean, English and mixed; typing errors; every
  way of writing a content, a size, a range; several fillers; matrix or filler by context; unknown and ambiguous
  materials; sentences that are not requests; contents that cannot be), each checked against what it must be read
  as; MPSim's own validation of the 98 cases made from them; a conversation of several messages and clicks with
  changes (another filler, an analysis added and removed, another content, another matrix); the local-model adapter
  against a stand-in server, including made-up numbers, materials outside the library, broken answers and no answer.
- `python AIMPSim/tests/exhaustive.py` - generated requests, each with its answer, graded as right, asked, wrong or
  missed: every alias of every material as matrix and as filler (746), every way of writing a content (212), a size
  (94), a shape (118), every alias of every analysis (221), DOE ranges and steps (86), calibration units and
  conditions (37), optimisation goals (22), settings (120), pairs of fillers (132), Korean word orders (432) and
  particles (158), typing errors made from every alias (1,087), sentences that are not requests (20), unknown names
  (9) and random combinations of all of them (1,500 per seed). In 4,994 requests and three further random seeds
  (4,500): **no input was wrong and nothing was missed**; 130 were questions where the sentence was unclear (96 of
  1,087 typing errors, the rest by design), and every input was accepted by MPSim.

## Licence

MIT (see LICENSE). AIMPSim is MPSim with the AI tab; the open-source projects MPSim builds on are listed in its
[README](https://github.com/HyoseokByun-opt/MPSim#license). The optional local model runs on llama.cpp.

**Declaration of AI assistance.** The code and the tests were written with the assistance of Claude (Anthropic;
Claude Code with Claude Opus 5.5), an AI assistant, working under the author's direction. The author reviewed the
output and takes full responsibility for the content; commits written with its help carry a `Co-Authored-By: Claude`
trailer.
