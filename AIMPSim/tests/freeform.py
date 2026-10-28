"""Free requests as people type them - roundabout, spaced wrongly, Korean and
English mixed, misspelt, with corrections, material values and settings -
each with what it must become. Not made from templates.

    python tests/freeform.py                          the rules alone
    python tests/freeform.py --llm <llama-server.exe> <model.gguf> [--threads 6]
    python tests/freeform.py --url http://127.0.0.1:8089

Each field is graded: ok (read right), asked (left open and asked) or wrong
(read as something else). A wrong field with no question open is silent:
the summary is the only place the user can catch it.
"""
import argparse
import json
import os
import statistics
import sys
import time

AI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AI)
sys.path.insert(0, os.path.join(AI, "tests"))
from run_tests import find_mpsim, host_for  # noqa: E402

E, A, S, B, N = "epoxy", "al2o3", "sio2", "hbn", "aln"
T = {"thermal"}
# (category, text, expect)
#   m: matrix id (None: must be asked)      f: [(id, percent or None (asked) or "*")]
#   a: analyses (None: must be asked)       t: task
#   size / shape / props / std: {filler index: value}
#   doe: (lo, hi)    meas: n measurements    set: {key: value} of quality, auto, directions, film, threads,
#   concurrency, seeds, orientation
CASES = [
    # ---- roundabout: a purpose or a description instead of a name ---------------
    ("round", "안녕하세요, 이번에 새로 개발하는 방열 소재가 있는데요, 에폭시 베이스에 알루미나를 한 55% 정도 넣어볼까 하거든요. 이게 열을 얼마나 잘 전달할지 미리 좀 보고 싶어서요.",
     {"m": E, "f": [(A, 55)], "a": T}),
    ("round", "에폭시에 알루미나 반 정도 섞으면 열이 얼마나 잘 빠질까?", {"m": E, "f": [(A, 50)], "a": T}),
    ("round", "실리콘 고무에 질화붕소 판 모양 가루를 4분의 1쯤 넣으면 얼마나 딱딱해지는지 궁금함",
     {"m": "silicone", "f": [(B, 25)], "a": {"cte"}, "shape": {0: "platelet"}}),
    ("round", "은가루를 에폭시에 20% 정도 넣었을 때 전기가 통하는지 봐줘", {"m": E, "f": [("ag", 20)], "a": {"electrical"}}),
    ("round", "온도 올라가면 얼마나 늘어나는지 알고 싶은데, 에폭시에 실리카 60%짜리", {"m": E, "f": [(S, 60)], "a": {"cte"}}),
    ("round", "5G 기판용으로 PTFE에 실리카 30% 섞은 거 신호 손실 어느 정도일지", {"m": "ptfe", "f": [(S, 30)], "a": {"dielectric"}}),
    ("round", "언더필 만들 건데 에폭시에 실리카 55% 넣으면 잘 흐를까", {"m": E, "f": [(S, 55)], "a": {"viscosity"}}),
    ("round", "에폭시에 실리카 60% 넣은 몰딩재가 물을 얼마나 먹는지", {"m": E, "f": [(S, 60)], "a": {"moisture"}}),
    ("round", "에폭시에 구리 가루 넣어서 전자파 얼마나 막는지 보고 싶어. 구리는 30% 정도", {"m": E, "f": [("cu", 30)], "a": {"emi"}}),
    ("round", "TIM 용도로 실리콘에 질화알루미늄 70% 넣을 건데 성능 괜찮을까", {"m": "silicone", "f": [(N, 70)], "a": T}),
    ("round", "에폭시에 산화알루미늄 분말 50% 넣으면 열 전달 성능이 어떻게 돼?", {"m": E, "f": [(A, 50)], "a": T}),
    ("round", "칩 휘는 거 걱정되는데 에폭시에 실리카 70% 몰드면 괜찮을까", {"m": E, "f": [(S, 70)], "a": {"thermomech"}}),
    ("round", "에폭시에 은 플레이크를 한 30프로 정도 넣은 페이스트 전기 저항 좀", {"m": E, "f": [("ag", 30)], "a": {"electrical"}, "shape": {0: "platelet"}}),
    ("round", "I'm curious how well heat would get through epoxy if I packed it with about half alumina by volume", {"m": E, "f": [(A, 50)], "a": T}),
    ("round", "What happens to the stiffness when you load silicone with boron nitride flakes, roughly a quarter?", {"m": "silicone", "f": [(B, 25)], "a": {"cte"}}),
    ("round", "Could you check whether a silver-filled epoxy at 20% would even conduct electricity?", {"m": E, "f": [("ag", 20)], "a": {"electrical"}}),
    ("round", "We're designing an underfill: epoxy with sixty percent silica. Will it flow okay?", {"m": E, "f": [(S, 60)], "a": {"viscosity"}}),
    ("round", "How much will a PTFE board with 30% silica swell in humid conditions?", {"m": "ptfe", "f": [(S, 30)], "a": {"moisture"}}),
    ("round", "My TIM is silicone with 70% aluminum nitride, is that good enough?", {"m": "silicone", "f": [(N, 70)], "a": T}),
    ("round", "Mix copper powder into epoxy (thirty percent) and tell me how well it blocks EMI", {"m": E, "f": [("cu", 30)], "a": {"emi"}}),
    ("round", "How hot will a silver epoxy trace get when current runs through it? silver 25%", {"m": E, "f": [("ag", 25)], "a": {"joule"}}),
    ("round", "Figure out the warpage of an epoxy mold compound with 70% silica", {"m": E, "f": [(S, 70)], "a": {"thermomech"}}),
    ("round", "열 잘 빠지는 실리콘 패드, 질화붕소 40 넣은거", {"m": "silicone", "f": [(B, 40)], "a": T}),
    ("round", "PI에 BN 넣은 필름인데 15% 정도, 방열이랑 휨 둘 다", {"m": "polyimide", "f": [(B, 15)], "a": {"thermal", "thermomech"}}),
    # ---- amounts said in other ways -------------------------------------------------
    ("amount", "수지 100g에 알루미나 150g 넣으면 열전도도는?", {"m": None, "f": [(A, 60)], "a": T}),
    ("amount", "필러를 수지보다 조금 더 많이, 부피로 따지면 육십 정도 되게 에폭시에 알루미나 넣어서 열전도도", {"m": E, "f": [(A, 60)], "a": T}),
    ("amount", "에폭시랑 알루미나 비율을 4대6으로 해서 열전도도", {"m": E, "f": [(A, 60)], "a": T}),
    ("amount", "열전도도 계산 부탁드립니다. 조성은 에폭시 45, 알루미나 55입니다.", {"m": E, "f": [(A, 55)], "a": T}),
    ("amount", "에폭시에 알루미나 오십오프로 열전도 ㄱㄱ", {"m": E, "f": [(A, 55)], "a": T}),
    ("amount", "100 parts epoxy, 150 parts alumina, thermal conductivity please", {"m": E, "f": [(A, 60)], "a": T}),
    ("amount", "I want to know the thermal conductivity of epoxy. The filler? Alumina. Amount? 55.", {"m": E, "f": [(A, 55)], "a": T}),
    ("amount", "에폭시 레진에 구형 실리카를 부피 기준으로 절반 넣고, 유전율이랑 유전손실 확인 부탁", {"m": E, "f": [(S, 50)], "a": {"dielectric"}}),
    ("amount", "에폭시 3 : 알루미나 7 무게비로 열전도", {"m": E, "f": [(A, 70)], "a": T}),
    ("amount", "silicone 40 / AlN 60 by volume, k?", {"m": "silicone", "f": [(N, 60)], "a": T}),
    ("amount", "에폭시에 실리카 0.6만큼 넣은거 CTE", {"m": E, "f": [(S, 60)], "a": {"cte"}}),
    ("amount", "에폭시 수지가 35%고 나머지는 전부 알루미나야. 열전도도", {"m": E, "f": [(A, 65)], "a": T}),
    ("amount", "에폭시에 알루미나 100phr 넣으면 열전도", {"m": E, "f": [(A, 50)], "a": T}),
    # ---- corrections and words taken back ---------------------------------------------
    ("correct", "알루미나는 아니고 질화붕소를 에폭시에 30% 넣은 경우 열전도도", {"m": E, "f": [(B, 30)], "a": T}),
    ("correct", "열전도도는 필요없고 CTE만 봐줘, 에폭시에 실리카 50%", {"m": E, "f": [(S, 50)], "a": {"cte"}}),
    ("correct", "에폭시 말고 BT에 실리카 40%로 유전율", {"m": "bt", "f": [(S, 40)], "a": {"dielectric"}}),
    ("correct", "에폭시에 알루미나 55%, 아니 60%로 해줘. 열전도도", {"m": E, "f": [(A, 60)], "a": T}),
    ("correct", "알루미나 55% 에폭시 열전도도 말고 열팽창", {"m": E, "f": [(A, 55)], "a": {"cte"}}),
    ("correct", "Don't bother with thermal conductivity, I only need the CTE of epoxy with 50% silica", {"m": E, "f": [(S, 50)], "a": {"cte"}}),
    ("correct", "Not alumina - use boron nitride, 30% in epoxy, for heat spreading", {"m": E, "f": [(B, 30)], "a": T}),
    ("correct", "epoxy with alumina, 55%, actually make that 60%, thermal conductivity", {"m": E, "f": [(A, 60)], "a": T}),
    ("correct", "실리카 넣으려다가 그냥 알루미나로 하기로 했어, 에폭시에 50%, 열전도", {"m": E, "f": [(A, 50)], "a": T}),
    ("correct", "silicone with 40% AlN, hmm no, 45%, and only the thermal part", {"m": "silicone", "f": [(N, 45)], "a": T}),
    ("correct", "에폭시에 BN 20%랑 알루미나 40% 넣는데 BN은 빼고 알루미나만으로 열전도도", {"m": E, "f": [(A, 40)], "a": T}),
    # ---- spacing ------------------------------------------------------------------------
    ("spacing", "에폭시에알루미나55%넣고열전도도구해줘", {"m": E, "f": [(A, 55)], "a": T}),
    ("spacing", "실리콘 에 질화 알루미늄 60 % 넣 고 열 전도도", {"m": "silicone", "f": [(N, 60)], "a": T}),
    ("spacing", "피티에프이에실리카30퍼유전율이랑유전손실", {"m": "ptfe", "f": [(S, 30)], "a": {"dielectric"}}),
    ("spacing", "에 폭 시 에 실 리 카 50 % 열 팽 창", {"m": E, "f": [(S, 50)], "a": {"cte"}}),
    ("spacing", "epoxywith55%alumina thermalconductivity", {"m": E, "f": [(A, 55)], "a": T}),
    ("spacing", "폴리이미드필름에질화붕소판상20부피%넣고 열전도도랑휨", {"m": "polyimide", "f": [(B, 20)], "a": {"thermal", "thermomech"}, "shape": {0: "platelet"}}),
    # ---- Korean and English mixed ---------------------------------------------------------
    ("mixed", "epoxy에 alumina 55vol% 넣어서 thermal conductivity 계산해줘", {"m": E, "f": [(A, 55)], "a": T}),
    ("mixed", "BN flake 30%를 silicone에 넣고 k 계산", {"m": "silicone", "f": [(B, 30)], "a": T, "shape": {0: "platelet"}}),
    ("mixed", "PI film + SiC 20wt%, CTE랑 modulus", {"m": "polyimide", "f": [("sic", 20)], "a": {"cte"}}),
    ("mixed", "ptfe substrate에 silica 40퍼 넣고 Dk Df 뽑아줘", {"m": "ptfe", "f": [(S, 40)], "a": {"dielectric"}}),
    ("mixed", "에폭시 matrix에 copper 15% 넣고 EMI shielding 얼마나 되는지", {"m": E, "f": [("cu", 15)], "a": {"emi"}}),
    ("mixed", "silicone rubber에 aluminum nitride sphere 5um 50% thermal", {"m": "silicone", "f": [(N, 50)], "a": T, "size": {0: 5}, "shape": {0: "sphere"}}),
    ("mixed", "실리콘에 AlN 50% 넣고 thermal conductivity 정확하게", {"m": "silicone", "f": [(N, 50)], "a": T, "set": {"quality": "accurate"}}),
    # ---- typing errors ----------------------------------------------------------------------
    ("typo", "애폭시에 알르미나 55퍼 열전도", {"m": E, "f": [(A, 55)], "a": T}),
    ("typo", "sillica 60% in epoxi, CTE", {"m": E, "f": [(S, 60)], "a": {"cte"}}),
    ("typo", "질화부소 30% 실리콘, 열전도율", {"m": "silicone", "f": [(B, 30)], "a": T}),
    ("typo", "aluminium nitrade 60% in silicon rubber, termal conductivity", {"m": "silicone", "f": [(N, 60)], "a": T}),
    ("typo", "에폭씨에 시리카 오십퍼 유젼율", {"m": E, "f": [(S, 50)], "a": {"dielectric"}}),
    ("typo", "폴리이미드에 질화붕소 20% 열전도도 구해즈ㅜ", {"m": "polyimide", "f": [(B, 20)], "a": T}),
    # ---- material values the user gives -------------------------------------------------------
    ("props", "에폭시에 알루미나 55%, 알루미나 열전도도는 우리 제품 기준 200으로, 열전도도 계산", {"m": E, "f": [(A, 55)], "a": T, "props": {0: {"k": 200}}}),
    ("props", "k가 25 W/mK인 알루미나를 에폭시에 50% 넣었을 때 열전도도", {"m": E, "f": [(A, 50)], "a": T, "props": {0: {"k": 25}}}),
    ("props", "에폭시 열전도도를 0.25로 두고 실리카 60% 넣으면 열전도도", {"m": E, "f": [(S, 60)], "a": T, "props": {"m": {"k": 0.25}}}),
    ("props", "E가 70 GPa인 유리섬유 30%를 에폭시에 넣고 탄성계수", {"m": E, "f": [("eglass", 30)], "a": {"cte"}, "props": {0: {"E": 70}}}),
    ("props", "silica with a CTE of 0.5 ppm/K, 60% in epoxy, thermal expansion", {"m": E, "f": [(S, 60)], "a": {"cte"}, "props": {0: {"alpha": 0.5}}}),
    ("props", "우리 BN은 열전도도 300짜리야. 실리콘에 30% 넣고 열전도", {"m": "silicone", "f": [(B, 30)], "a": T, "props": {0: {"k": 300}}}),
    ("props", "epoxy (k 0.2, E 3 GPa) with 50% alumina, thermal conductivity and modulus", {"m": E, "f": [(A, 50)], "a": {"thermal", "cte"}, "props": {"m": {"k": 0.2, "E": 3}}}),
    ("props", "에폭시에 실리카 50% 넣고 유전율, 실리카 유전율은 3.8로", {"m": E, "f": [(S, 50)], "a": {"dielectric"}, "props": {0: {"eps_r": 3.8}}}),
    # ---- sizes and shapes ---------------------------------------------------------------------
    ("size", "에폭시 안에 지름 5마이크론짜리 동그란 알루미나 알갱이가 55% 차 있을 때 열전도율", {"m": E, "f": [(A, 55)], "a": T, "size": {0: 5}, "shape": {0: "sphere"}}),
    ("size", "Epoxy matrix, filler is aluminum oxide powder at 55 vol%, spheres of 5 microns; need k", {"m": E, "f": [(A, 55)], "a": T, "size": {0: 5}}),
    ("size", "에폭시에 500나노 실리카 30% 유전율", {"m": E, "f": [(S, 30)], "a": {"dielectric"}, "size": {0: 0.5}}),
    ("size", "에폭시에 알루미나 50%, 평균 입경 10um에 표준편차 3um, 열전도", {"m": E, "f": [(A, 50)], "a": T, "size": {0: 10}, "std": {0: 3}}),
    ("size", "BN 판상인데 지름 20마이크로 두께 1마이크로, 실리콘에 30% 열전도", {"m": "silicone", "f": [(B, 30)], "a": T, "size": {0: 20}, "shape": {0: "platelet"}}),
    ("size", "carbon fibre 7 um diameter, 70 um long, 20% in epoxy, thermal", {"m": E, "f": [("carbon_fiber", 20)], "a": T, "size": {0: 7}, "shape": {0: "fiber"}}),
    ("size", "실리콘에 알루미나 넣는데, 큰 거 50마이크로 40%랑 작은 거 5마이크로 20%로 섞어서 열전도도", {"m": "silicone", "f": [(A, 40), (A, 20)], "a": T, "size": {0: 50, 1: 5}}),
    ("size", "에폭시에 각진 알루미나 0.02mm 50% 열전도", {"m": E, "f": [(A, 50)], "a": T, "size": {0: 20}, "shape": {0: "irregular"}}),
    # ---- several fillers ------------------------------------------------------------------------
    ("multi", "에폭시에 알루미나 50%랑 질화붕소 10% 같이 넣으면 열 잘 통하나?", {"m": E, "f": [(A, 50), (B, 10)], "a": T}),
    ("multi", "에폭시에 알루미나 55% 넣고 그 다음에 BN도 5% 더 넣으면 열전도도", {"m": E, "f": [(A, 55), (B, 5)], "a": T}),
    ("multi", "silicone with 40% alumina and 20% aluminium nitride, thermal", {"m": "silicone", "f": [(A, 40), (N, 20)], "a": T}),
    ("multi", "에폭시 기반, 필러는 실리카 30에 알루미나 20", {"m": E, "f": [(S, 30), (A, 20)], "a": None}),
    # ---- settings ----------------------------------------------------------------------------------
    ("settings", "에폭시에 알루미나 55% 열전도도 정밀하게 코어는 8개만 써서", {"m": E, "f": [(A, 55)], "a": T, "set": {"quality": "accurate", "threads": 8}}),
    ("settings", "에폭시에 실리카 50% 열전도 대충 빨리", {"m": E, "f": [(S, 50)], "a": T, "set": {"quality": "fast"}}),
    ("settings", "에폭시에 BN 판상 20% 수직으로 세워서 열전도, 3방향 다", {"m": E, "f": [(B, 20)], "a": T, "set": {"directions": "xyz", "orientation": "z"}}),
    ("settings", "epoxy with 50% alumina, k, just decide the rest yourself", {"m": E, "f": [(A, 50)], "a": T, "set": {"auto": True}}),
    ("settings", "에폭시에 알루미나 50% 열전도, 나머지는 알아서", {"m": E, "f": [(A, 50)], "a": T, "set": {"auto": True}}),
    ("settings", "PI 필름 25um에 BN 20% 휨", {"m": "polyimide", "f": [(B, 20)], "a": {"thermomech"}, "set": {"film": 25}}),
    ("settings", "에폭시 알루미나 50 열전도, 시드 바꿔서 3번 반복", {"m": E, "f": [(A, 50)], "a": T, "set": {"seeds": 3}}),
    # ---- DOE, optimisation, calibration -----------------------------------------------------------
    ("task", "에폭시에 알루미나를 40에서 60까지 바꿔가며 열전도도 어떻게 변하나 보고싶어", {"m": E, "f": [(A, "*")], "a": T, "t": "doe", "doe": (40, 60)}),
    ("task", "Sweep alumina in epoxy from 40 to 60 percent and show me how the thermal conductivity changes", {"m": E, "f": [(A, "*")], "a": T, "t": "doe", "doe": (40, 60)}),
    ("task", "실리카 함량 30, 40, 50, 60으로 에폭시 점도 비교", {"m": E, "f": [(S, "*")], "a": {"viscosity"}, "t": "doe", "doe": (30, 60)}),
    ("task", "에폭시에 알루미나 20~60% 사이에서 열전도도 제일 높은 데 찾아줘", {"m": E, "f": [(A, "*")], "a": T, "t": "optimization", "doe": (20, 60)}),
    ("task", "열전도도 측정해보니 50%에서 1.2 나왔어. 에폭시-알루미나야. 계면저항 맞춰줘", {"m": E, "f": [(A, "*")], "a": T, "t": "calibration", "meas": 1}),
    ("task", "I measured 1.2 W/mK at 50% alumina in epoxy; fit the interface resistance", {"m": E, "f": [(A, "*")], "a": T, "t": "calibration", "meas": 1}),
    ("task", "에폭시 실리카 30%일때 0.45, 50%일때 0.8 W/mK 측정값으로 보정", {"m": E, "f": [(S, "*")], "a": T, "t": "calibration", "meas": 2}),
    ("task", "에폭시에 알루미나 넣은 구조만 만들어줘, 55%", {"m": E, "f": [(A, 55)], "a": None, "t": "structure"}),
    ("task", "BN 입경 5에서 20마이크로까지 4단계로, 실리콘에 30%, 열전도", {"m": "silicone", "f": [(B, 30)], "a": T, "t": "doe"}),
    # ---- what only the user can give: must be asked, never filled ------------------------------------
    ("vague", "열전도도랑 CTE 둘 다 궁금한데, 에폭시에 알루미나를 절반보다 살짝 많이 넣은 경우야", {"m": E, "f": [(A, None)], "a": {"thermal", "cte"}}),
    ("vague", "Let's say epoxy with a bit more than half alumina; thermal conductivity", {"m": E, "f": [(A, None)], "a": T}),
    ("vague", "에폭시랑 알루미나로 열 잘 통하는 거 만들고 싶어", {"m": E, "f": [(A, None)], "a": T}),
    ("vague", "전에 했던 거에서 함량만 좀 올려서 다시 해줘", {"m": None, "f": [], "a": None}),
    ("vague", "열전도 높은 방열 패드 만들고 싶은데 뭘 넣어야 할지 모르겠어", {"m": None, "f": [], "a": T}),
    ("vague", "에폭시에 필러 많이 넣으면 어떻게 돼?", {"m": E, "f": [], "a": None}),
    ("vague", "에폭시에 그래핀옥사이드 5% 넣고 열전도도", {"m": E, "f": [(None, "*")], "a": T}),
    ("vague", "something with good heat transfer please", {"m": None, "f": [], "a": T}),
    ("vague", "오늘 점심 뭐 먹지", {"m": None, "f": [], "a": None}),
    ("vague", "알루미나랑 질화붕소 중에 에폭시에 30% 넣었을 때 어느 쪽이 열전도도 더 높은지 비교해줘", {"m": E, "compare": True, "a": T}),
    ("vague", "Compare alumina vs boron nitride at 30% in epoxy for thermal conductivity", {"m": E, "compare": True, "a": T}),
]


