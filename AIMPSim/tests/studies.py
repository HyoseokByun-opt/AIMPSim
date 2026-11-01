"""Design, optimisation and calibration requests - beside the one a user
first wrote - each with what it must become, and the loops run on each to
their answer.

    python tests/studies.py                          the rules alone
    python tests/studies.py --llm <llama-server.exe> <model.gguf>
    python tests/studies.py --loops                  also run every loop on a stand-in solver
    python tests/studies.py --holdout                the requests written after the changes

Reading: the task, the target(s) with their direction, the bounds, the
fillers, what the study varies (its DOE parameters, their ranges, the
number of cases and the grid), the goal of an optimisation, and the
measurements and unknowns of a calibration. A field read otherwise is
wrong; a field left open with a question is asked.

Loops (--loops): every design and optimisation request is planned, its DOE
"run" on an effective-medium stand-in of the property (differential
Bruggeman with Hasselman-Johnson particles for k, Maxwell Garnett for the
permittivity, Turner for the CTE, Mori-Tanaka for the modulus, a
percolation power law for the electrical conductivity) with 3 % scatter,
and the loop of the AI tab (loop.py) is followed round by round until it
answers. Each must end with "done" on a measured check, within the safety
limit, and its answer must hold on the stand-in itself. A calibration's
loop is followed on scripted results: reached, a range at its end, nothing
left (asked).
"""
from __future__ import annotations

import argparse
import copy
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from aimpsim.lexicon import Lexicon  # noqa: E402
from aimpsim.parser import parse  # noqa: E402
from aimpsim.planner import Planner  # noqa: E402
from run_tests import find_mpsim, host_for  # noqa: E402

