"""The words AIMPSim knows: materials of the MPSim library, analyses,
shapes, roles, task and setting words, in Korean and English.

Only names are kept here - never a property value. A material is always
taken from the MPSim library by its id, with the values the library holds;
a word that names no library material is asked about, not invented.

Aliases are matched after squashing (lower case, no spaces, hyphens or
dots), so "Al2O3", "al 2 o 3" and "AL2O3" are one alias. Typos are found by
phonetic.similarity; the aliases below are the spellings in use.
"""

# id -> aliases. "ko"/"en" are names; "formula" chemical formulae and trade
# or common abbreviations (matched exactly, never fuzzily: "BN", "Ag").
MATERIALS = {
    # ---- polymers (matrices) ----
    "epoxy": {"ko": ["에폭시", "에폭시수지", "에폭시레진", "에폭시 수지", "이엠씨", "언더필수지", "몰딩컴파운드"],
              "en": ["epoxy", "epoxy resin", "epoxide", "emc", "molding compound", "mould compound"], "formula": ["EP"]},
    "bt": {"ko": ["비티레진", "비티수지", "비스말레이미드트리아진", "비스말레이미드"], "en": ["bt resin", "bismaleimide triazine",
           "bismaleimide-triazine", "bismaleimide"], "formula": ["BT"]},
    "polyimide": {"ko": ["폴리이미드", "피아이"], "en": ["polyimide"], "formula": ["PI"]},
    "pbo": {"ko": ["피비오", "폴리벤즈옥사졸"], "en": ["polybenzoxazole"], "formula": ["PBO"]},
    "bcb": {"ko": ["비씨비", "벤조사이클로부텐"], "en": ["benzocyclobutene"], "formula": ["BCB"]},
    "su8": {"ko": ["에스유8", "에스유에잇"], "en": ["su-8", "su8", "epoxy photoresist"], "formula": ["SU-8", "SU8"]},
    "silicone": {"ko": ["실리콘수지", "실리콘레진", "실리콘고무", "실리콘겔", "실리콘 수지", "피디엠에스", "실리콘오일"],
                 "en": ["silicone", "silicone resin", "silicone rubber", "silicone gel", "pdms", "polydimethylsiloxane"],
                 "formula": ["PDMS"]},
    "ppe": {"ko": ["피피이", "폴리페닐렌에테르", "폴리페닐렌옥사이드"], "en": ["polyphenylene ether", "polyphenylene oxide"],
            "formula": ["PPE", "PPO"]},
    "lcp": {"ko": ["엘씨피", "액정폴리머", "액정 폴리머", "액정고분자"], "en": ["liquid crystal polymer"], "formula": ["LCP"]},
    "ptfe": {"ko": ["피티에프이", "불소수지", "폴리테트라플루오로에틸렌"], "en": ["ptfe",
             "polytetrafluoroethylene"], "formula": ["PTFE"]},
    "peek": {"ko": ["피크", "폴리에테르에테르케톤"], "en": ["peek", "polyether ether ketone"], "formula": ["PEEK"]},
    "parylene_c": {"ko": ["파릴렌", "패럴린", "파릴렌씨"], "en": ["parylene", "parylene c"], "formula": []},
    "cyanate_ester": {"ko": ["시아네이트에스터", "시아네이트 에스테르", "시아네이트"], "en": ["cyanate ester", "cyanate"],
                      "formula": ["CE"]},
    "pps": {"ko": ["피피에스", "폴리페닐렌설파이드"], "en": ["polyphenylene sulfide"], "formula": ["PPS"]},
    "fr4": {"ko": ["에프알4", "유리에폭시적층판"], "en": ["fr-4", "fr4", "glass epoxy laminate"], "formula": ["FR-4", "FR4"]},
    # ---- inorganic fillers ----
    "sio2": {"ko": ["실리카", "용융실리카", "용융 실리카", "퓨즈드실리카", "이산화규소", "비정질실리카", "구상실리카"],
             "en": ["silica", "fused silica", "amorphous silica", "silicon dioxide", "silicon oxide"],
             "formula": ["SiO2"]},
    "quartz": {"ko": ["석영", "쿼츠", "결정성실리카", "결정질실리카", "결정실리카"], "en": ["quartz", "crystalline silica"],
               "formula": []},
    "sicoh": {"ko": ["시코", "저유전막"], "en": ["sicoh", "osg", "organosilicate glass"], "formula": ["SiCOH"]},
    "glass_bsg": {"ko": ["붕규산유리", "보로실리케이트", "보로실리케이트유리"], "en": ["borosilicate", "borosilicate glass"],
                  "formula": ["BSG"]},
    "eglass": {"ko": ["유리섬유", "이글라스", "글라스파이버", "유리 섬유"], "en": ["e-glass", "eglass", "glass fibre",
               "glass fiber"], "formula": ["GF"]},
    "al2o3": {"ko": ["알루미나", "산화알루미늄", "산화 알루미늄"], "en": ["alumina", "aluminium oxide", "aluminum oxide"],
              "formula": ["Al2O3"]},
    "aln": {"ko": ["질화알루미늄", "질화 알루미늄", "알루미늄나이트라이드"], "en": ["aluminium nitride", "aluminum nitride"],
            "formula": ["AlN"]},
    "hbn": {"ko": ["질화붕소", "질화 붕소", "보론나이트라이드", "육방정질화붕소", "비엔"], "en": ["boron nitride", "hexagonal boron nitride",
            "h-bn", "hbn"], "formula": ["BN", "h-BN", "hBN"]},
    "hbn_platelet": {"ko": ["이방성질화붕소", "이방성 질화붕소"], "en": ["anisotropic boron nitride", "anisotropic h-bn"],
                     "formula": []},
    "si3n4": {"ko": ["질화규소", "질화 규소", "실리콘나이트라이드"], "en": ["silicon nitride"], "formula": ["Si3N4"]},
    "mgo": {"ko": ["산화마그네슘", "산화 마그네슘", "마그네시아"], "en": ["magnesia", "magnesium oxide"], "formula": ["MgO"]},
    "zno": {"ko": ["산화아연", "산화 아연"], "en": ["zinc oxide"], "formula": ["ZnO"]},
    "beo": {"ko": ["산화베릴륨", "베릴리아"], "en": ["beryllia", "beryllium oxide"], "formula": ["BeO"]},
    "sic": {"ko": ["탄화규소", "탄화 규소", "실리콘카바이드"], "en": ["silicon carbide"], "formula": ["SiC"]},
    "diamond": {"ko": ["다이아몬드", "다이아"], "en": ["diamond"], "formula": []},
    "tio2": {"ko": ["이산화티타늄", "티타니아", "산화티타늄", "루틸"], "en": ["titania", "titanium dioxide", "rutile"],
             "formula": ["TiO2"]},
    "batio3": {"ko": ["티탄산바륨", "바륨티타네이트", "티탄산 바륨"], "en": ["barium titanate"], "formula": ["BaTiO3", "BTO"]},
    "zrw2o8": {"ko": ["텅스텐산지르코늄", "지르코늄텅스테이트", "음열팽창필러"], "en": ["zirconium tungstate"],
               "formula": ["ZrW2O8"]},
    "si": {"ko": ["규소", "실리콘입자", "실리콘분말", "실리콘웨이퍼", "다결정실리콘"], "en": ["silicon", "polysilicon",
           "polycrystalline silicon"], "formula": ["Si"]},
    "diamond_grit": {"ko": ["다이아몬드그릿", "다이아몬드 그릿", "합성다이아몬드"], "en": ["diamond grit", "synthetic diamond"],
                     "formula": ["MBD"]},
    "sic_grit": {"ko": ["탄화규소입자", "탄화규소그릿", "알파탄화규소"], "en": ["sic grit", "sic particles", "alpha sic"],
                 "formula": []},
    "gan": {"ko": ["질화갈륨", "질화 갈륨"], "en": ["gallium nitride"], "formula": ["GaN"]},
    "ga2o3": {"ko": ["산화갈륨", "산화 갈륨"], "en": ["gallium oxide"], "formula": ["Ga2O3"]},
    "glass_core": {"ko": ["글라스코어", "유리코어", "무알칼리유리"], "en": ["glass core", "alkali-free glass"], "formula": []},
    "ltcc": {"ko": ["엘티씨씨", "저온동시소성세라믹"], "en": ["ltcc", "low temperature co-fired ceramic"], "formula": ["LTCC"]},
    # ---- metals ----
    "cu": {"ko": ["구리", "동분말", "구리분말", "카파"], "en": ["copper"], "formula": ["Cu"]},
    "ag": {"ko": ["은분말", "은입자", "은플레이크", "은나노", "실버"], "en": ["silver"], "formula": ["Ag"]},
    "au": {"ko": ["금분말", "금입자", "골드"], "en": ["gold"], "formula": ["Au"]},
    "al": {"ko": ["알루미늄", "알미늄"], "en": ["aluminium", "aluminum"], "formula": ["Al"]},
    "w": {"ko": ["텅스텐"], "en": ["tungsten"], "formula": ["W"]},
    "ti": {"ko": ["티타늄", "티탄"], "en": ["titanium"], "formula": ["Ti"]},
    "sn": {"ko": ["주석"], "en": ["tin"], "formula": ["Sn"]},
    "in": {"ko": ["인듐"], "en": ["indium"], "formula": ["In"]},
    "sac305": {"ko": ["솔더", "땜납", "무연솔더", "삭305"], "en": ["solder", "sac305", "sac 305", "lead-free solder"],
               "formula": ["SAC305", "SAC"]},
    "invar": {"ko": ["인바", "인바합금"], "en": ["invar"], "formula": []},
    "sus316l": {"ko": ["스테인리스", "스테인레스", "서스", "스텐"], "en": ["stainless steel", "stainless", "316l"],
                "formula": ["SUS316L", "SUS", "316L"]},
    "al6061": {"ko": ["알루미늄합금", "알루미늄 합금", "알루미늄6061"], "en": ["aluminium alloy", "aluminum alloy", "al 6061",
               "6061"], "formula": ["Al6061"]},
    "a356": {"ko": ["알루미늄주조합금", "에이356"], "en": ["a356", "casting alloy"], "formula": ["A356"]},
    "mo": {"ko": ["몰리브덴", "몰리브데넘"], "en": ["molybdenum"], "formula": ["Mo"]},
    "kovar": {"ko": ["코바", "코바르"], "en": ["kovar", "sealing alloy"], "formula": []},
    "alloy42": {"ko": ["알로이42", "42합금", "리드프레임합금"], "en": ["alloy 42", "alloy42"], "formula": []},
    "egain": {"ko": ["액체금속", "갈륨인듐", "이가인"], "en": ["liquid metal", "egain", "gallium indium"], "formula": ["EGaIn"]},
    # ---- carbon ----
    "cnt": {"ko": ["탄소나노튜브", "씨엔티", "다중벽탄소나노튜브", "나노튜브"], "en": ["carbon nanotube", "carbon nanotubes",
            "mwcnt", "nanotube"], "formula": ["CNT", "MWCNT"]},
    "graphite": {"ko": ["흑연", "그라파이트", "그래핀", "그래핀나노플레이트렛", "지엔피"], "en": ["graphite", "graphene",
                 "graphene nanoplatelet", "gnp"], "formula": ["GNP"]},
    "carbon_fiber": {"ko": ["탄소섬유", "카본파이버", "탄소 섬유"], "en": ["carbon fibre", "carbon fiber"], "formula": ["CF"]},
    "carbon_black": {"ko": ["카본블랙", "카본 블랙", "흑연분"], "en": ["carbon black"], "formula": ["CB"]},
    # ---- magnetic ----
    "ni": {"ko": ["니켈"], "en": ["nickel"], "formula": ["Ni"]},
    "carbonyl_iron": {"ko": ["카보닐철", "카르보닐철", "카보닐아이언", "철분말", "철분"], "en": ["carbonyl iron", "iron powder",
                      "cip"], "formula": ["CIP"]},
    "sendust": {"ko": ["센더스트", "샌더스트"], "en": ["sendust", "fe-si-al"], "formula": []},
    "nizn_ferrite": {"ko": ["니켈아연페라이트", "니켈 아연 페라이트", "엔아이지엔페라이트"], "en": ["nizn ferrite", "ni-zn ferrite"],
                     "formula": ["NiZn"]},
    "mnzn_ferrite": {"ko": ["망간아연페라이트", "망간 아연 페라이트", "엠엔지엔페라이트"], "en": ["mnzn ferrite", "mn-zn ferrite"],
                     "formula": ["MnZn"]},
    # ---- pores ----
    "air": {"ko": ["기공", "공기", "보이드", "공극", "에어", "빈공간"], "en": ["air", "pore", "pores", "void", "voids", "porosity"],
            "formula": []},
    "vacuum": {"ko": ["진공"], "en": ["vacuum", "evacuated pore"], "formula": []},
}