# Held out: never looked at while the model's instructions are tuned (--holdout runs them).
HOLDOUT = [
    ("round", "산화아연 넣은 실리콘 갭필러인데 25 정도 넣으면 열 빼는 능력 어떨까", {"m": "silicone", "f": [("zno", 25)], "a": T}),
    ("round", "LCP 기판에 산화마그네슘 20% 넣으면 고주파에서 손실 얼마나 생기나", {"m": "lcp", "f": [("mgo", 20)], "a": {"dielectric"}}),
    ("round", "니켈 분말 35% 넣은 에폭시, 전류가 흐르긴 하는지", {"m": E, "f": [("ni", 35)], "a": {"electrical"}}),
    ("round", "센더스트 50% 실리콘 시트로 자기 특성 보고 싶어", {"m": "silicone", "f": [("sendust", 50)], "a": {"magnetic"}}),
    ("round", "PEEK에 탄소섬유 30% 넣으면 얼마나 단단해져?", {"m": "peek", "f": [("carbon_fiber", 30)], "a": {"cte"}}),
    ("round", "How much will an epoxy with 60% fused quartz bow when it cools?", {"m": E, "f": [("quartz", 60)], "a": {"thermomech"}}),
    ("round", "is a cyanate ester with 40% silica going to soak up water?", {"m": "cyanate_ester", "f": [(S, 40)], "a": {"moisture"}}),
    ("round", "barium titanate in epoxy at 30%, I need the permittivity for an embedded capacitor", {"m": E, "f": [("batio3", 30)], "a": {"dielectric"}}),
    ("amount", "에폭시 2, 질화규소 3 비율로 열전도", {"m": E, "f": [("si3n4", 60)], "a": T}),
    ("amount", "실리콘 50g에 다이아몬드 50g 넣고 열전도도", {"m": "silicone", "f": [("diamond", 50)], "a": T}),
    ("amount", "PPE에 실리카 사분의 일 넣었을 때 유전율", {"m": "ppe", "f": [(S, 25)], "a": {"dielectric"}}),
    ("amount", "epoxy 30 vol%, the rest silicon carbide, thermal conductivity", {"m": E, "f": [("sic", 70)], "a": T}),
    ("amount", "에폭시 100에 산화티타늄 25phr 유전율", {"m": E, "f": [("tio2", 20)], "a": {"dielectric"}}),
    ("amount", "BCB with seventy-five hundredths quartz? no sorry, 0.35 quartz, permittivity", {"m": "bcb", "f": [("quartz", 35)], "a": {"dielectric"}}),
    ("correct", "니켈 말고 은으로, 에폭시에 25% 전기전도도", {"m": E, "f": [("ag", 25)], "a": {"electrical"}}),
    ("correct", "실리콘에 질화알루미늄 50, 아 잠깐 55로 정정할게. 열전도", {"m": "silicone", "f": [(N, 55)], "a": T}),
    ("correct", "PI 대신 BCB로 하고 실리카 30% 유전율", {"m": "bcb", "f": [(S, 30)], "a": {"dielectric"}}),
    ("correct", "탄화규소 20%랑 다이아몬드 10%를 에폭시에 넣는데, 다이아는 너무 비싸니까 빼고 해줘. 열전도", {"m": E, "f": [("sic", 20)], "a": T}),
    ("correct", "silicone with 30% graphite for thermal and electrical, actually skip electrical", {"m": "silicone", "f": [("graphite", 30)], "a": T}),
    ("correct", "use invar instead of kovar, 40% in epoxy, CTE", {"m": E, "f": [("invar", 40)], "a": {"cte"}}),
    ("spacing", "실리콘에다이아몬드40%열전도도", {"m": "silicone", "f": [("diamond", 40)], "a": T}),
    ("spacing", "에폭 시에 산화 마그네슘 45 % 열 전 도", {"m": E, "f": [("mgo", 45)], "a": T}),
    ("spacing", "lcpwith20%silica dielectric", {"m": "lcp", "f": [(S, 20)], "a": {"dielectric"}}),
    ("mixed", "PEEK matrix에 glass fiber 25wt% 넣고 modulus랑 CTE", {"m": "peek", "f": [("eglass", 25)], "a": {"cte"}}),
    ("mixed", "silicone pad에 alumina 구형 30um 65% thermal 계산", {"m": "silicone", "f": [(A, 65)], "a": T, "size": {0: 30}, "shape": {0: "sphere"}}),
    ("mixed", "epoxy에 CNT 2% 넣고 electrical conductivity percolation 보고싶어", {"m": E, "f": [("cnt", 2)], "a": {"electrical", "percolation"}}),
    ("typo", "실리꼰에 질화알미늄 55% 열전도", {"m": "silicone", "f": [(N, 55)], "a": T}),
    ("typo", "epoxie with 40% sillicon carbide, thermal conductivty", {"m": E, "f": [("sic", 40)], "a": T}),
    ("typo", "폴리이마이드에 BN 20퍼 열전도", {"m": "polyimide", "f": [(B, 20)], "a": T}),
    ("props", "다이아몬드 열전도도 1000으로 보고 에폭시에 30% 넣었을 때 열전도", {"m": E, "f": [("diamond", 30)], "a": T, "props": {0: {"k": 1000}}}),
    ("props", "silicone (k = 0.15) with 50% alumina, thermal", {"m": "silicone", "f": [(A, 50)], "a": T, "props": {"m": {"k": 0.15}}}),
    ("props", "유전율 1000짜리 티탄산바륨 20% 에폭시 유전율", {"m": E, "f": [("batio3", 20)], "a": {"dielectric"}, "props": {0: {"eps_r": 1000}}}),
    ("props", "에폭시 E 2.5GPa, 실리카 60% 탄성계수", {"m": E, "f": [(S, 60)], "a": {"cte"}, "props": {"m": {"E": 2.5}}}),
    ("size", "에폭시에 3마이크로 실리카 55% CTE", {"m": E, "f": [(S, 55)], "a": {"cte"}, "size": {0: 3}}),
    ("size", "구리 플레이크 직경 15um 두께 0.5um를 에폭시에 20% 전기전도", {"m": E, "f": [("cu", 20)], "a": {"electrical"}, "size": {0: 15}, "shape": {0: "platelet"}}),
    ("size", "50 nm silica, 10% in epoxy, permittivity", {"m": E, "f": [(S, 10)], "a": {"dielectric"}, "size": {0: 0.05}}),
    ("size", "질화알루미늄 평균 20um 표준편차 5um 실리콘에 60% 열전도", {"m": "silicone", "f": [(N, 60)], "a": T, "size": {0: 20}, "std": {0: 5}}),
    ("multi", "에폭시에 실리카 40, 알루미나 15 넣고 열전도랑 CTE", {"m": E, "f": [(S, 40), (A, 15)], "a": {"thermal", "cte"}}),
    ("multi", "silicone with 45% alumina plus 10% zinc oxide, thermal", {"m": "silicone", "f": [(A, 45), ("zno", 10)], "a": T}),
    ("settings", "에폭시 알루미나 50 열전도, 빠르게 대충만", {"m": E, "f": [(A, 50)], "a": T, "set": {"quality": "fast"}}),
    ("settings", "실리콘 BN 30 열전도 최대한 정확하게, x y z 다", {"m": "silicone", "f": [(B, 30)], "a": T, "set": {"quality": "accurate", "directions": "xyz"}}),
    ("settings", "epoxy, 50% alumina, k, use 4 cores", {"m": E, "f": [(A, 50)], "a": T, "set": {"threads": 4}}),
    ("settings", "알아서 해줘. 실리콘에 질화알루미늄 50 열전도", {"m": "silicone", "f": [(N, 50)], "a": T, "set": {"auto": True}}),
    ("task", "에폭시에 실리카 40%부터 70%까지 10%씩 CTE", {"m": E, "f": [(S, "*")], "a": {"cte"}, "t": "doe", "doe": (40, 70)}),
    ("task", "silicone with AlN, try 40, 50 and 60 percent, thermal", {"m": "silicone", "f": [(N, "*")], "a": T, "t": "doe", "doe": (40, 60)}),
    ("task", "실리콘 BN 측정값 30%에서 2.1 W/mK, 계면저항 보정해줘", {"m": "silicone", "f": [(B, "*")], "a": T, "t": "calibration", "meas": 1}),
    ("task", "에폭시에 실리카 30~70% 중 CTE 가장 낮은 조건", {"m": E, "f": [(S, "*")], "a": {"cte"}, "t": "optimization", "doe": (30, 70)}),
    ("vague", "실리콘에 질화붕소 적당히 넣고 열전도도", {"m": "silicone", "f": [(B, None)], "a": T}),
    ("vague", "에폭시에 맥신 10% 열전도", {"m": E, "f": [(None, "*")], "a": T}),
    ("vague", "what would you recommend for a high-k substrate?", {"m": None, "f": [], "a": {"dielectric"}}),
]