# expectations: task; tg [(property, op, value, direction)]; m matrix; f filler ids; cmax, cmin; size (lo, hi);
# roles (DOE roles of a design); n cases; edge; basis; obj; prefer; goal and factors {(what, lo, hi)} of an
# optimisation; meas [(property, value, content)] and unk (the unknown keys run) of a calibration; shape {i: shape}
D, O, C = "design", "optimization", "calibration"
CASES = [
    # ---- designs ---------------------------------------------------------------------------------------
    ("실리콘 TIM 패드에 판상 BN을 넣어서 면내 열전도도 8 W/mK 이상을 최소 함량으로 만들고 싶습니다. BN 크기는 5~30um 중에서 "
     "골라주시고 최대 함량은 45vol%입니다.",
     {"task": D, "tg": [("k", ">=", 8.0, "xy")], "m": "silicone", "f": ["hbn"], "cmax": 45.0, "size": (5.0, 30.0),
      "roles": {"content", "size0"}, "n": 36, "edge": "own", "shape": {0: "platelet"}}),
    ("EMC용 에폭시에 구형 실리카를 넣어 CTE를 12 ppm/K 이하로 낮추고 싶은데, 실리카 함량을 최대한 줄이고 싶어요. 입자 크기는 "
     "0.5~20um, 최대 충전량 75vol%, 대입자/소입자 두 가지 크기로 배합비도 알려주세요.",
     {"task": D, "tg": [("alpha", "<=", 12.0, None)], "m": "epoxy", "f": ["sio2"], "cmax": 75.0, "size": (0.5, 20.0),
      "roles": {"content", "share", "size0", "size1"}, "n": 40, "edge": "own"}),
    ("에폭시에 알루미나와 질화알루미늄을 섞어서 열전도도 5 W/mK 이상이 되는 가장 낮은 총 함량과 두 필러의 배합비를 찾아줘. "
     "둘 다 구형 20um, 최대 68vol%, 계면저항 5E-9",
     {"task": D, "tg": [("k", ">=", 5.0, None)], "m": "epoxy", "f": ["al2o3", "aln"], "cmax": 68.0,
      "roles": {"content", "share"}, "n": 36, "edge": "fixed", "sizes": [20.0, 20.0], "r": (5e-9, None)}),
    ("Find the smallest loading of spherical AlN in silicone that gives at least 3 W/mK. AlN between 2 and 40 um, at "
     "most 60 vol%, interfacial resistance 2e-8 m2K/W, tell me the size too",
     {"task": D, "tg": [("k", ">=", 3.0, None)], "m": "silicone", "f": ["aln"], "cmax": 60.0, "size": (2.0, 40.0),
      "roles": {"content", "size0"}, "n": 36, "edge": "own", "r": (2e-8, None)}),
    ("언더필 레진(에폭시)에 실리카 넣어서 열팽창계수 25ppm/K 이하 되게 하려면 몇 % 넣어야 해? 실리카는 구형 1um",
     {"task": D, "tg": [("alpha", "<=", 25.0, None)], "m": "epoxy", "f": ["sio2"], "roles": {"content"}, "n": 9,
      "sizes": [1.0]}),
    ("20um 두께 폴리이미드 필름에 BN 판상 필러를 수직 정렬로 넣어 두께 방향 열전도도 2 W/mK 이상, 함량은 가장 적게. "
     "BN은 2~10um, 최대 40vol%",
     {"task": D, "tg": [("k", ">=", 2.0, "z")], "m": "polyimide", "f": ["hbn"], "cmax": 40.0, "size": (2.0, 10.0),
      "roles": {"content", "size0"}, "n": 36, "film": 20.0, "orient": "z", "shape": {0: "platelet"}}),
    ("열전도도 4 W/mK 이상 나오면서 점도가 가장 낮은 알루미나 크기 조합을 찾아줘. 에폭시, 총 함량 60~70vol%, 입자 크기 "
     "1~45um, 두 가지 크기",
     {"task": D, "tg": [("k", ">=", 4.0, None)], "m": "epoxy", "f": ["al2o3"], "cmax": 70.0, "cmin": 60.0,
      "size": (1.0, 45.0), "roles": {"content", "share", "size0", "size1"}, "n": 40, "obj": "viscosity"}),
    ("알루미나 대입자 20~70um과 소입자 0.5~5um을 섞어서 실리콘에서 열전도도 3 W/mK를 최소 함량으로 달성하는 배합 알려줘. "
     "최대 75vol%",
     {"task": D, "tg": [("k", ">=", 3.0, None)], "m": "silicone", "f": ["al2o3"], "cmax": 75.0,
      "roles": {"content", "share", "size0", "size1"}, "n": 40,
      "ranges": {"phases.0.size.d": (20.0, 70.0), "phases.1.size.d": (0.5, 5.0)}}),
    ("Epoxy film 50 um thick: what alumina blend (two sizes, 0.3-10 um, monodisperse) reaches k_z >= 2 W/mK with the "
     "least filler? Max 65 vol%. Within 2 vol% I'd take the lower viscosity, and packing should be good.",
     {"task": D, "tg": [("k", ">=", 2.0, "z")], "m": "epoxy", "f": ["al2o3"], "cmax": 65.0, "size": (0.3, 10.0),
      "roles": {"content", "share", "size0", "size1"}, "n": 40, "film": 50.0, "tol": 2.0,
      "prefer": {"low_viscosity", "high_packing"}}),
    ("에폭시에 은 플레이크 넣어서 전기전도도 1E4 S/m 이상 되는 최소 함량 찾아줘. 은 크기 5um, 최대 40vol%",
     {"task": D, "tg": [("sigma", ">=", 1e4, None)], "m": "epoxy", "f": ["ag"], "cmax": 40.0, "roles": {"content"},
      "n": 9, "shape": {0: "platelet"}, "sizes": [5.0]}),
    ("에폭시에 유리섬유 넣어서 탄성률 12 GPa 이상 되게 하는 최소 함량 알려줘, 섬유 지름 10um 길이 100um, 최대 50vol%",
     {"task": D, "tg": [("E", ">=", 12.0, None)], "m": "epoxy", "f": ["eglass"], "cmax": 50.0, "roles": {"content"},
      "n": 9}),
    ("PPE 수지에 실리카를 넣어서 유전율 3.0 이하로 유지하면서 CTE 30ppm/K 이하가 되는 최소 함량 찾아줘. 구형 5um, 최대 60vol%",
     {"task": D, "tg": [("eps_r", "<=", 3.0, None), ("alpha", "<=", 30.0, None)], "m": "ppe", "f": ["sio2"],
      "cmax": 60.0, "roles": {"content"}, "n": 9}),
    ("열전도도 1.5W/mK 정도 되는 실리카 함량 찾아줘. 에폭시, 결정질 실리카 구형 10um",
     {"task": D, "tg": [("k", "=", 1.5, None)], "m": "epoxy", "f": ["quartz"], "roles": {"content"}, "n": 9}),
    ("실리콘에 알루미나 70um, 5um, 0.5um 세 가지 크기 섞어서 열전도도 5 W/mK 이상 최소 함량",
     {"task": D, "tg": [("k", ">=", 5.0, None)], "m": "silicone", "f": ["al2o3"], "roles": {"content", "share", "share2"},
      "n": 30, "sizes": [70.0, 5.0, 0.5]}),
    ("We need k >= 1.2 W/mK in a BT resin substrate with as little boron nitride as possible; BN platelets 1-15 um, "
     "max 50 vol%, random orientation.",
     {"task": D, "tg": [("k", ">=", 1.2, None)], "m": "bt", "f": ["hbn"], "cmax": 50.0, "size": (1.0, 15.0),
      "roles": {"content", "size0"}, "n": 36, "orient": "iso"}),
    ("에폭시 열전도 3 넘기려면 알루미나 최소 몇프로? 크기도 추천좀 1~30마이크로 사이로",
     {"task": D, "tg": [("k", ">=", 3.0, None)], "m": "epoxy", "f": ["al2o3"], "size": (1.0, 30.0),
      "roles": {"content", "size0"}, "n": 36}),
    ("AlN 필러로 실리콘 갭필러 열전도도 6 W/mK 이상 맞추고 싶어. 필러 함량은 최소로, 대/소 입자 2종 블렌딩, 대입자 topcut 80um, "
     "소입자 최소 1um, 최대 함량 72vol%, 계면 열저항 1E-8, 입자간 접촉저항 2E-8",
     {"task": D, "tg": [("k", ">=", 6.0, None)], "m": "silicone", "f": ["aln"], "cmax": 72.0, "size": (1.0, 80.0),
      "roles": {"content", "share", "size0", "size1"}, "n": 40, "r": (1e-8, 2e-8)}),
    ("에폭시에 실리카 넣어서 열전도도 5 W/mK 이상 되는 최소 함량, 최대 60vol%, 크기 10um",
     {"task": D, "tg": [("k", ">=", 5.0, None)], "m": "epoxy", "f": ["sio2"], "cmax": 60.0, "roles": {"content"}, "n": 9,
      }),
    ("에폭시에 알루미나 넣어서 열전도도 2 W/mK 이상 되는 최소 wt%를 알려줘. 최대 90wt%, 구형 10um",
     {"task": D, "tg": [("k", ">=", 2.0, None)], "m": "epoxy", "f": ["al2o3"], "cmax": 90.0, "basis": "wt",
      "roles": {"content"}, "n": 9}),
    # found in the browser walk: the least content of a ceiling target (silica raises the permittivity) lies below the
    # study's range (22 vol% below the maximum): the loop extends the range downwards
    ("PPE 수지에 구형 실리카 5um를 넣어서 유전율 3.0 이하로 유지하면서 CTE 40ppm/K 이하가 되는 최소 함량 찾아줘. 최대 60vol%",
     {"task": D, "tg": [("eps_r", "<=", 3.0, None), ("alpha", "<=", 40.0, None)], "m": "ppe", "f": ["sio2"],
      "cmax": 60.0, "roles": {"content"}, "n": 9, "sizes": [5.0]}),
    # found while writing the browser walk: sizes said for a blend that also asks to "find"; "에폭시에서 열전도도 2 W/mK
    # 이상" (the composite's target, not epoxy's own k)
    ("실리콘에 구형 알루미나 20um, 10um, 5um 세 가지 크기를 섞어서 열전도도 1.5 W/mK 이상 되는 최소 함량 찾아줘. 최대 65vol%",
     {"task": D, "tg": [("k", ">=", 1.5, None)], "m": "silicone", "f": ["al2o3"], "cmax": 65.0,
      "roles": {"content", "share", "share2"}, "n": 30, "sizes": [20.0, 10.0, 5.0]}),
    ("알루미나 대입자 8~16um과 소입자 4~8um를 섞어서 에폭시에서 열전도도 2 W/mK 이상 되는 최소 함량과 배합 알려줘. 최대 65vol%",
     {"task": D, "tg": [("k", ">=", 2.0, None)], "m": "epoxy", "f": ["al2o3"], "cmax": 65.0,
      "roles": {"content", "share", "size0", "size1"}, "n": 40,
      "ranges": {"phases.0.size.d": (8.0, 16.0), "phases.1.size.d": (4.0, 8.0)}}),
    ("Blend alumina and BN in epoxy for k >= 4 W/mK at the lowest total vol%; alumina spheres 10 um, BN platelets "
     "10 um; max 60 vol%; give me the blend ratio",
     {"task": D, "tg": [("k", ">=", 4.0, None)], "m": "epoxy", "f": ["al2o3", "hbn"], "cmax": 60.0,
      "roles": {"content", "share"}, "n": 36}),
    # ---- optimisations ---------------------------------------------------------------------------------
    ("실리카 함량 50~75vol%, 크기 1~30um 범위에서 에폭시 CTE가 가장 낮아지는 조건 찾아줘",
     {"task": O, "goal": "min", "m": "epoxy", "f": ["sio2"], "factors": {("content", 50.0, 75.0), ("size", 1.0, 30.0)},
      "n": 25, "edge": "own"}),
    ("에폭시에 알루미나 넣고 함량 40~65%, 입자 크기 2~50um 바꿔가며 열전도도 최대 조건 찾아줘. 계면저항 1E-8",
     {"task": O, "goal": "max", "m": "epoxy", "f": ["al2o3"], "factors": {("content", 40.0, 65.0), ("size", 2.0, 50.0)},
      "n": 25, "edge": "own", "r": (1e-8, None)}),
    ("Vary the BN platelet loading from 10 to 40 vol% and size from 5 to 25 um in silicone, and find what maximises "
     "the in-plane thermal conductivity",
     {"task": O, "goal": "max", "m": "silicone", "f": ["hbn"], "factors": {("content", 10.0, 40.0), ("size", 5.0, 25.0)},
      "n": 25, "edge": "own"}),
    ("에폭시에 BaTiO3 함량 20~50%로 바꿔서 유전율이 최대가 되는 조건",
     {"task": O, "goal": "max", "m": "epoxy", "f": ["batio3"], "factors": {("content", 20.0, 50.0)}, "n": 5}),
    ("에폭시에 은 함량 10~40%로 바꿔가며 전기전도도 최대 조건",
     {"task": O, "goal": "max", "m": "epoxy", "f": ["ag"], "factors": {("content", 10.0, 40.0)}, "n": 5}),
    ("에폭시에 알루미나 크기 1~50um로 바꿔가며 열전도도 최대 조건, 함량은 55%, 계면저항 2E-8",
     {"task": O, "goal": "max", "m": "epoxy", "f": ["al2o3"], "factors": {("size", 1.0, 50.0)}, "n": 5, "edge": "own",
      "contents": [55.0], "r": (2e-8, None)}),
    # a value to be met over a range: read as a design that brings the property to it
    ("실리콘에 질화알루미늄 함량을 30~60%로 바꿔가며 열전도도가 2.5 W/mK에 가장 가까운 조건 찾아줘",
     {"task": D, "tg": [("k", "=", 2.5, None)], "m": "silicone", "f": ["aln"], "cmax": 60.0, "cmin": 30.0,
      "roles": {"content"}, "n": 9}),
    ("PPE에 실리카 10~50% 넣어서 유전율 3.0에 맞추는 함량 찾아줘",
     {"task": D, "tg": [("eps_r", "=", 3.0, None)], "m": "ppe", "f": ["sio2"], "cmax": 50.0, "cmin": 10.0,
      "roles": {"content"}, "n": 9}),
    # ---- calibrations ----------------------------------------------------------------------------------
    ("실리콘에 구형 알루미나 5um 40vol%, 50vol%, 60vol%에서 열전도도가 각각 0.9, 1.4, 2.3 W/mK로 측정됐어요. 계면저항을 보정해줘",
     {"task": C, "m": "silicone", "f": ["al2o3"], "meas": [("k", 0.9, 40.0), ("k", 1.4, 50.0), ("k", 2.3, 60.0)],
      "asked": ["r_int"]}),
    ("에폭시에 판상 BN 20wt%일 때 1.1 W/mK, 40wt%일 때 2.6 W/mK 실측. BN 열전도도 보정해줘",
     {"task": C, "m": "epoxy", "f": ["hbn"], "meas": [("k", 1.1, 20.0), ("k", 2.6, 40.0)], "asked": ["filler_k"],
      "basis": "wt"}),
    ("Measured k of epoxy with 30 vol% and 50 vol% spherical alumina (10 um): 0.62 and 1.35 W/mK. Calibrate the "
     "interfacial resistance.",
     {"task": C, "m": "epoxy", "f": ["al2o3"], "meas": [("k", 0.62, 30.0), ("k", 1.35, 50.0)], "asked": ["r_int"]}),
    ("에폭시+실리카 60vol% CTE 측정값 22 ppm/K, 70vol%에서 15 ppm/K. 실리카 CTE 보정",
     {"task": C, "m": "epoxy", "f": ["sio2"], "meas": [("alpha", 22.0, 60.0), ("alpha", 15.0, 70.0)],
      "asked": ["filler_alpha"]}),
    ("에폭시에 알루미나 10um 50vol%, 측정값 1.6 W/mK. 에폭시 열전도도와 계면저항 둘 다 맞춰줘",
     {"task": C, "m": "epoxy", "f": ["al2o3"], "meas": [("k", 1.6, 50.0)], "asked": ["r_int", "matrix_k"]}),
    ("실리카 30%에서 10 W/mK 측정, 에폭시. 보정",
     {"task": C, "m": "epoxy", "f": ["sio2"], "meas": [("k", 10.0, 30.0)], "asked": ["r_int"]}),
]


