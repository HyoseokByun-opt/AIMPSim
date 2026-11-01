"""Words of the replies, in the language of the request (Korean when the
request has Hangul, English otherwise)."""
from __future__ import annotations

AN_NAME = {
    "thermal": ("열전도도", "Thermal conductivity"), "electrical": ("전기전도도", "Electrical conductivity"),
    "dielectric": ("유전율과 손실", "Permittivity and loss"), "magnetic": ("투자율", "Magnetic permeability"),
    "emi": ("EMI 차폐", "EMI shielding"), "cte": ("탄성과 열팽창(CTE)", "Elasticity and CTE"),
    "mechtest": ("기계 시험", "Mechanical test"), "thermomech": ("열응력과 휨", "Thermal stress and warpage"),
    "joule": ("줄 발열", "Joule heating"), "viscosity": ("점도와 유동성", "Viscosity and flowability"),
    "moisture": ("흡습과 팽윤", "Moisture uptake and swelling"), "permeability": ("투과도", "Permeability"),
    "filtration": ("여과 효율", "Filtration efficiency"), "tortuosity": ("확산", "Diffusion"),
    "acoustics": ("흡음", "Acoustic absorption"), "radiation": ("복사", "Radiation"),
    "morphology": ("기공률과 크기", "Porosity and sizes"), "percolation": ("퍼콜레이션", "Percolation path"),
    "porosimetry": ("포로시메트리", "Porosimetry"), "pore_network": ("기공 네트워크", "Pore network"),
    "grains": ("입자 분석", "Grain analysis"),
}
SHAPE_NAME = {"sphere": ("구형", "sphere"), "platelet": ("판상", "platelet"), "fiber": ("섬유(원기둥)", "fibre (cylinder)"),
              "cube": ("정육면체", "cube"), "irregular": ("불규칙 다면체", "irregular polyhedron"),
              "spheroid": ("회전타원체", "spheroid"), "network": ("연속 기공(다공체)", "open pore network")}
QUALITY_NAME = {"fast": ("Fast(빠름)", "Fast"), "standard": ("Standard(표준)", "Standard"),
                "accurate": ("Accurate(정밀)", "Accurate")}
TASK_NAME = {"run": ("해석 1건", "One run"), "doe": ("DOE 스터디", "DOE study"), "calibration": ("보정(Calibration)", "Calibration"),
             "optimization": ("최적화 (DOE 후 최적점 탐색)", "Optimization (a DOE, then its optimum)"),
             "structure": ("구조만 생성", "Structure only"),
             "design": ("설계 탐색 (DOE → 대리모델 → 추천 조합 → 확인 해석)",
                        "Design search (a DOE, a surrogate, the recommended recipe, a check run)")}
SRC = {"text": ("입력", "said"), "fuzzy": ("오타·발음 보정", "spelling matched"), "rule": ("단위 규칙", "unit rule"),
       "auto": ("자동", "automatic"), "default": ("기본값", "default"), "answer": ("답변", "answered"),
       "llm": ("AI 추정 - 확인 필요", "AI guess - check it"), "derived": ("계산", "derived")}

M = {
    "q_matrix": ("매트릭스(수지) 재료가 무엇인가요?", "Which matrix (resin) material?"),
    "q_compare": ("{names}을(를) 비교하는 요청으로 읽었습니다. 섞지 않고 각각 따로 해석할까요?",
                  "This reads as a comparison of {names}. Run each on its own (they are not mixed)?"),
    "q_filler": ("어떤 필러를 넣나요?", "Which filler?"),
    "q_content": ("{name}의 함량은 얼마인가요? (예: 55%, 0.55, 30 wt%)", "How much {name}? (e.g. 55%, 0.55, 30 wt%)"),
    "q_basis": ("함량은 부피% 인가요, 중량% 인가요?", "Is the content by volume or by weight?"),
    "q_shape": ("{name} 입자의 형상은?", "Shape of the {name} particles?"),
    "q_size": ("{name} 입자의 크기(지름)는? (예: 5 µm)", "Size (diameter) of the {name} particles? (e.g. 5 µm)"),
    "q_analysis": ("어떤 물성을 계산할까요?", "Which property should be computed?"),
    "q_which_cond": ("'{text}'은(는) 열전도도인가요, 전기전도도인가요?", "Does '{text}' mean thermal or electrical conductivity?"),
    "q_quality": ("도메인 정확도 수준을 정해 주세요.", "Choose the accuracy level of the domain."),
    "q_parallel": ("병렬 실행은 어떻게 할까요?", "How should the runs use the machine?"),
    "q_unknown": ("'{text}'은(는) 라이브러리에 없는 재료입니다. 어떤 재료를 쓸까요? (없으면 Material 탭에서 새 재료를 추가)",
                  "'{text}' is not in the material library. Which material is it? (or add it in the Material tab)"),
    "q_ambiguous": ("'{text}'은(는) 어느 재료인가요?", "Which material is '{text}'?"),
    "q_doe_range": ("DOE로 바꿀 변수와 범위를 알려 주세요. (예: 알루미나 40~60%)", "Which variable and range should the DOE vary? (e.g. alumina 40-60%)"),
    "q_doe_steps": ("몇 단계(수준)로 나눌까요?", "How many levels?"),
    "q_cal_meas": ("보정에 쓸 측정값을 알려 주세요. (예: 20%일 때 0.45 W/mK)", "Which measurements? (e.g. 0.45 W/mK at 20%)"),
    "q_cal_unknowns": ("무엇을 보정할까요?", "What should be calibrated?"),
    "q_opt_goal": ("{prop}을(를) 최대로 할까요, 최소로 할까요?", "Maximise or minimise the {prop}?"),
    "q_film": ("필름 두께는? (예: 50 µm)", "Film thickness? (e.g. 50 µm)"),
    "q_pores": ("이 해석에는 기공이 필요합니다. 기공 함량은? (예: 30%)", "This analysis needs pores. How much porosity? (e.g. 30%)"),
    "opt_auto": ("알아서 (추천값)", "Decide for me (recommended)"),
    "opt_vol": ("부피% (vol%)", "by volume (vol%)"), "opt_wt": ("중량% (wt%)", "by weight (wt%)"),
    "par_auto": ("자동: {txt}", "Automatic: {txt}"),
    "par_one": ("한 번에 1개, 모든 코어", "One at a time on every core"),
    "par_n": ("동시에 {n}개, 각 {c}코어", "{n} at a time, {c} cores each"),
    "ready": ("아래 조건으로 진행할까요?", "Run with these conditions?"),
    "need": ("진행하려면 몇 가지를 정해야 합니다.", "A few things are needed before running."),
    "assume": ("가정", "assumed"),
    "q_reason_auto": ("자동", "auto"),
}


def t(key, lang, **kw):
    ko, en = M[key]
    return (ko if lang == "ko" else en).format(**kw)


def name(table, key, lang):
    v = table.get(key)
    if not v:
        return key
    return v[0] if lang == "ko" else v[1]