# Written after the last change to the reading, read once: the final check.
FINAL = [
    ("round", "이번 프로젝트는 고방열 접착제인데요, 에폭시에 질화알루미늄을 60% 넣어보려고 합니다. 열이 잘 빠질지 확인 부탁드려요", {"m": E, "f": [(N, 60)], "a": T}),
    ("round", "실리콘 갭필러에 알루미나 70 들어간 거, 열 잘 전달되나", {"m": "silicone", "f": [(A, 70)], "a": T}),
    ("round", "PPE 기판에 실리카 45% 넣으면 고주파 신호가 얼마나 손실될까", {"m": "ppe", "f": [(S, 45)], "a": {"dielectric"}}),
    ("round", "does a silicone pad with 65% alumina move heat well enough for a power module?", {"m": "silicone", "f": [(A, 65)], "a": T}),
    ("round", "epoxy loaded with 40% carbonyl iron, I want to know how magnetic it gets", {"m": E, "f": [("carbonyl_iron", 40)], "a": {"magnetic"}}),
    ("round", "에폭시에 실리카 65% 넣은 언더필, 갭 사이로 잘 흘러 들어갈까?", {"m": E, "f": [(S, 65)], "a": {"viscosity"}}),
    ("amount", "에폭시:알루미나 = 3:7 로 섞은 것의 열전도도", {"m": E, "f": [(A, 70)], "a": T}),
    ("amount", "실리콘 200g, 질화붕소 50g 넣으면 열전도도 얼마", {"m": "silicone", "f": [(B, 20)], "a": T}),
    ("amount", "epoxy with three quarters alumina, thermal conductivity", {"m": E, "f": [(A, 75)], "a": T}),
    ("amount", "BT 레진 40에 실리카 60, 유전율", {"m": "bt", "f": [(S, 60)], "a": {"dielectric"}}),
    ("correct", "에폭시에 질화붕소 25%, 아 아니다 35%로. 열전도", {"m": E, "f": [(B, 35)], "a": T}),
    ("correct", "구리 대신 은 플레이크 15%를 에폭시에 넣고 전기전도도", {"m": E, "f": [("ag", 15)], "a": {"electrical"}}),
    ("correct", "silicone with zinc oxide 30%, no wait, magnesia instead, thermal", {"m": "silicone", "f": [("mgo", 30)], "a": T}),
    ("correct", "에폭시에 실리카 50% 열전도랑 CTE 보려 했는데 CTE는 됐고 열전도만", {"m": E, "f": [(S, 50)], "a": T}),
    ("spacing", "실리콘수지에질화붕소30퍼센트열전도도", {"m": "silicone", "f": [(B, 30)], "a": T}),
    ("spacing", "에폭시 에 은 20 % 넣 고 전 기 전 도", {"m": E, "f": [("ag", 20)], "a": {"electrical"}}),
    ("mixed", "epoxy matrix에 SiC 35wt% 넣고 thermal conductivity 확인", {"m": E, "f": [("sic", 35)], "a": T}),
    ("mixed", "PI에 BN platelet 20vol%, k랑 warpage", {"m": "polyimide", "f": [(B, 20)], "a": {"thermal", "thermomech"}}),
    ("typo", "에폭시에 탄화규쏘 30% 열전도", {"m": E, "f": [("sic", 30)], "a": T}),
    ("typo", "silcone with 50% alumnia, thermal", {"m": "silicone", "f": [(A, 50)], "a": T}),
    ("props", "열전도도 180 W/mK짜리 질화알루미늄을 실리콘에 50% 넣고 열전도", {"m": "silicone", "f": [(N, 50)], "a": T, "props": {0: {"k": 180}}}),
    ("props", "epoxy with k = 0.22 and 55% alumina, thermal", {"m": E, "f": [(A, 55)], "a": T, "props": {"m": {"k": 0.22}}}),
    ("size", "평균 입경 2마이크로 실리카 50%를 에폭시에, CTE", {"m": E, "f": [(S, 50)], "a": {"cte"}, "size": {0: 2}}),
    ("size", "에폭시에 200 nm 은 입자 10% 전기전도도", {"m": E, "f": [("ag", 10)], "a": {"electrical"}, "size": {0: 0.2}}),
    ("size", "glass fibres 10 um across and 300 um long, 30% in epoxy, stiffness", {"m": E, "f": [("eglass", 30)], "a": {"cte"}, "size": {0: 10}, "shape": {0: "fiber"}}),
    ("multi", "실리콘에 알루미나 50이랑 산화아연 10 같이, 열전도", {"m": "silicone", "f": [(A, 50), ("zno", 10)], "a": T}),
    ("multi", "epoxy + 40% silica + 10% alumina, CTE and thermal", {"m": E, "f": [(S, 40), (A, 10)], "a": {"cte", "thermal"}}),
    ("settings", "에폭시 알루미나 55 열전도, 빨리만 대충 보고 싶어", {"m": E, "f": [(A, 55)], "a": T, "set": {"quality": "fast"}}),
    ("settings", "실리콘 BN 판상 30% 면내로 눕혀서 열전도, 정확하게", {"m": "silicone", "f": [(B, 30)], "a": T, "set": {"quality": "accurate", "orientation": "xy"}}),
    ("settings", "epoxy 50% alumina thermal, 2 runs at a time", {"m": E, "f": [(A, 50)], "a": T, "set": {"concurrency": 2}}),
    ("task", "에폭시에 알루미나 30에서 70까지 5단계로 열전도", {"m": E, "f": [(A, "*")], "a": T, "t": "doe", "doe": (30, 70)}),
    ("task", "silicone with BN between 20 and 40 percent, which gives the highest k?", {"m": "silicone", "f": [(B, "*")], "a": T, "t": "optimization", "doe": (20, 40)}),
    ("task", "에폭시 알루미나 40%에서 1.1, 60%에서 2.3 W/mK 나왔어. 맞춰줘", {"m": E, "f": [(A, "*")], "a": T, "t": "calibration", "meas": 2}),
    ("task", "실리콘에 질화붕소 30% 구조만 보고 싶어", {"m": "silicone", "f": [(B, 30)], "a": None, "t": "structure"}),
    ("vague", "에폭시에 알루미나 좀 많이 넣으면 열전도 어때", {"m": E, "f": [(A, None)], "a": T}),
    ("vague", "실리콘에 뭔가 넣어서 열 잘 빠지게 하고 싶은데", {"m": "silicone", "f": [], "a": T}),
    ("vague", "에폭시에 페로브스카이트 20% 유전율", {"m": E, "f": [(None, "*")], "a": {"dielectric"}}),
    ("vague", "질화붕소랑 질화알루미늄 중에 실리콘에 40% 넣으면 뭐가 나아? 열전도", {"m": "silicone", "compare": True, "a": T}),
    ("vague", "hello, can you help me?", {"m": None, "f": [], "a": None}),
    ("vague", "에폭시에 알루미나 50% 넣었을 때", {"m": E, "f": [(A, 50)], "a": None}),
]