# written after the changes CASES led to, and read as they came out the first time
HOLDOUT = [
    ("방열 갭패드용 실리콘에 MgO를 넣어서 열전도도 2.5W/mK 이상 나오는 최소 충전량이랑 MgO 입경(10~60um 사이) 추천해줘. 충전량 상한 65%",
     {"task": D, "tg": [("k", ">=", 2.5, None)], "m": "silicone", "f": ["mgo"], "cmax": 65.0, "size": (10.0, 60.0),
      "roles": {"content", "size0"}, "n": 36, "edge": "own"}),
    ("Si3N4 filler in epoxy: what's the minimum vol% to get through-plane k of 1.5 W/mK in a 30 um film? Particles 1 to "
     "10 um, no more than 55 vol%",
     {"task": D, "tg": [("k", ">=", 1.5, "z")], "m": "epoxy", "f": ["si3n4"], "cmax": 55.0, "size": (1.0, 10.0),
      "roles": {"content", "size0"}, "n": 36, "film": 30.0}),
    ("에폭시 몰딩에 구상 실리카 대/소 2종 블렌딩으로 CTE 9 ppm/K 이하 맞추고 싶은데 최소 충전량이 얼마일까요? 대입자 10~40um, "
     "소입자 0.5~3um, 최대 85vol%, 점도 낮은 쪽 선호",
     {"task": D, "tg": [("alpha", "<=", 9.0, None)], "m": "epoxy", "f": ["sio2"], "cmax": 85.0,
      "roles": {"content", "share", "size0", "size1"}, "n": 40, "prefer": {"low_viscosity"},
      "ranges": {"phases.0.size.d": (10.0, 40.0), "phases.1.size.d": (0.5, 3.0)}}),
    ("PI 필름(25um)에 BN 넣어 면내 열전도도 3W/mK 넘기는 최소 함량, BN 크기 3um 고정, 최대 30vol%",
     {"task": D, "tg": [("k", ">=", 3.0, "xy")], "m": "polyimide", "f": ["hbn"], "cmax": 30.0, "roles": {"content"},
      "n": 9, "film": 25.0, "sizes": [3.0]}),
    ("알루미나 40um, 4um 두 가지를 섞어서 실리콘에서 열전도도 4W/mK 이상 되는 최소 총함량과 미세입자 비율 알려줘. 최대 75%",
     {"task": D, "tg": [("k", ">=", 4.0, None)], "m": "silicone", "f": ["al2o3"], "cmax": 75.0,
      "roles": {"content", "share"}, "n": 36, "sizes": [40.0, 4.0]}),
    ("LCP에 실리카를 섞어 유전율 3.2 이하와 CTE 15 ppm/K 이하를 동시에 만족하는 최소 실리카 함량 (최대 50vol%, 구형 2um)",
     {"task": D, "tg": [("eps_r", "<=", 3.2, None), ("alpha", "<=", 15.0, None)], "m": "lcp", "f": ["sio2"],
      "cmax": 50.0, "roles": {"content"}, "n": 9, "sizes": [2.0]}),
    ("구리 분말 에폭시에 넣어서 전기전도도 100 S/cm 이상 되는 최소 함량. 구리 10um 구형, 최대 50vol%",
     {"task": D, "tg": [("sigma", ">=", 1e4, None)], "m": "epoxy", "f": ["cu"], "cmax": 50.0, "roles": {"content"},
      "n": 9, "sizes": [10.0]}),
    ("SiC 입자를 알루미늄 6061에 넣어서 CTE 15ppm/K 이하가 되는 최소 함량 찾아줘. SiC 20um, 최대 60vol%",
     {"task": D, "tg": [("alpha", "<=", 15.0, None)], "m": "al6061", "f": ["sic"], "cmax": 60.0, "roles": {"content"},
      "n": 9, "sizes": [20.0]}),
    ("에폭시에 다이아몬드 입자 넣어서 열전도도 10W/mK 이상, 최소 함량, 다이아 크기 20~100um, 최대 60vol%, 계면저항 1e-8",
     {"task": D, "tg": [("k", ">=", 10.0, None)], "m": "epoxy", "f": ["diamond"], "cmax": 60.0, "size": (20.0, 100.0),
      "roles": {"content", "size0"}, "n": 36, "r": (1e-8, None)}),
    ("Using ZnO in silicone, what is the lowest loading that keeps the thermal conductivity at or above 1 W/mK? ZnO 1 um, "
     "up to 50 vol%.",
     {"task": D, "tg": [("k", ">=", 1.0, None)], "m": "silicone", "f": ["zno"], "cmax": 50.0, "roles": {"content"},
      "n": 9, "sizes": [1.0]}),
    ("MgO 함량 30~60vol%와 입경 5~50um를 바꿔가면서 실리콘 복합재 열전도도가 최대인 조건을 찾아줘",
     {"task": O, "goal": "max", "m": "silicone", "f": ["mgo"], "factors": {("content", 30.0, 60.0), ("size", 5.0, 50.0)},
      "n": 25, "edge": "own"}),
    ("실리카 크기를 0.5~20um 범위에서 바꿔서 에폭시 70vol% CTE 최소 조건",
     {"task": O, "goal": "min", "m": "epoxy", "f": ["sio2"], "factors": {("size", 0.5, 20.0)}, "n": 5, "contents": [70.0]}),
    ("Find the AlN loading between 20 and 50 vol% that gives the lowest CTE in epoxy",
     {"task": O, "goal": "min", "m": "epoxy", "f": ["aln"], "factors": {("content", 20.0, 50.0)}, "n": 5}),
    ("에폭시에 BaTiO3 10~40vol% 바꿔가며 유전율이 20에 가장 가까운 함량",
     {"task": D, "tg": [("eps_r", "=", 20.0, None)], "m": "epoxy", "f": ["batio3"], "cmax": 40.0, "cmin": 10.0,
      "roles": {"content"}, "n": 9}),
    ("실리콘에 알루미나 함량 50~70%, 크기 10~70um, 계면저항 2E-8로 열전도도 최대 조건 찾아줘, 빠르게",
     {"task": O, "goal": "max", "m": "silicone", "f": ["al2o3"], "factors": {("content", 50.0, 70.0), ("size", 10.0, 70.0)},
      "n": 25, "r": (2e-8, None)}),
    ("실리콘 + AlN 30, 45, 60 vol%에서 측정한 열전도도가 0.8, 1.6, 3.4 W/mK입니다. 계면 열저항을 역산해 주세요",
     {"task": C, "m": "silicone", "f": ["aln"], "meas": [("k", 0.8, 30.0), ("k", 1.6, 45.0), ("k", 3.4, 60.0)],
      "asked": ["r_int"]}),
    ("We measured 0.45 and 0.92 W/mK for epoxy with 20 and 40 vol% spherical silica. Fit the filler conductivity.",
     {"task": C, "m": "epoxy", "f": ["sio2"], "meas": [("k", 0.45, 20.0), ("k", 0.92, 40.0)], "asked": ["filler_k"]}),
    ("에폭시+알루미나(10um) 50vol% 시편 CTE 실측 25 ppm/K, 에폭시 CTE를 보정해줘",
     {"task": C, "m": "epoxy", "f": ["al2o3"], "meas": [("alpha", 25.0, 50.0)], "asked": ["matrix_alpha"]}),
    ("BN 판상 30vol% 실리콘 복합재 면내 열전도도 측정 5.2 W/mK, 계면저항 맞춰줘",
     {"task": C, "m": "silicone", "f": ["hbn"], "meas": [("k", 5.2, 30.0)], "asked": ["r_int"], "shape": {0: "platelet"},
      "meas_dir": "x"}),
    ("유전율 측정값: PPE+실리카 20vol% 3.0, 40vol% 3.4. 실리카 유전율 보정",
     {"task": C, "m": "ppe", "f": ["sio2"], "meas": [("eps_r", 3.0, 20.0), ("eps_r", 3.4, 40.0)], "asked": ["filler_eps_r"]}),
]