# the shape a material's name already says (glass fibre, carbon fibre, nanotubes)
MATERIAL_SHAPE = {"eglass": "fiber", "carbon_fiber": "fiber", "cnt": "fiber"}

# words that name a material ambiguously: the context decides, else the user
AMBIGUOUS = {
    # 실리콘: the polymer (silicone) as a matrix, the element (Si) as a filler
    "실리콘": ["silicone", "si"], "silicon": ["si", "silicone"],
    "페라이트": ["nizn_ferrite", "mnzn_ferrite"], "ferrite": ["nizn_ferrite", "mnzn_ferrite"],
    "유리": ["glass_bsg", "eglass", "glass_core"], "glass": ["glass_bsg", "eglass", "glass_core"],
    "은": ["ag"], "금": ["au"], "철": ["carbonyl_iron"], "동": ["cu"],
}
# one-syllable Korean material names that are also particles or common words:
# a material only when a filler word, a number or "(Ag)" stands next to them
SHORT_KO = {"은": "ag", "금": "au", "철": "carbonyl_iron", "동": "cu"}

ANALYSES = {
    "thermal": {"ko": ["열전도도", "열전도율", "열전도", "열 전도도", "열 전도율", "열전달계수", "방열", "방열특성", "열저항",
                       "열전도성", "열특성", "k값", "케이값"],
                "en": ["thermal conductivity", "heat conduction", "thermal resistance", "tc", "k value", "k-value",
                       "heat dissipation", "thermal", "heat conductivity", "heat transport", "heat transfer",
                       "conducts heat", "carry heat"]},
    "electrical": {"ko": ["전기전도도", "전기 전도도", "전기전도율", "전기전도", "전기저항", "비저항", "저항률", "면저항", "도전성",
                          "통전성", "전기특성"],
                   "en": ["electrical conductivity", "electric conductivity", "resistivity", "sheet resistance",
                          "electrical resistance", "electrical"]},
    "dielectric": {"ko": ["유전율", "유전상수", "비유전율", "유전손실", "유전정접", "유전특성", "유전 특성", "디케이", "디에프"],
                   "en": ["permittivity", "dielectric constant", "dielectric loss", "dielectric", "loss tangent",
                          "dk", "df", "tan delta"]},
    "magnetic": {"ko": ["투자율", "자기투자율", "비투자율", "자성특성"], "en": ["magnetic permeability", "relative permeability",
                                                                  "magnetic", "mu r"]},
    "emi": {"ko": ["전자파차폐", "전자파 차폐", "차폐효율", "차폐 효율", "이엠아이", "차폐"], "en": ["emi", "emi shielding",
            "shielding effectiveness", "shielding"]},
    "cte": {"ko": ["열팽창", "열팽창계수", "열팽창률", "탄성", "탄성계수", "탄성률", "영률", "모듈러스", "강성", "푸아송비",
                   "포아송비", "기계적물성", "기계적 물성", "씨티이"],
            "en": ["cte", "thermal expansion", "coefficient of thermal expansion", "elastic", "elasticity",
                   "young's modulus", "youngs modulus", "modulus", "stiffness", "poisson's ratio", "elastic modulus"]},
    "mechtest": {"ko": ["기계시험", "인장시험", "압축시험", "만능시험", "하중변위", "유티엠"],
                 "en": ["mechanical test", "tensile test", "compression test", "utm", "load displacement"]},
    "thermomech": {"ko": ["휨", "워피지", "와피지", "열응력", "휘어짐", "변형량"], "en": ["warpage", "thermal stress", "bow",
                   "curvature"]},
    "joule": {"ko": ["줄발열", "줄 발열", "주울발열", "전류발열", "열폭주"], "en": ["joule heating", "joule", "thermal runaway"]},
    "viscosity": {"ko": ["점도", "점성", "유동성", "흐름성", "상대점도", "유변"], "en": ["viscosity", "flowability", "rheology",
                  "relative viscosity"]},
    "moisture": {"ko": ["흡습", "흡습률", "수분흡수", "수분 흡수", "흡수율", "팽윤", "습윤팽창"], "en": ["moisture", "water uptake",
                 "moisture uptake", "swelling", "cme", "hygroscopic"]},
    "permeability": {"ko": ["투과도", "투과율", "기체투과", "통기도", "다르시"], "en": ["gas permeability", "darcy permeability",
                     "flow permeability", "darcy"]},
    "filtration": {"ko": ["여과", "여과효율", "필터효율", "포집효율"], "en": ["filtration", "filtration efficiency",
                   "filter efficiency"]},
    "tortuosity": {"ko": ["확산", "확산계수", "굴곡도", "비틀림"], "en": ["tortuosity", "diffusion", "diffusivity"]},
    "acoustics": {"ko": ["흡음", "흡음률", "흡음계수", "음향"], "en": ["acoustic", "acoustics", "sound absorption", "nrc"]},
    "radiation": {"ko": ["복사", "복사열", "복사열전달"], "en": ["radiation", "radiative"]},
    "morphology": {"ko": ["기공크기", "기공 크기", "기공률", "비표면적", "형상분석"], "en": ["pore size", "specific surface",
                   "morphology"]},
    "percolation": {"ko": ["퍼콜레이션", "연결성", "침투경로"], "en": ["percolation", "connectivity"]},
    "porosimetry": {"ko": ["포로시메트리", "수은압입", "기공분포"], "en": ["porosimetry", "mercury intrusion"]},
    "pore_network": {"ko": ["기공네트워크", "기공 네트워크"], "en": ["pore network"]},
    "grains": {"ko": ["입자분석", "입자 분석", "구형도"], "en": ["grain analysis", "sphericity", "particle analysis"]},
}
# a word that names analyses only together with its context
AMBIGUOUS_ANALYSES = {
    "전도도": ["thermal", "electrical"], "전도율": ["thermal", "electrical"], "conductivity": ["thermal", "electrical"],
    "permeability": ["magnetic", "permeability"], "투과": ["permeability", "magnetic"],
}
# broad requests: a group of analyses the user is asked to narrow down
ANALYSIS_GROUPS = {
    "열적물성": ["thermal", "cte"], "열적 물성": ["thermal", "cte"], "thermal properties": ["thermal", "cte"],
    "전기적물성": ["electrical", "dielectric"], "전기적 물성": ["electrical", "dielectric"],
    "electrical properties": ["electrical", "dielectric"],
}
ALL_PROPS = ["모든물성", "모든 물성", "전체물성", "전부", "물성 전부", "all properties", "everything"]