# Written after the last change, read once and reported as it came out: no change follows from it.
LAST = [
    ("round", "고열전도 언더필 만드는 중인데요, 에폭시에 구형 알루미나 60% 넣으면 흐름성이랑 열전도 둘 다 어떨까요", {"m": E, "f": [(A, 60)], "a": {"viscosity", "thermal"}}),
    ("round", "LTCC 대신 유리 기판 쓰려는데, 에폭시에 붕규산유리 40% 넣은 거 유전율", {"m": E, "f": [("glass_bsg", 40)], "a": {"dielectric"}}),
    ("round", "a conductive adhesive: epoxy and 75% silver flakes. will it conduct?", {"m": E, "f": [("ag", 75)], "a": {"electrical"}}),
    ("round", "how much will a silicone with 20% graphite heat up when current passes through it", {"m": "silicone", "f": [("graphite", 20)], "a": {"joule"}}),
    ("amount", "에폭시 10에 실리카 15 비율이면 CTE 얼마나 낮아져", {"m": E, "f": [(S, 60)], "a": {"cte"}}),
    ("amount", "polyimide 100 g with 30 g boron nitride, thermal conductivity", {"m": "polyimide", "f": [(B, 23.0769)], "a": T}),
    ("amount", "실리콘에 질화알루미늄 0.45만큼 넣고 열전도", {"m": "silicone", "f": [(N, 45)], "a": T}),
    ("correct", "에폭시에 산화마그네슘 30% 하려다가 산화아연으로 바꿨어, 열전도", {"m": E, "f": [("zno", 30)], "a": T}),
    ("correct", "silica 50 in epoxy, sorry I meant 55, dielectric constant", {"m": E, "f": [(S, 55)], "a": {"dielectric"}}),
    ("correct", "실리콘 말고 에폭시에 알루미나 50% 넣고 열전도", {"m": E, "f": [(A, 50)], "a": T}),
    ("correct", "에폭시에 은 30%랑 구리 10% 넣는데 구리는 산화되니까 빼고, 전기전도", {"m": E, "f": [("ag", 30)], "a": {"electrical"}}),
    ("spacing", "에폭시수지에구형알루미나60부피%열전도도부탁", {"m": E, "f": [(A, 60)], "a": T}),
    ("mixed", "silicone에 AlN 45vol%랑 BN 10vol% 섞어서 thermal 계산", {"m": "silicone", "f": [(N, 45), (B, 10)], "a": T}),
    ("typo", "에퐉시에 알루미나 50% 열전도도", {"m": E, "f": [(A, 50)], "a": T}),
    ("typo", "epoxy with 40% silicon carbide, termal and CTE", {"m": E, "f": [("sic", 40)], "a": {"thermal", "cte"}}),
    ("props", "에폭시(열전도도 0.18)에 알루미나 60% 넣으면 열전도", {"m": E, "f": [(A, 60)], "a": T, "props": {"m": {"k": 0.18}}}),
    ("props", "silica with a permittivity of 3.9, 50% in PTFE, Dk", {"m": "ptfe", "f": [(S, 50)], "a": {"dielectric"}, "props": {0: {"eps_r": 3.9}}}),
    ("size", "에폭시에 지름 30 마이크로 구형 알루미나 50% 열전도", {"m": E, "f": [(A, 50)], "a": T, "size": {0: 30}, "shape": {0: "sphere"}}),
    ("size", "copper flakes 20 um wide, 30% in epoxy, electrical", {"m": E, "f": [("cu", 30)], "a": {"electrical"}, "size": {0: 20}, "shape": {0: "platelet"}}),
    ("multi", "에폭시에 실리카 30, 알루미나 20, 질화붕소 5 넣고 열전도", {"m": E, "f": [(S, 30), (A, 20), (B, 5)], "a": T}),
    ("settings", "에폭시 알루미나 50 열전도, 코어 4개로 천천히 정확하게", {"m": E, "f": [(A, 50)], "a": T, "set": {"quality": "accurate", "threads": 4}}),
    ("settings", "silicone 40% BN flakes, thermal in all three directions", {"m": "silicone", "f": [(B, 40)], "a": T, "set": {"directions": "xyz"}}),
    ("task", "에폭시에 실리카를 20, 40, 60%로 바꿔서 CTE 보여줘", {"m": E, "f": [(S, "*")], "a": {"cte"}, "t": "doe", "doe": (20, 60)}),
    ("task", "find the alumina content between 30 and 60% in epoxy that keeps viscosity lowest", {"m": E, "f": [(A, "*")], "a": {"viscosity"}, "t": "optimization", "doe": (30, 60)}),
    ("task", "실리콘 질화붕소 측정값: 20%에서 1.0, 40%에서 2.2 W/mK. 계면저항 보정", {"m": "silicone", "f": [(B, "*")], "a": T, "t": "calibration", "meas": 2}),
    ("vague", "에폭시에 알루미나 적당량 넣고 열전도", {"m": E, "f": [(A, None)], "a": T}),
    ("vague", "에폭시에 카본나노튜브 넣으면 전기 통하나", {"m": E, "f": [("cnt", None)], "a": {"electrical"}}),
    ("vague", "BN이랑 알루미나 중 어느 쪽이 실리콘에서 열전도 좋아? 둘 다 50%", {"m": "silicone", "compare": True, "a": T}),
    ("vague", "thanks, that's all", {"m": None, "f": [], "a": None}),
    ("vague", "에폭시에 언옵테니움 20% 열전도", {"m": E, "f": [(None, "*")], "a": T}),
]