def _f(x):
    return None if x is None else float(x)


def grade(exp, it, r, planner):
    """{field: ok | asked | wrong} of one reading (it) and its plan (r, with "decide for me")."""
    out = {}
    qs = [q["id"] for q in r["questions"] if q["essential"]]

    def g(name, got, want):
        out[name] = "ok" if got == want else ("asked" if got in (None, [], set()) and qs else "wrong")
    task = it.get("task") or "run"
    g("task", task, exp["task"])
    g("matrix", (it.get("matrix") or {}).get("id"), exp["m"])
    fl = it.get("fillers") or []
    # one material in two sizes may be written as two copies of it (a blend of sizes): the materials count
    g("fillers", sorted({str(f.get("id")) for f in fl}), sorted(exp["f"]))
    for i, sh in (exp.get("shape") or {}).items():
        g(f"shape{i}", fl[i].get("shape") if i < len(fl) else None, sh)
    p = r.get("payload")
    if exp["task"] == D:
        d = it.get("design") or {}
        tg = [(t["property"], t["op"], t["value"], t.get("direction")) for t in d.get("targets") or []]
        g("targets", tg, exp["tg"])
        for k, key in (("cmax", "content_max"), ("cmin", "content_min"), ("tol", "tol")):
            if k in exp:
                g(k, _f(d.get(key)), exp[k])
        if "size" in exp:
            g("size", (_f(d.get("size_min_um")), _f(d.get("size_max_um"))), exp["size"])
        if "prefer" in exp:
            g("prefer", set(d.get("prefer") or []), exp["prefer"])
        if p is None or p.get("kind") != "design":
            out["plan"] = "asked" if qs else "wrong"
            return out
        sp = p["design"]
        g("roles", set(sp["roles"].values()), exp["roles"])
        g("n", p["doe"]["n_cases"], exp["n"])
        g("analyses", set(a for a, v in p["form"]["analyses"].items() if v) >= {
            {"k": "thermal", "alpha": "cte", "eps_r": "dielectric", "E": "cte", "sigma": "electrical"}[t[0]] for t in exp["tg"]}, True)
        if "edge" in exp:
            g("edge", p["doe"]["edge"], exp["edge"])
        if "basis" in exp:
            g("basis", sp["basis"], exp["basis"])
        if "obj" in exp:
            g("obj", sp["objective"], exp["obj"])
        if "sizes" in exp:
            g("sizes", [round(x["size"]["d"], 6) for x in p["form"]["phases"]], exp["sizes"])
        for path, rg in (exp.get("ranges") or {}).items():
            pp = next((x for x in p["doe"]["parameters"] if x["path"] == path), None)
            g("range " + path, (pp["min"], pp["max"]) if pp else None, rg)
        if len(exp["tg"]) > 1:
            g("targets in the plan", [(t["property"], t["op"], t["value"]) for t in sp.get("targets") or []],
              [t[:3] for t in exp["tg"]])
    elif exp["task"] == O:
        g("goal", (it.get("optimization") or {}).get("goal"), exp["goal"])
        fs = {(f["what"], _f((f.get("range") or [None, None])[0]), _f((f.get("range") or [None, None])[1]))
              for f in (it.get("doe") or {}).get("factors") or []}
        g("factors", fs, exp["factors"])
        if p is None:
            out["plan"] = "asked" if qs else "wrong"
            return out
        g("n", p["doe"]["n_cases"], exp["n"])
        if "edge" in exp:
            g("edge", p["doe"]["edge"], exp["edge"])
        if "contents" in exp:
            g("contents", [x["fraction"]["value"] for x in p["form"]["phases"]], exp["contents"])
    else:
        ms = [(m["property"], m["value"], _f(m.get("content"))) for m in it["calibration"]["measurements"]]
        g("measurements", ms, exp["meas"])
        if p is None or not p.get("cal"):
            out["plan"] = "asked" if qs else "wrong"
            return out
        g("asked", list(p["cal"].get("asked") or []), exp["asked"])
        if "meas_dir" in exp:
            g("direction measured", {m.get("direction") for m in p["cal"]["measurements"]}, {exp["meas_dir"]})
        if "basis" in exp:
            g("basis", p["form"]["phases"][0]["fraction"].get("basis"), exp["basis"])
    if "r" in exp:
        itf = it.get("interface") or {}
        g("resistances", (_f(itf.get("r_int")), _f(itf.get("r_contact"))), exp["r"])
    if "film" in exp:
        g("film", _f(it.get("film")), exp["film"])
    if "orient" in exp:
        g("orientation", it.get("orientation"), exp["orient"])
    if p is not None and planner.host.get("validate"):
        err = planner.host["validate"](p["form"])
        out["MPSim accepts"] = "ok" if not err else "wrong"
    return out