# shape words -> (MPSim shape, size extras)
SHAPES = {
    "sphere": {"ko": ["구형", "구상", "구", "볼", "비드", "구슬"], "en": ["sphere", "spheres", "spherical", "ball", "beads"]},
    "platelet": {"ko": ["판상", "플레이크", "플레이크상", "판형", "박편", "판상형", "플레이트렛", "플레이크형"],
                 "en": ["platelet", "platelets", "flake", "flakes", "plate", "plates", "sheet", "sheets", "flaky"]},
    "fiber": {"ko": ["섬유", "섬유상", "파이버", "로드", "막대", "봉상", "침상", "위스커", "와이어", "나노와이어", "단섬유"],
              "en": ["fiber", "fibre", "fibers", "fibres", "rod", "rods", "whisker", "whiskers", "wire", "wires",
                     "nanowire", "needle"]},
    "cube": {"ko": ["큐브", "정육면체", "입방체"], "en": ["cube", "cubes", "cubic"]},
    "irregular": {"ko": ["불규칙", "불규칙형", "각형", "파쇄", "파쇄형", "부정형", "모난"], "en": ["irregular", "angular",
                  "crushed", "jagged"]},
    "spheroid": {"ko": ["타원체", "회전타원체", "타원형"], "en": ["spheroid", "ellipsoid", "ellipsoidal"]},
    "network": {"ko": ["다공성", "다공질", "스펀지", "폼", "연속기공", "망상"], "en": ["porous", "foam", "sponge", "open pores",
                "network"]},
}
# a filler or a matrix
ROLE_FILLER = {"ko": ["필러", "충전재", "충진재", "입자", "분말", "파우더", "분체", "필러로", "첨가제", "강화재"],
               "en": ["filler", "fillers", "particle", "particles", "powder", "powders", "additive", "inclusion",
                      "inclusions", "reinforcement"]}
