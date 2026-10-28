"""Requests and what they must be read as.

Each case: (text, expect). `expect` holds only what is checked:
  matrix          material id (or None: must be asked)
  fillers         [(id, content % or None, basis or None, shape or None, size µm or None)] in order;
                  "*" for a field not checked
  analyses        set of analysis keys (exactly)
  task            run | doe | calibration | optimization | structure
  quality, auto, directions, seeds, seed
  parallel        dict of the settings named
  ask             question ids that must be open (prefix match)
  noask           question ids that must not be open
  doe             list of (what, lo, hi, n levels)
  measurements    list of (property, value, content)
  unknowns        calibration unknowns
  ready           True when the payload must be there
"""

CASES = [
    # ---- A. plain Korean ------------------------------------------------------
    ("에폭시 수지 45%와 구형 알루미나 필러 55 vol%가 섞인 복합재의 열전도도 구해줘",
     {"matrix": "epoxy", "fillers": [("al2o3", 55, "vol", "sphere", None)], "analyses": {"thermal"}, "task": "run"}),
    ("에폭시에 알루미나 50% 넣었을 때 열전도도",
     {"matrix": "epoxy", "fillers": [("al2o3", 50, None, None, None)], "analyses": {"thermal"}, "ask": ["basis", "shape:0", "size:0", "quality", "parallel"]}),
    ("실리콘 수지에 질화알루미늄 60 부피% 10마이크로 구형, 열전도도",
     {"matrix": "silicone", "fillers": [("aln", 60, "vol", "sphere", 10)], "analyses": {"thermal"}}),
    ("폴리이미드에 BN 판상 25 vol% 열전도율",
     {"matrix": "polyimide", "fillers": [("hbn", 25, "vol", "platelet", None)], "analyses": {"thermal"}}),
    ("BT 레진에 실리카 40 wt% 유전율 구해줘",
     {"matrix": "bt", "fillers": [("sio2", 40, "wt", None, None)], "analyses": {"dielectric"}}),
    ("에폭시 기지에 은 필러 20 vol% 넣은 도전성 접착제의 전기전도도",
     {"matrix": "epoxy", "fillers": [("ag", 20, "vol", None, None)], "analyses": {"electrical"}}),
    ("PTFE에 실리카 30%를 넣은 기판의 Dk, Df",
     {"matrix": "ptfe", "fillers": [("sio2", 30, None, None, None)], "analyses": {"dielectric"}}),
    ("에폭시에 실리카 60% 열팽창계수랑 탄성계수",
     {"matrix": "epoxy", "fillers": [("sio2", 60, None, None, None)], "analyses": {"cte"}}),
    ("에폭시에 실리카 50% 점도",
     {"matrix": "epoxy", "fillers": [("sio2", 50, None, None, None)], "analyses": {"viscosity"}}),
    ("에폭시에 실리카 60% 흡습 특성",
     {"matrix": "epoxy", "fillers": [("sio2", 60, None, None, None)], "analyses": {"moisture"}}),
    ("에폭시에 카보닐철 40% 넣은 차폐재 EMI 차폐 효율",
     {"matrix": "epoxy", "fillers": [("carbonyl_iron", 40, None, None, None)], "analyses": {"emi"}}),
    ("에폭시에 니켈아연페라이트 50%의 투자율",
     {"matrix": "epoxy", "fillers": [("nizn_ferrite", 50, None, None, None)], "analyses": {"magnetic"}}),
    # ---- B. plain English -----------------------------------------------------
    ("epoxy with 60 vol% spherical silica 4 um, thermal conductivity and CTE",
     {"matrix": "epoxy", "fillers": [("sio2", 60, "vol", "sphere", 4)], "analyses": {"thermal", "cte"}}),
    ("silicone filled with 50 vol% alumina, 10 micron spheres, thermal conductivity",
     {"matrix": "silicone", "fillers": [("al2o3", 50, "vol", "sphere", 10)], "analyses": {"thermal"}}),
    ("thermal conductivity of PI with 20 wt% boron nitride platelets",
     {"matrix": "polyimide", "fillers": [("hbn", 20, "wt", "platelet", None)], "analyses": {"thermal"}}),
    ("permittivity of PTFE with 30% silica",
     {"matrix": "ptfe", "fillers": [("sio2", 30, None, None, None)], "analyses": {"dielectric"}}),
    ("LCP with 25 vol% fused silica, dielectric constant and loss tangent",
     {"matrix": "lcp", "fillers": [("sio2", 25, "vol", None, None)], "analyses": {"dielectric"}}),
    ("electrical conductivity of epoxy with 30 vol% silver flakes",
     {"matrix": "epoxy", "fillers": [("ag", 30, "vol", "platelet", None)], "analyses": {"electrical"}}),
    ("Young's modulus of epoxy with 40 vol% glass fibre, aspect ratio 10",
     {"matrix": "epoxy", "fillers": [("eglass", 40, "vol", "fiber", None)], "analyses": {"cte"}}),
    # ---- C. Korean typos ------------------------------------------------------
    ("애폭시레진 45%와 구형알루미나필러 55%가 섞인 복합재의 열전도도 구해줘",
     {"matrix": "epoxy", "fillers": [("al2o3", 55, None, "sphere", None)], "analyses": {"thermal"}}),
    ("에폭씨에 실리까 60% 열전도도", {"matrix": "epoxy", "fillers": [("sio2", 60, "*", "*", "*")], "analyses": {"thermal"}}),
    ("에폭시에 알루미냐 50% 열전도율", {"matrix": "epoxy", "fillers": [("al2o3", 50, "*", "*", "*")], "analyses": {"thermal"}}),
    ("에폭시에 질화붕서 30% 열전도도", {"matrix": "epoxy", "fillers": [("hbn", 30, "*", "*", "*")], "analyses": {"thermal"}}),
    ("폴리이미트에 실리카 20%", {"matrix": "polyimide", "fillers": [("sio2", 20, "*", "*", "*")]}),
    ("에폭시에 그래파이트 10%의 열전도도", {"matrix": "epoxy", "fillers": [("graphite", 10, "*", "*", "*")], "analyses": {"thermal"}}),
    ("애폭시에 씰리카 55% 열전도두", {"matrix": "epoxy", "fillers": [("sio2", 55, "*", "*", "*")], "analyses": {"thermal"}}),
    ("에폭시에 질화알루미눔 40% 열전도도", {"matrix": "epoxy", "fillers": [("aln", 40, "*", "*", "*")], "analyses": {"thermal"}}),
    # ---- D. English typos -----------------------------------------------------
    ("epocxy with 60% sillica, thermal conductivity", {"matrix": "epoxy", "fillers": [("sio2", 60, "*", "*", "*")], "analyses": {"thermal"}}),
    ("epoxy with 50% alumna, thermal conductivty", {"matrix": "epoxy", "fillers": [("al2o3", 50, "*", "*", "*")], "analyses": {"thermal"}}),
    ("sillicone with 40% aluminium nitrde", {"matrix": "silicone", "fillers": [("aln", 40, "*", "*", "*")]}),
    ("polymide with 20% boron nitrid", {"matrix": "polyimide", "fillers": [("hbn", 20, "*", "*", "*")]}),
    # ---- E. how contents are written ----------------------------------------------
    ("에폭시에 실리카 55퍼센트 열전도도", {"fillers": [("sio2", 55, None, "*", "*")]}),
    ("에폭시에 실리카 55프로 열전도도", {"fillers": [("sio2", 55, None, "*", "*")]}),
    ("에폭시에 실리카 오십오 퍼센트 열전도도", {"fillers": [("sio2", 55, None, "*", "*")]}),
    ("에폭시에 실리카 0.55만큼 열전도도", {"fillers": [("sio2", 55, None, "*", "*")]}),
    ("에폭시에 실리카 영점오오 들어간 거 열전도도", {"fillers": [("sio2", 55, None, "*", "*")]}),
    ("에폭시에 실리카 부피분율 0.55 열전도도", {"fillers": [("sio2", 55, "vol", "*", "*")]}),
    ("에폭시에 실리카 30 중량% 열전도도", {"fillers": [("sio2", 30, "wt", "*", "*")]}),
    ("에폭시에 실리카 30 wt.% 열전도도", {"fillers": [("sio2", 30, "wt", "*", "*")]}),
    ("에폭시에 실리카 55%(v/v) 열전도도", {"fillers": [("sio2", 55, "vol", "*", "*")]}),
    ("에폭시 100에 실리카 30 phr 열전도도", {"fillers": [("sio2", 23.0769, "wt", "*", "*")], "ready_auto": True}),
    ("에폭시에 실리카 1/3 열전도도", {"fillers": [("sio2", 33.3333, None, "*", "*")]}),
    ("에폭시에 실리카 삼분의 일 열전도도", {"fillers": [("sio2", 33.3333, None, "*", "*")]}),
    ("에폭시에 실리카를 절반 넣은 열전도도", {"fillers": [("sio2", 50, "*", "*", "*")]}),
    ("epoxy with fifty five percent silica, thermal conductivity", {"fillers": [("sio2", 55, None, "*", "*")]}),
    ("epoxy with silica at a volume fraction of 0.55, thermal conductivity", {"fillers": [("sio2", 55, "vol", "*", "*")]}),
    ("에폭시에 실리카 60 넣고 열전도도", {"fillers": [("sio2", 60, None, "*", "*")]}),
    ("에폭시 40%에 실리카 열전도도", {"matrix": "epoxy", "fillers": [("sio2", 60, "*", "*", "*")]}),
    ("에폭시에 실리카 0,55 열전도도", {"fillers": [("sio2", 55, None, "*", "*")]}),
    ("에폭시에 실리카 ５５％ 열전도도", {"fillers": [("sio2", 55, None, "*", "*")]}),
    # ---- F. sizes ---------------------------------------------------------------
    ("에폭시에 실리카 50% 5um 열전도도", {"fillers": [("sio2", 50, "*", "*", 5)]}),
    ("에폭시에 실리카 50% 5 µm 열전도도", {"fillers": [("sio2", 50, "*", "*", 5)]}),
    ("에폭시에 실리카 50% 5미크론 열전도도", {"fillers": [("sio2", 50, "*", "*", 5)]}),
    ("에폭시에 실리카 50% 500 nm 열전도도", {"fillers": [("sio2", 50, "*", "*", 0.5)]}),
    ("에폭시에 실리카 50% 입경 5 열전도도", {"fillers": [("sio2", 50, "*", "*", 5)]}),
    ("에폭시에 실리카 50% D50 8 열전도도", {"fillers": [("sio2", 50, "*", "*", 8)]}),
    ("에폭시에 실리카 50% 0.5 마이크로미터 열전도도", {"fillers": [("sio2", 50, "*", "*", 0.5)]}),
    # ---- G. shapes -------------------------------------------------------------
    ("에폭시에 판상 BN 30% 열전도도", {"fillers": [("hbn", 30, "*", "platelet", "*")]}),
    ("에폭시에 BN 플레이크 30% 열전도도", {"fillers": [("hbn", 30, "*", "platelet", "*")]}),
    ("에폭시에 탄소섬유 20% 종횡비 20 열전도도", {"fillers": [("carbon_fiber", 20, "*", "fiber", "*")]}),
    ("에폭시에 불규칙 실리카 60% 열전도도", {"fillers": [("sio2", 60, "*", "irregular", "*")]}),
    ("에폭시에 파쇄형 알루미나 50% 열전도도", {"fillers": [("al2o3", 50, "*", "irregular", "*")]}),
    ("에폭시에 큐브 알루미나 40% 열전도도", {"fillers": [("al2o3", 40, "*", "cube", "*")]}),
    # ---- H. several fillers --------------------------------------------------------
    ("에폭시에 알루미나 40%와 질화붕소 10% 열전도도",
     {"matrix": "epoxy", "fillers": [("al2o3", 40, "*", "*", "*"), ("hbn", 10, "*", "*", "*")], "analyses": {"thermal"}}),
    ("epoxy with 30 vol% silica and 20 vol% alumina, thermal conductivity",
     {"matrix": "epoxy", "fillers": [("sio2", 30, "vol", "*", "*"), ("al2o3", 20, "vol", "*", "*")]}),
    ("실리콘에 알루미나 10um 40%, 알루미나 아닌 질화알루미늄 2um 20% 열전도도",
     {"matrix": "silicone", "fillers": [("al2o3", 40, "*", "*", 10), ("aln", 20, "*", "*", 2)]}),
    # ---- I. matrix or filler ---------------------------------------------------------
    ("알루미늄에 SiC 50% 넣은 복합재 CTE", {"matrix": "al", "fillers": [("sic", 50, "*", "*", "*")], "analyses": {"cte"}}),
    ("실리콘에 질화붕소 판상 필러 30wt% 열전도도", {"matrix": "silicone", "fillers": [("hbn", 30, "wt", "platelet", "*")]}),
    ("에폭시에 실리콘 분말 30% 열전도도", {"matrix": "epoxy", "fillers": [("si", 30, "*", "*", "*")]}),
    ("구리에 다이아몬드 50% 열전도도", {"matrix": "cu", "fillers": [("diamond", 50, "*", "*", "*")]}),
    ("SU-8에 실리카 20%", {"matrix": "su8", "fillers": [("sio2", 20, "*", "*", "*")]}),
    ("FR-4", {"matrix": "fr4", "ask": ["filler_new", "analyses"]}),
    ("에폭시에 기공 20% 유전율", {"matrix": "epoxy", "fillers": [("air", 20, "*", "*", "*")], "analyses": {"dielectric"}}),
    # ---- J. analyses ----------------------------------------------------------------
    ("에폭시에 실리카 50% 전도도", {"ask": ["analysis_pick"]}),
    ("에폭시에 실리카 50% 열 전도도", {"analyses": {"thermal"}}),
    ("에폭시에 은 30% 전기 전도도", {"analyses": {"electrical"}}),
    ("에폭시에 실리카 50% 열적 물성", {"analyses": {"thermal", "cte"}}),
    ("에폭시에 실리카 50%", {"ask": ["analyses"]}),
    ("에폭시에 실리카 50% 휨 해석", {"analyses": {"thermomech"}, "ask": ["film"]}),
    ("에폭시에 실리카 50% 휨 해석, 필름 두께 40um", {"analyses": {"thermomech"}, "noask": ["film"]}),
    ("에폭시에 실리카 50% 줄 발열", {"analyses": {"joule"}, "mpsim_refuses": True}),
    # ---- K. tasks -----------------------------------------------------------------
    ("에폭시에 알루미나 10마이크로 구형 40~60% 범위로 5단계 DOE, 열전도도",
     {"task": "doe", "doe": [("content", 40, 60, 5)], "fillers": [("al2o3", "*", "*", "sphere", 10)]}),
    ("에폭시에 알루미나 함량을 40에서 60%까지 10%씩 바꿔가며 열전도도",
     {"task": "doe", "doe": [("content", 40, 60, 3)]}),
    ("epoxy with alumina from 40 to 60 vol% in 5 levels, thermal conductivity",
     {"task": "doe", "doe": [("content", 40, 60, 5)]}),
    ("에폭시에 실리카 40, 50, 60% 열전도도", {"task": "doe", "doe": [("content", 40, 60, 3)]}),
    ("에폭시에 실리카 50% 입경 2~10um 5단계 열전도도", {"task": "doe", "doe": [("size", 2, 10, 5)]}),
    ("에폭시에 실리카 20%일 때 0.45 W/mK, 40%일 때 0.8 W/mK 측정됐는데 계면저항 보정해줘",
     {"task": "calibration", "measurements": [("k", 0.45, 20), ("k", 0.8, 40)], "unknowns": ["r_int"], "analyses": {"thermal"}}),
    ("에폭시에 알루미나 50%에서 측정한 열전도도가 1.2 W/mK야. 보정해줘",
     {"task": "calibration", "measurements": [("k", 1.2, 50)]}),
    ("에폭시에 알루미나 함량을 40~60%로 바꿔가며 열전도도가 최대가 되는 조건 찾아줘",
     {"task": "optimization", "doe": [("content", 40, 60, "*")]}),
    ("에폭시에 실리카 40~70% CTE가 최소가 되도록 최적화", {"task": "optimization"}),
    ("에폭시에 실리카 50% 구조만 생성", {"task": "structure"}),
    # ---- L. settings ----------------------------------------------------------------
    ("에폭시에 실리카 50% 열전도도 빠르게", {"quality": "fast", "noask": ["quality"]}),
    ("에폭시에 실리카 50% 열전도도 정확하게", {"quality": "accurate"}),
    ("에폭시에 실리카 50% 열전도도, 코어 8개로", {"parallel": {"threads": 8}, "noask": ["parallel"]}),
    ("에폭시에 실리카 40~60% DOE 열전도도, 동시에 2개씩", {"parallel": {"concurrency": 2}}),
    ("에폭시에 실리카 50% 열전도도, 3번 반복", {"seeds": 3}),
    ("에폭시에 실리카 50% 열전도도, seed 5", {"seed": 5}),
    ("에폭시에 판상 BN 30% 열전도도 3방향", {"directions": "xyz"}),
    ("에폭시에 실리카 50% 열전도도 알아서 해줘", {"auto": True, "noask": ["quality", "parallel", "shape:0", "size:0", "basis"], "ready": True}),
    ("epoxy with 50% silica, thermal conductivity, use defaults", {"auto": True, "ready": True}),
    ("에폭시에 실리카 50% 열전도도, 모든 코어 사용", {"parallel": {"threads": 0}}),
    # ---- M. unknown and ambiguous --------------------------------------------------------
    ("XYZ필러 30%와 에폭시 열전도도", {"matrix": "epoxy", "ask": ["filler:0"]}),
    ("에폭시에 그래핀옥사이드 5% 열전도도", {"matrix": "epoxy", "ask": ["filler:0"]}),
    ("에폭시에 페라이트 50% 투자율", {"ask": ["filler:0"]}),
    ("에폭시에 유리 30% 열전도도", {"ask": ["filler:0"]}),
    ("레진에 실리카 50% 열전도도", {"matrix": None, "ask": ["matrix"]}),
    ("열전도도 구해줘", {"ask": ["matrix", "filler_new"]}),
    # ---- O. sentences that are not requests ----------------------------------------------------
    ("안녕하세요 오늘 날씨 좋네요", {"matrix": None, "fillers": []}),
    ("이거 왜 이렇게 오래 걸려", {"matrix": None, "fillers": []}),
    ("지난번 해석이랑 같은 조건으로 다시 해줘", {"matrix": None, "fillers": []}),
    ("please run it again with the same settings", {"matrix": None, "fillers": []}),
    ("hello how are you", {"matrix": None, "fillers": []}),
    # ---- P. contents that cannot be -----------------------------------------------------------
    ("에폭시에 실리카 120% 열전도도", {"ask": ["content:0"]}),
    ("에폭시에 실리카 0% 열전도도", {"ask": ["content:0"]}),
    ("에폭시에 실리카 70%, 알루미나 50% 열전도도", {"problems": True, "mpsim_refuses": True}),
    # ---- N. mixed languages ------------------------------------------------------------------
    ("epoxy에 silica 60% 열전도도", {"matrix": "epoxy", "fillers": [("sio2", 60, "*", "*", "*")], "analyses": {"thermal"}}),
    ("Al2O3 55vol% 에폭시 열전도도", {"matrix": "epoxy", "fillers": [("al2o3", 55, "vol", "*", "*")]}),
    ("silicone에 AlN 50% k값", {"matrix": "silicone", "fillers": [("aln", 50, "*", "*", "*")], "analyses": {"thermal"}}),
]