# ---------------------------------------------------------------------- the stand-in solver
def truth(form, prop):
    """The property of a case form on closed forms (spheres; the shape and orientation are ignored)."""
    from mpsim import spec as S
    from mpsim.calibrate import dem_conductivity, fill_props
    sp = S.normalize(fill_props(form))
    m = sp["matrix"]["props"]
    ph = [(float(x["vf"]), x["props"], float(x["size_um"].get("d") or 1.0) * 1e-6, float(x.get("r_int") or 0.0))
          for x in sp["phases"]]
    phi = sum(v for v, *_ in ph)
    if prop == "k":
        return dem_conductivity(float(m["k"]), [(v, float(p["k"]), r, d) for v, p, d, r in ph])
    if prop == "eps_r":
        e = float(m["eps_r"])
        # Maxwell Garnett with the fillers' mean polarisability
        b = sum(v * (float(p["eps_r"]) - e) / (float(p["eps_r"]) + 2 * e) for v, p, *_ in ph)
        return e * (1 + 2 * b) / (1 - b)
    if prop in ("alpha", "E"):
        def kg(E, nu):
            return E / (3 * (1 - 2 * nu)), E / (2 * (1 + nu))
        Km, Gm = kg(float(m["E"]), 0.35)
        fs = [(v, *kg(float(p["E"]), 0.22), float(p["alpha"])) for v, p, *_ in ph]
        if prop == "E":
            # Mori-Tanaka for spheres, the fillers taken as one (their volume-weighted moduli)
            Kf = sum(v * k for v, k, _, _ in fs) / phi
            Gf = sum(v * g for v, _, g, _ in fs) / phi
            fm = Gm * (9 * Km + 8 * Gm) / (6 * (Km + 2 * Gm))
            K = Km + phi * (Kf - Km) / (1 + (1 - phi) * (Kf - Km) / (Km + 4 * Gm / 3))
            G = Gm + phi * (Gf - Gm) / (1 + (1 - phi) * (Gf - Gm) / (Gm + fm))
            return 9 * K * G / (3 * K + G)
        # Turner: the expansion weighted by bulk modulus
        num = (1 - phi) * Km * float(m["alpha"]) + sum(v * k * a for v, k, _, a in fs)
        den = (1 - phi) * Km + sum(v * k for v, k, _, _ in fs)
        return num / den
    if prop == "sigma":
        sm = float(m["sigma"])
        sf = max(float(p["sigma"]) for _, p, *_ in ph)
        pc = 0.16
        return sm + (sf * ((phi - pc) / (1 - pc)) ** 2.0 if phi > pc else 0.0)
    raise ValueError(prop)