ROLE_MATRIX = {"ko": ["레진", "수지", "매트릭스", "기지", "바인더", "고분자", "베이스", "모재"],
               "en": ["resin", "matrix", "binder", "polymer", "base", "host"]}

TASKS = {
    "doe": {"ko": ["doe", "실험계획", "실험 계획", "바꿔가며", "바꿔가면서", "변화시키며", "변화시키면서", "변화에따른", "에따른",
                   "에 따른", "범위", "스윕", "별로", "수준별", "단계별", "케이스별", "파라미터스터디", "민감도"],
            "en": ["doe", "design of experiments", "sweep", "vary", "varying", "range", "parameter study", "sensitivity",
                   "as a function of", "versus", "vs"]},
    "calibration": {"ko": ["보정", "캘리브레이션", "캘리브", "맞춰", "맞추", "역산", "피팅", "측정값", "측정치", "실측"],
                    "en": ["calibrate", "calibration", "fit", "fitting", "match the measurement", "measured", "back-calculate"]},
    "optimization": {"ko": ["최적화", "최적", "최대화", "최소화", "최대가되는", "최소가되는", "목표", "가장높은", "가장낮은"],
                     "en": ["optimize", "optimise", "optimization", "optimisation", "maximize", "maximise", "minimize",
                            "minimise", "optimum", "best", "target"]},
    "structure": {"ko": ["구조만", "구조생성", "구조 생성", "구조만생성", "형상만"], "en": ["structure only", "generate structure",
                  "just the structure"]},
}