def grade(exp, it, r):
    """{field: ok | asked | wrong}"""
    qs = [q["id"] for q in r["questions"]]
    out = {}

    def g(name, got, want, asked_ids=()):
        if got == want:
            out[name] = "ok"
        elif got in (None, [], set(), {}) and (not asked_ids or any(q.startswith(asked_ids) for q in qs)):
            out[name] = "asked"
        else:
            out[name] = "wrong"
    gm = (it.get("matrix") or {}).get("id")
    if "m" in exp:
        if exp["m"] is None:
            out["matrix"] = "ok" if gm is None else "wrong"
        else:
            g("matrix", gm, exp["m"], ("matrix",))
    fl = it.get("fillers") or []
    if exp.get("compare"):
        # right: asked whether to run each on its own, or run so; wrong: one mixture made of them
        p = r.get("payload")
        if p is not None and not p.get("more_forms") and len(p["form"]["phases"]) >= 2:
            out["fillers"] = "wrong"
        elif "compare" in qs or (p or {}).get("more_forms"):
            out["fillers"] = "ok"
        else:
            out["fillers"] = "asked"
    elif "f" in exp:
        want = [w for w, _ in exp["f"]]
        got = [f.get("id") for f in fl]
        if sorted(map(str, got)) == sorted(map(str, want)):
            out["fillers"] = "ok"
        elif set(x for x in got if x) <= set(x for x in want if x) and any(q.startswith(("filler", "content")) for q in qs):
            out["fillers"] = "asked"
        else:
            out["fillers"] = "wrong"
        if out["fillers"] == "ok":
            for f, (_, pct) in zip(sorted(fl, key=lambda f: str(f.get("id"))), sorted(exp["f"], key=lambda x: str(x[0]))):
                if pct == "*":
                    continue
                c = f.get("content") or {}
                v = c.get("value")
                if v is not None and c.get("basis") == "phr":
                    v = 100.0 * v / (100.0 + v)
                if pct is None:
                    k = "ok" if v is None else "wrong"
                elif v is None:
                    k = "asked"
                else:
                    k = "ok" if abs(v - pct) < 0.6 else "wrong"
                if out.get("content") in (None, "ok"):
                    out["content"] = k
    if "a" in exp:
        ga = set(it.get("analyses") or [])
        if exp["a"] is None:
            out["analyses"] = "ok" if not ga else "wrong"
        else:
            out["analyses"] = "ok" if ga == set(exp["a"]) else ("asked" if not ga else "wrong")
    if "t" in exp:
        out["task"] = "ok" if (it.get("task") or "run") == exp["t"] else "wrong"
    elif exp.get("f") and all(p != "*" for _, p in exp["f"]):
        out["task"] = "ok" if (it.get("task") or "run") == "run" else "wrong"
    for key, field in (("size", "size_um"), ("shape", "shape"), ("std", "std_um")):
        for i, v in (exp.get(key) or {}).items():
            got = fl[i].get(field) if i < len(fl) else None
            if key == "size" and len(fl) > 1:      # two sizes of one material: in any order
                got = v if any(abs((f.get(field) or -1) - v) < 0.01 for f in fl) else got
            if isinstance(v, float) or isinstance(v, int):
                out[f"{key}{i}"] = "ok" if got is not None and abs(got - v) < 0.01 * max(1, v) else (
                    "asked" if got is None else "wrong")
            else:
                out[f"{key}{i}"] = "ok" if got == v else ("asked" if got is None else "wrong")
    for i, pv in (exp.get("props") or {}).items():
        slot = (it.get("matrix") or {}) if i == "m" else (fl[i] if i < len(fl) else {})
        got = slot.get("props") or {}
        out[f"props{i}"] = "ok" if all(abs((got.get(k) or -1e9) - v) < 1e-6 * max(1, v) for k, v in pv.items()) \
            and set(got) <= set(pv) else ("asked" if not got else "wrong")
    if "doe" in exp:
        fs = [f for f in it.get("doe", {}).get("factors") or [] if f.get("what") == "content"]
        lv = (fs[0].get("range") or (min(fs[0]["levels"]), max(fs[0]["levels"]))) if fs and (fs[0].get("range") or fs[0].get("levels")) else None
        out["doe"] = "ok" if lv and abs(lv[0] - exp["doe"][0]) < 0.5 and abs(lv[1] - exp["doe"][1]) < 0.5 else (
            "asked" if any(q == "doe_range" for q in qs) else "wrong")
    if "meas" in exp:
        n = len(it.get("calibration", {}).get("measurements") or [])
        out["meas"] = "ok" if n == exp["meas"] else ("asked" if n == 0 and "cal_meas" in qs else "wrong")
    st = exp.get("set") or {}
    for k, v in st.items():
        got = {"quality": it.get("quality"), "auto": bool(it.get("auto")), "directions": it.get("directions"),
               "film": it.get("film"), "threads": (it.get("parallel") or {}).get("threads"),
               "concurrency": (it.get("parallel") or {}).get("concurrency"), "seeds": it.get("seeds"),
               "orientation": it.get("orientation")}[k]
        out[f"set.{k}"] = "ok" if got == v or (isinstance(v, (int, float)) and got and abs(got - v) < 1e-6) else "wrong"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", nargs=2, metavar=("SERVER_EXE", "MODEL"))
    ap.add_argument("--url")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--args", default="", help="extra llama-server arguments, space separated")
    ap.add_argument("--only", default="")
    ap.add_argument("--holdout", action="store_true", help="the held-out requests instead")
    ap.add_argument("--final", action="store_true", help="the final requests instead")
    ap.add_argument("--last", action="store_true", help="the last requests (written after the last change) instead")
    ap.add_argument("-q", action="store_true", help="only the failures")
    a = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    from aimpsim.llm import LocalLLM
    from aimpsim.web import Assistant
    host = host_for(find_mpsim())
    asst = Assistant(host)
    if a.llm:
        asst.llm = LocalLLM({"server_exe": a.llm[0], "model": a.llm[1], "threads": a.threads,
                             "args": a.args.split() if a.args else [], "timeout_s": 300,
                             "log": os.path.join(os.environ.get("TEMP", "."), "aimpsim_llama.log")})
        t0 = time.time()
        if not (asst.llm._ping() or asst.llm._start()):
            sys.exit("the model server did not start (see %TEMP%\\aimpsim_llama.log)")
        print(f"model server up in {time.time() - t0:.1f} s")
    elif a.url:
        asst.llm = LocalLLM({"url": a.url, "timeout_s": 300})
    else:
        asst.llm = LocalLLM({})
    tally = {"ok": 0, "asked": 0, "wrong": 0}
    fields = {"ok": 0, "asked": 0, "wrong": 0}
    silent, secs, bycat = [], [], {}
    try:
        for cat, text, exp in (LAST if a.last else FINAL if a.final else HOLDOUT if a.holdout else CASES):
            if a.only and a.only not in text and a.only != cat:
                continue
            t0 = time.time()
            r = asst.interpret(text, new=True)
            secs.append(time.time() - t0)
            it = asst.sessions[r["session_id"]]["intent"]
            res = asst.planner.resolve(it, {})
            out = grade(exp, it, res)
            worst = "wrong" if "wrong" in out.values() else ("asked" if "asked" in out.values() else "ok")
            tally[worst] += 1
            c = bycat.setdefault(cat, {"ok": 0, "asked": 0, "wrong": 0})
            c[worst] += 1
            for v in out.values():
                fields[v] += 1
            ess = [q["id"] for q in res["questions"] if q["essential"]]
            if worst == "wrong" and not ess:
                silent.append(text)
            if worst != "ok" or not a.q:
                bad = {k: v for k, v in out.items() if v != "ok"}
                got = (f"m={(it.get('matrix') or {}).get('id')} f={[(f.get('id'), (f.get('content') or {}).get('value')) for f in it['fillers']]}"
                       f" a={sorted(it.get('analyses') or [])} t={it.get('task') or 'run'}")
                print(f"{worst:5s} [{cat}] {text}\n      {bad or ''} -> {got}  ask={ess}  {secs[-1]:.1f}s")
                ss = asst.sessions[r["session_id"]]
                if worst != "ok" and ss.get("llm_raw") is not None:
                    print(f"      model: {json.dumps(ss['llm_raw'], ensure_ascii=False)}")
                    rp = {k: v for k, v in (ss.get("llm_report") or {}).items() if v}
                    if rp:
                        print(f"      checks: {rp}")
    finally:
        asst.llm.close()
    n = sum(tally.values())
    print(f"\n{n} requests: {tally['ok']} right, {tally['asked']} asked, {tally['wrong']} wrong "
          f"({len(silent)} of them with no question)")
    print("fields:", fields)
    for cat, c in bycat.items():
        print(f"  {cat:9s} {c['ok']:3d} right {c['asked']:3d} asked {c['wrong']:3d} wrong")
    if secs:
        print(f"time per request: median {statistics.median(secs):.1f} s, max {max(secs):.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