def run_loops(cases, lex, host, verbose=False):
    """Every design and optimisation request planned and followed by its loop on the stand-in."""
    import numpy as np
    sys.path.insert(0, find_mpsim())
    from mpsim import doe as DOE
    from mpsim.calibrate import fill_props
    from aimpsim import design as DZ
    planner = Planner(lex, host)
    errs, n = [], 0
    for text, exp in cases:
        if exp["task"] not in (D, O):
            continue
        r = planner.resolve(parse(text, lex), {"_auto": True})
        p = r["payload"]
        if not p or not p.get("doe"):
            errs.append(f"no study: {text[:50]}")
            continue
        n += 1
        base, params = fill_props(p["form"]), p["doe"]["parameters"]
        rng = np.random.default_rng(11)
        if exp["task"] == D:
            sp = p["design"]
            tgs = sp.get("targets") or [sp["target"]]
        else:
            an = p["opt"]["analysis"]
            tgs = [{"property": {"thermal": "k", "cte": "alpha", "dielectric": "eps_r", "electrical": "sigma"}[an],
                    "response": {"thermal": "k", "cte": "alpha", "dielectric": "eps", "electrical": "sigma"}[an]}]

        def run(values, label="case"):
            f = DOE.apply_case(base, {"values": values, "label": label}, parameters=params)
            met = {}
            for t in tgs:
                v = truth(f, t["property"])
                met[t.get("response") or DZ.PROP_RESPONSE[t["property"]]] = v * (1 + 0.03 * rng.standard_normal())
            ph = f["phases"]
            met["real_filler"] = sum(x["fraction"]["value"] for x in ph) - 0.2
            return {"state": "done", "values": values, "label": label, "job_id": "x", "metrics": met}
        first = [run(c["values"], c["label"]) for c in DOE.expand(params, p["doe"]["design"], p["doe"]["samples"], 1)]
        study = {"parameters": params, "base_form": base}
        sp = p.get("design")
        variants = [(sp, "as asked")]
        if exp["task"] == D:
            # what the stand-in can reach in the ranges: a target beyond it must end "unreachable"; then the same
            # study with a target it can reach must end with a checked recipe
            from mpsim import optimise as OPT
            grid = [{}]
            for q, (lo, hi) in zip(params, OPT._bounds(params)):
                lv = [math.exp(math.log(lo) + (math.log(hi) - math.log(lo)) * k / 4.0) if q.get("scale") == "log" and lo > 0
                      else lo + (hi - lo) * k / 4.0 for k in range(5)]
                grid = [dict(gp, **{q["path"]: v}) for gp in grid for v in lv]
            fv = [{t["property"]: truth(DOE.apply_case(base, {"values": gp, "label": ""}, parameters=params), t["property"])
                   for t in tgs} for gp in grid]

            def reach(ts, margin):
                def ok(v, t):
                    if t["op"] == ">=":
                        return v >= t["value"] * (1 + margin)
                    if t["op"] == "<=":
                        return v <= t["value"] * (1 - margin)
                    return True
                if any(t["op"] == "=" for t in ts):
                    t = next(t for t in ts if t["op"] == "=")
                    vs = [v[t["property"]] for v in fv]
                    return min(vs) * (1 + margin) <= t["value"] <= max(vs) * (1 - margin)
                return any(all(ok(v[t["property"]], t) for t in ts) for v in fv)
            if not reach(tgs, -0.05):
                t0 = tgs[0]
                vs = [v[t0["property"]] for v in fv]
                new = dict(t0, value=float(f"{(0.55 * max(vs) + 0.45 * min(vs) if t0['op'] != '<=' else 0.55 * min(vs) + 0.45 * max(vs)):.3g}"))
                variants = [(sp, "unreachable"), (dict(sp, target=new, targets=[new] + list(tgs[1:])), f"reachable {new['value']:g}")]
            elif not reach(tgs, 0.05):
                variants = [(sp, "borderline")]
        for spv, how in variants:
            if spv is not None:
                sp = spv
                tgs = sp.get("targets") or [sp["target"]]
            rows = list(first)
            loop_one(text, exp, how, sp, tgs, study, rows, run, base, params, p, errs, verbose)
    return errs, n