QUALITY = {
    "fast": {"ko": ["빠르게", "빨리", "간단히", "대략", "대충", "러프", "스크리닝", "빠른", "간단하게", "급하게"],
             "en": ["fast", "quick", "quickly", "rough", "roughly", "screening", "draft"]},
    "standard": {"ko": ["표준", "보통", "일반", "스탠다드", "기본정확도"], "en": ["standard", "normal", "regular"]},
    "accurate": {"ko": ["정확하게", "정확히", "정밀", "정밀하게", "정확도높게", "상세히", "논문용", "보고용", "정확한", "고정밀"],
                 "en": ["accurate", "accurately", "precise", "precisely", "high accuracy", "publication", "report"]},
}
# "decide it yourself"
AUTO = {"ko": ["알아서", "자동으로", "자동", "적당히", "적절히", "기본값", "기본값으로", "맡길게", "맡겨", "추천대로", "추천값",
               "아무거나", "상관없어", "상관없음", "디폴트"],
        "en": ["auto", "automatic", "automatically", "you decide", "your choice", "default", "defaults", "whatever",
               "as recommended", "recommended"]}
DIRECTIONS = {
    "z": {"ko": ["두께방향", "z방향", "수직방향", "면수직"], "en": ["through-plane", "through plane", "out-of-plane", "z direction",
          "z-direction", "thickness direction"]},
    "x": {"ko": ["면내", "면내방향", "수평방향", "x방향"], "en": ["in-plane", "in plane", "x direction", "x-direction"]},
    "xyz": {"ko": ["3방향", "3 방향", "세방향", "세 방향", "모든방향", "전방향", "xyz", "삼방향", "이방성"], "en": ["all directions",
            "three directions", "3 directions", "xyz", "every direction", "anisotropy", "tensor"]},
}
ORIENTATION = {
    "z": {"ko": ["수직배향", "두께방향배향", "z배향", "세워진"], "en": ["aligned along z", "vertically aligned", "z-aligned"]},
    "xy": {"ko": ["수평배향", "면내배향", "누운", "평행배향", "적층배향"], "en": ["in-plane aligned", "lying flat", "horizontally aligned"]},
    "iso": {"ko": ["랜덤", "무작위", "등방", "무작위배향", "랜덤배향"], "en": ["random", "randomly oriented", "isotropic"]},
}
DISTRIBUTION = {"lognormal": {"ko": ["로그정규", "로그 정규", "로그노말", "입도분포"], "en": ["lognormal", "log-normal",
                              "size distribution", "psd"]},
                "normal": {"ko": ["정규분포"], "en": ["normal distribution", "gaussian"]},
                "mono": {"ko": ["단분산", "균일크기", "단일입경"], "en": ["monodisperse", "uniform size", "single size"]}}
# Korean particles and fillers of speech stripped off a word before matching
PARTICLES = ["에다가", "으로써", "에서는", "으로는", "이라는", "이라고", "만큼의", "정도의", "만큼", "정도", "쯤", "에다", "으로", "에서", "부터",
             "까지", "에는", "에게", "이고", "이며", "이랑", "하고", "와의", "과의", "로서", "로써", "이나", "이다",
             "은", "는", "이", "가", "을", "를", "에", "의", "와", "과", "로", "도", "만", "랑", "씩", "고", "나"]
# words that never name a material (kept out of fuzzy matching)
STOP = {"ko": ["해줘", "구해줘", "계산", "계산해줘", "해석", "해석해줘", "시뮬레이션", "물성", "복합재", "복합제", "복합체",
               "컴파운드", "섞인", "섞여있는", "섞은", "혼합", "넣은", "넣고", "넣어서", "포함", "포함된", "사용", "조건",
               "경우", "그리고", "및", "약", "대략", "있는", "있다", "있을때", "되는", "값", "구하고", "싶어", "알려줘", "봐줘",
               "돌려줘", "진행", "진행해줘", "하나", "단계", "수준", "범위", "까지", "부터", "에서", "만큼", "정도", "이상",
               "이하", "사이", "기준", "방향", "크기", "입경", "지름", "직경", "평균", "함량", "비율", "분율", "부피", "중량",
               "무게", "질량", "퍼센트", "프로", "마이크로", "미크론", "마이크론", "나노", "코어", "병렬", "동시에", "반복",
               "정확도", "도메인", "해줄래", "해주세요", "주세요", "부탁해", "원해", "보고", "싶다", "보자", "할때", "일때"],
        "en": ["the", "a", "an", "of", "with", "and", "in", "for", "to", "please", "compute", "calculate", "simulate",
               "find", "get", "what", "is", "are", "composite", "compound", "mixed", "filled", "containing", "content",
               "loading", "fraction", "size", "diameter", "average", "mean", "run", "analysis", "analyse", "analyze",
               "properties", "property", "percent", "vol", "wt", "volume", "weight", "mass", "from", "between",
               "at", "by", "on", "into", "using", "use", "do", "me", "it", "its", "this", "that", "level", "levels",
               "step", "steps", "cores", "core", "parallel", "times", "repeat", "accuracy", "domain", "want", "would",
               "like", "show", "tell", "about", "around", "approximately", "approx", "roughly",
               # frequent words, never a material however they are spelled
               "again", "same", "settings", "setting", "hello", "how", "you", "your", "they", "them", "there",
               "here", "where", "when", "which", "who", "why", "then", "than", "also", "only", "just", "more",
               "most", "less", "much", "many", "some", "any", "all", "each", "other", "another", "same", "such",
               "make", "made", "need", "needs", "give", "take", "keep", "start", "stop", "again", "last", "next",
               "first", "second", "time", "times", "case", "cases", "result", "results", "value", "values",
               "good", "better", "best", "high", "higher", "low", "lower", "small", "large", "big", "long", "short",
               "new", "old", "same", "thing", "things", "something", "anything", "everything", "please", "thanks",
               "thank", "okay", "yes", "no", "not", "very", "really", "maybe", "about", "after", "before",
               "should", "could", "can", "will", "shall", "may", "might", "must", "have", "has", "had", "been",
               "being", "was", "were", "does", "did", "done", "going", "want", "wants", "know", "think", "check",
               "again", "said", "say", "tell", "today", "now", "later", "slow", "slowly", "faster", "wait",
               # units: a word after a number is its unit, not a material ("6 GPa", "2 S/m")
               "gpa", "mpa", "kpa", "pa", "ppm", "s", "m", "k", "w", "um", "nm", "mm", "cm", "vol", "wt", "phr", "cp",
               "cps", "ohm", "mk", "hz", "ghz", "mhz", "khz", "db", "kelvin", "celsius", "sec", "min", "hr"]}