def loop_one(text, exp, how, sp, tgs, study, rows, run, base, params, p, errs, verbose):
    """One loop of a request followed to its end; its answer checked on the stand-in."""
    import numpy as np
    from mpsim import doe as DOE
    from aimpsim import design as DZ
    from aimpsim import loop as LP
    if True:
        state, final, seen = {}, None, []
        for _ in range(LP.MAX_ROUNDS + 3):
            if exp["task"] == D:
                out = LP.design_round(study, rows, sp, state)
            else:
                out = LP.opt_round(study, rows, tgs[0]["response"], p["opt"]["goal"], p["opt"].get("target"), state)
            state = out.get("state") or state
            seen.append(f"{out['action']}:{out.get('why')}")
            if not LP.explain(out, "design" if exp["task"] == D else "opt", "ko"):
                errs.append(f"no words for a round: {text[:40]}")
            if out["action"] == "refine" or (exp["task"] == O and out["action"] == "check"):
                rows += [run(v, "added") for v in out["points"]]
            elif out["action"] == "check" and exp["task"] == D:
                v = state["check"]["values"]
                res = out["result"]
                pick = res.get("recommended") or res.get("best")
                vals = dict(v)
                ci = next((q for q, ro in sp["roles"].items() if ro == "content"), None)
                if ci and pick.get("asked"):
                    vals[ci] = pick["asked"]
                seeds = [run(vals, "check") for _ in range(3)]
                got = {k: float(np.mean([s["metrics"][k] for s in seeds])) for k in seeds[0]["metrics"]}
                r0 = tgs[0].get("response") or DZ.PROP_RESPONSE[tgs[0]["property"]]
                state["check"].update(value=got[r0], measured=got, ci=float(np.std([s["metrics"][r0] for s in seeds])),
                                      real=got["real_filler"])
            else:
                final = out
                break
        rounds = len(seen)
        tag = f"[{how}]"
        if how == "unreachable":
            ok = final is not None and final["action"] == "stop" and final.get("why") in ("unreachable", "no_points")
            if not ok:
                errs.append(f"loop (target out of reach) did not stop as unreachable: {text[:50]} {seen}")
            elif verbose:
                print(f"loop  {rounds:2d} rounds  stop:{final.get('why')}  {tag}  {text[:60]}")
            return
        if how == "borderline" and final is not None and final["action"] == "stop" and final.get("why") == "unreachable":
            if verbose:
                print(f"loop  {rounds:2d} rounds  stop:unreachable  {tag}  {text[:60]}")
            return
        if final is None or final["action"] != "done":
            errs.append(f"loop did not answer {tag}: {text[:50]} {seen}")
            return
        # the answer holds on the stand-in itself
        if exp["task"] == D:
            rec = final["result"].get("recommended") or {}
            f = DOE.apply_case(base, {"values": rec["values"], "label": "answer"}, parameters=params)
            bad = []
            for t in tgs:
                v = truth(f, t["property"])
                tol = 0.06 * abs(t["value"]) if t["property"] != "sigma" else 0.5 * t["value"]
                if (t["op"] == ">=" and v < t["value"] - tol) or (t["op"] == "<=" and v > t["value"] + tol) or \
                        (t["op"] == "=" and abs(v - t["value"]) > tol):
                    bad.append(f"{t['property']} {v:.4g} vs {t['op']} {t['value']}")
            if bad:
                errs.append(f"design answer misses on the stand-in {tag}: {text[:50]} {bad} {rec.get('content')}")
            elif verbose:
                print(f"loop  {rounds:2d} rounds  {rec.get('content')} vol%  {tag}  {' '.join(seen)}  {text[:50]}")
        else:
            best = final.get("best") or {}
            if "measured" not in best:
                errs.append(f"optimum without a measured run: {text[:50]} {seen}")
                return
            # no point of the ranges does better than the answer by more than the scatter (a grid on the stand-in)
            from mpsim import optimise as OPT
            bounds = OPT._bounds(params)
            grid = [{}]
            for q, (lo, hi) in zip(params, bounds):
                grid = [dict(gp, **{q["path"]: lo + (hi - lo) * k / 6.0}) for gp in grid for k in range(7)]
            prop = tgs[0]["property"]
            vals = [truth(DOE.apply_case(base, {"values": gp, "label": ""}, parameters=params), prop) for gp in grid]
            ans = truth(DOE.apply_case(base, {"values": best["values"], "label": ""}, parameters=params), prop)
            goal = p["opt"]["goal"]
            top = max(vals) if goal == "max" else min(vals)
            span = (max(vals) - min(vals)) or 1.0
            gap = (top - ans) if goal == "max" else (ans - top)
            if prop == "sigma":
                gap = math.log10(max(top, 1e-30)) - math.log10(max(ans, 1e-30)) if goal == "max" else 0.0
                span = 1.0
            if gap > 0.08 * span:
                errs.append(f"optimum off on the stand-in: {text[:50]} answer {ans:.4g} best {top:.4g} {seen}")
            elif verbose:
                print(f"loop  {rounds:2d} rounds  {ans:.4g} (grid best {top:.4g})  {' '.join(seen)}  {text[:50]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", nargs=2, metavar=("SERVER_EXE", "MODEL"))
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--loops", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--holdout", action="store_true", help="the requests written after the changes instead")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    host = host_for(find_mpsim())
    lex = Lexicon(host.get("library") or [])
    planner = Planner(lex, host)
    asst = None
    if a.llm:
        from aimpsim.llm import LocalLLM
        from aimpsim.web import Assistant
        asst = Assistant(host)
        asst.llm = LocalLLM({"server_exe": a.llm[0], "model": a.llm[1], "threads": a.threads, "timeout_s": 300})
        if not asst.llm._start():
            sys.exit("the model server did not start")
        planner = asst.planner
    cases = [c for c in (HOLDOUT if a.holdout else CASES) if not a.only or a.only in c[0]]
    tally = {"ok": 0, "asked": 0, "wrong": 0}
    try:
        for text, exp in cases:
            if asst:
                r0 = asst.interpret(text, new=True)
                it = copy.deepcopy(asst.sessions[r0["session_id"]]["intent"])
            else:
                it = parse(text, lex)
            r = planner.resolve(copy.deepcopy(it), {"_auto": True})
            out = grade(exp, it, r, planner)
            worst = "wrong" if "wrong" in out.values() else "asked" if "asked" in out.values() else "ok"
            tally[worst] += 1
            if worst != "ok":
                bad = {k: v for k, v in out.items() if v != "ok"}
                print(f"{worst:5s} {text[:90]}\n      {bad}")
    finally:
        if asst:
            asst.llm.close()
    print(f"\n{len(cases)} requests: {tally['ok']} right, {tally['asked']} asked, {tally['wrong']} wrong")
    errs = []
    if a.loops and not a.llm:
        errs, n = run_loops(cases, lex, host, a.v)
        for e in errs:
            print("LOOP  " + e)
        print(f"loops: {n} studies, {len(errs)} problems")
    return 1 if tally["wrong"] or errs else 0


if __name__ == "__main__":
    sys.exit(main())