# frequent Korean words and endings (left out of fuzzy matching)
STOP_KO_EXTRA = ["안녕하세요", "안녕", "오늘", "날씨", "좋네요", "결과", "결과를", "빨리", "보고", "싶어요", "지난번", "이전",
                 "같은", "다시", "이거", "이것", "그거", "저거", "왜", "이렇게", "그렇게", "오래", "걸려", "걸려요", "걸리네",
                 "감사", "감사합니다", "고마워", "네", "아니", "아니요", "좋아", "좋아요", "그래", "그럼", "근데", "그런데",
                 "혹시", "한번", "다음", "이번", "저번", "방금", "아까", "지금", "나중", "먼저", "확인", "확인해줘",
                 "알려줘", "부탁", "부탁해요", "해주세요", "주세요", "되나요", "될까요", "할까요", "있나요", "없나요",
                 "멈춰", "중지", "취소", "그만", "계속", "시작", "실행", "실행해줘", "해봐", "해볼래", "해보자"]

# what a calibration may find (the material values themselves are named by
# the analysis words): interface resistances
CAL_UNKNOWNS = {
    "r_int": ["계면저항", "계면 저항", "계면열저항", "계면 열저항", "카피차저항", "kapitza", "interface resistance",
              "interfacial resistance", "interfacial thermal resistance", "r_int", "rint"],
    "r_contact": ["접촉저항", "접촉 저항", "접촉열저항", "contact resistance", "r_c"],
}
