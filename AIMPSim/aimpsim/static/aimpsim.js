/* AIMPSim - the AI tab of MPSim.
   A request in words is sent to /api/ai/interpret; the reply holds a summary
   of what would run, the questions still open and, when nothing essential is
   missing, the MPSim inputs. Nothing runs before the user presses Run: the
   inputs are then put into the case (the other tabs show them) and started
   through MPSim's own functions (window.MPSimHost) - a run, a DOE study, a
   calibration, or a DOE followed by its optimum. */
(function () {
  "use strict";
  const H = () => window.MPSimHost;
  const KEY = "aimpsim.chat";
  const S = { sid: null, msgs: [], busy: false, lang: "en", status: null, loops: [] };
  try { const s = JSON.parse(localStorage.getItem(KEY) || "null"); if (s) Object.assign(S, s, { busy: false }); } catch (e) { }
  if (!Array.isArray(S.loops)) S.loops = S.loop ? [S.loop] : [];
  delete S.loop;
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify({ sid: S.sid, msgs: S.msgs.slice(-60), lang: S.lang, loops: S.loops })); } catch (e) { } };
  const L = (ko, en) => (S.lang === "ko" ? ko : en);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (n) => (H() ? H().I(n) : "");

  const EXAMPLES = [
    "에폭시 수지 45%와 구형 알루미나 필러 55 vol%가 섞인 복합재의 열전도도 구해줘",
    "애폭시에 실리카 0.55만큼, 입경 5마이크로, 열전도율이랑 CTE 알아서 해줘",
    "실리콘에 판상 질화붕소 30wt% 종횡비 10, 열전도도 3방향",
    "에폭시에 알루미나 10마이크로 구형 40~60% 범위로 5단계 DOE, 열전도도",
    "에폭시에 실리카 20%일 때 0.45 W/mK, 40%일 때 0.8 W/mK 측정됐어. 계면저항 보정해줘",
    "에폭시에 알루미나 함량을 40~60%로 바꿔가며 열전도도가 최대가 되는 조건 찾아줘",
    "10um 에폭시 필름에서 알루미나를 가장 적게 넣고 z방향 열전도도 3 W/mK가 되는 크기와 배합비율 알려줘. topcut 3um, 가장 작은 입자 200nm, 최대 62vol%, 분포는 고려하지 않음, 필러-레진·필러-필러 열저항 1E-8, 비슷하면 점도 낮고 패킹 잘되는 조합",
    "에폭시에 구형 알루미나 10um 50vol%, 알루미나 열전도도는 라이브러리보다 10 낮게 해서 열전도도",
    "epoxy with 60 vol% spherical silica 4 um, thermal conductivity and CTE, accurate",
    "silicone with 50 vol% alumina 10 um, permittivity, quick, 2 runs at a time",
  ];

  async function post(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({ ok: false, error: r.statusText }));
    if (!r.ok || j.ok === false) throw new Error(j.error || r.statusText);
    return j;
  }

  // ------------------------------------------------------------ left panel
  function llmLabel(st) {
    const ms = st && st.llm && st.llm.state;
    return (!st ? "" : st.llm && st.llm.enabled
      ? `${L("로컬 모델", "Local model")}${st.llm.model ? ` (${st.llm.model.replace(/\.gguf$/, "")})` : ""}: ${
        ms === "ready" ? L("준비됨", "ready") : ms === "starting" ? L("준비 중… (처음 한 번 1분 이내)", "getting ready… (under a minute, once)")
          : ms === "failed" ? L("시작하지 못함 - 규칙으로 읽습니다", "did not start - the rules read requests")
            : L("필요할 때 시작", "starts when needed")}`
      : L("로컬 모델 없음 - 규칙으로 읽습니다", "No local model - requests are read by rules"))
      + (st ? ` · v${st.version}` : "");
  }
  function left() {
    const st = S.status;
    return `<div class="sec"><div class="sh">${icon("ai")}${L("요청", "Request")}</div><div class="sb">
        <textarea id="aiText" class="ai-text" rows="6" placeholder="${esc(L("예: 에폭시에 구형 알루미나 55 vol%, 열전도도 구해줘", "e.g. epoxy with 55 vol% spherical alumina, thermal conductivity"))}"></textarea>
        <div class="row gap" style="margin-top:6px"><button class="btn primary" id="aiSend">${icon("play")}${L("보내기", "Send")}</button>
          <button class="btn" id="aiNew">${icon("new")}${L("새 요청", "New request")}</button></div>
        <div class="hint" style="margin-top:6px">${L("Enter로 보내기, Shift+Enter로 줄바꿈. 이어서 쓰면 앞의 요청에 더해집니다.", "Enter sends, Shift+Enter starts a new line. A further message adds to the request before it.")}</div>
      </div></div>
      <div class="sec"><div class="sh">${icon("checks")}${L("읽는 규칙", "How requests are read")}</div><div class="sb ai-rules">
        <div>${L("<b>함량</b>: 55%, 55 vol%, 30 wt%, 30 phr, 0.55(=55%), 1/3, 절반. 단위 없는 1 이하의 수는 분율, 1~100은 %로 읽고 요약에 표시합니다.", "<b>Content</b>: 55%, 55 vol%, 30 wt%, 30 phr, 0.55 (= 55 %), 1/3, half. A bare number up to 1 is a fraction, up to 100 a percent - the summary says which.")}</div>
        <div>${L("<b>범위</b>: 40~60%, 40-60%, 40에서 60%까지, 40, 50, 60% → DOE. 5단계, 10%씩.", "<b>Ranges</b>: 40-60%, from 40 to 60%, 40, 50, 60% → a DOE; 5 levels, in steps of 10%.")}</div>
        <div>${L("<b>오타</b>: 철자와 발음이 가까운 재료로 찾고(애폭시→에폭시), 요약에 보정 내용을 보여 줍니다. 애매하면 묻습니다.", "<b>Typos</b>: the closest material by spelling and sound (alumna → alumina), shown in the summary; when unsure, a question.")}</div>
        <div>${L("<b>자유롭게</b> 쓰세요: 돌려 말하기, 정정(\"55%, 아니 60%\"), 빼기(\"알루미나 말고\"), 띄어쓰기·오타, 한영 혼용을 로컬 모델이 읽고, 규칙이 재료와 숫자가 문장에 있는지 검산합니다.", "<b>Write freely</b>: roundabout wording, corrections (\"55%, no, 60%\"), \"not alumina\", spacing and typing errors, Korean and English mixed are read by the local model; the rules check that every material and number is in the sentence.")}</div>
        <div>${L("<b>물성값</b>은 MPSim 라이브러리 값이나, 문장에서 직접 준 값(\"k가 200인 알루미나\", \"알루미나 열전도도 라이브러리보다 10 낮게\", \"20% 높게\", \"절반으로\")만 씁니다. 준 값은 이번 요청의 해석에만 쓰고 라이브러리는 바꾸지 않습니다. 지어내지 않고, 라이브러리에 없는 재료는 묻습니다.", "<b>Material values</b> are the MPSim library's, or a value given in the request (\"alumina with k = 200\", \"alumina k 10 below the library\", \"20% higher\", \"halved\"); a value given is used for this request only and the library is not changed. Never made up - a material the library does not hold is asked about.")}</div>
        <div>${L("<b>설계</b>: \"열전도도 3 W/mK가 되는 최소 함량과 크기·배합비율\"처럼 목표를 주면, 함량·크기·비율을 바꾸는 DOE를 돌린 뒤 대리모델로 목표를 만족하는 최저 함량 조합을 고릅니다(비슷하면 점도 낮고 패킹 좋은 쪽). 대리모델이 그 함량을 허용 오차 안으로 정하지 못하면 점을 더 해석하고, 정해지면 확인 해석해 목표를 만족할 때까지 계속합니다.", "<b>Design</b>: a target (\"the least filler for k = 3 W/mK, which sizes and blend\") runs a DOE over content, sizes and blend; a surrogate then picks the lowest content that meets the target (at a similar content, the lower viscosity and better packing). While it cannot fix that content within the tolerance, more points are run; then the recipe is checked, until a check meets the target.")}</div>
        <div>${L("<b>최적화</b>: \"함량 30~55%, 크기 5~30um로 바꿔가며 열전도도 최대\"처럼 범위와 목표를 주면, DOE 뒤 대리모델 정확도(R²)를 보고 모자라면 점을 더하고, 개선이 기대되는 점을 해석해 가다가 예측 최적점을 실제로 해석해 예측과 맞으면 확정합니다.", "<b>Optimisation</b>: ranges and a goal (\"vary 30-55 % and 5-30 um, highest k\") run a DOE; while the surrogate's R² is low, points are added where it is least sure, then the points of highest expected improvement, and the predicted optimum is run: it stands when the run agrees.")}</div>
        <div>${L("<b>보정</b>: 실행 전에 측정값을 이론 한계와 유효매질 모델로 점검해, 요청한 대상(예: 계면저항)으로 닿을 수 없으면 닿는 대상을 추천합니다. 결과가 측정에 닿지 않으면 범위나 대상을 바꿔 닿을 때까지 다시 보정하고, 더 바꿀 것이 없으면 재료 등급·함량 기준을 묻습니다.", "<b>Calibration</b>: before the run the data are checked against the bounds and the effective-medium model; when what was asked (R_int, say) cannot reach them, the unknowns that can are recommended. A result that does not reach the data is run again with another range or other unknowns until it does; when nothing is left, the material grade or the content basis is asked.")}</div>
        <div>${L("말하지 않은 정확도·병렬·형상·크기는 추천값과 함께 묻고, '알아서'라고 하면 문제에 맞게 정합니다.", "Accuracy, parallel runs, shape and size not given are asked with a recommendation; \"decide for me\" sets them for the problem.")}</div>
      </div></div>
      <div class="sec"><div class="sh">${icon("solver")}AIMPSim</div><div class="sb"><div class="hint" id="aiLlm">${esc(llmLabel(st))}</div></div></div>`;
  }
  function mountLeft(body) {
    const ta = body.querySelector("#aiText");
    if (!ta) return;
    body.querySelector("#aiSend").onclick = () => send(ta.value);
    body.querySelector("#aiNew").onclick = () => action("new");
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(ta.value); } });
    if (!S.status || (S.status.llm && S.status.llm.enabled && S.status.llm.state !== "ready")) warmUp();
    setTimeout(() => ta.focus(), 0);
  }

  // the local model is started and has read its instructions before the first request
  let warming = false;
  async function warmUp() {
    if (warming) return;
    warming = true;
    try {
      let st = await (await fetch("/api/ai/status")).json();
      S.status = st;
      if (st.llm && st.llm.enabled && st.llm.state !== "ready") {
        await fetch("/api/ai/warm", { method: "POST" });
        for (let i = 0; i < 120; i++) {
          st = await (await fetch("/api/ai/status")).json();
          S.status = st;
          showLlm();                     // only the label: the request being typed stays
          if (!st.llm || ["ready", "failed"].includes(st.llm.state)) break;
          await new Promise((r) => setTimeout(r, 2500));
        }
      }
      showLlm();
    } catch (e) { } finally { warming = false; }
  }
  function showLlm() {
    const el = document.getElementById("aiLlm");
    if (el) el.textContent = llmLabel(S.status);
  }

  // ------------------------------------------------------------ conversation
  // the conversation is on the centre page: it is shown whenever a request goes out or a reply comes back
  // (opening a case may have put the 3D view there in the meantime)
  function showConversation() {
    const h = H();
    if (h.state.tab === "ai" && h.state.center !== "ai") h.setCenter("ai");
  }
  // the left panel drawn again (its words follow the request's language), keeping what is being typed
  function redrawLeft() {
    const ta = document.getElementById("aiText"), typed = ta ? ta.value : "";
    H().renderLeft();
    const nt = document.getElementById("aiText");
    if (nt && typed) nt.value = typed;
  }
  async function send(text) {
    text = String(text || "").trim();
    if (!text || S.busy) return;
    if (/[가-힣]/.test(text)) S.lang = "ko"; else if (!S.msgs.length) S.lang = "en";
    if (S.loops.length) {
      let c = null;
      const kinds = [...new Set(S.loops.map((x) => x.kind))];
      const waiting = S.loops.some((x) => x.kind === "cal" && x.wait === "answer");
      try { c = await post("/api/ai/loop/command", { text, kinds, waiting, lang: S.lang }); } catch (e) { }
      const ta0 = document.getElementById("aiText");
      if (c && c.command === "stop") { if (ta0) ta0.value = ""; S.msgs.push({ role: "user", text }); await loopStop(); return; }
      if (c && c.command === "answer") { if (ta0) ta0.value = ""; await loopAnswer(c.answer, text); return; }
      const dl = S.loops.filter((x) => x.kind === "design").pop();
      if (c && c.command === "condition" && dl) {
        if (ta0) ta0.value = "";
        dl.design = Object.assign({}, dl.design, c.condition);
        S.msgs.push({ role: "user", text });
        const cs = c.condition;
        S.msgs.push({ role: "ai", note: esc(L("다음 라운드부터 반영합니다: ", "From the next round: ") + [cs.content_cap != null ? L(`최대 함량 ${cs.content_cap} vol%`, `content at most ${cs.content_cap} vol%`) : "",
          cs.tol != null ? L(`같은 함량으로 볼 차이 ${cs.tol} vol%`, `contents within ${cs.tol} vol% count as the same`) : ""].filter(Boolean).join(", ")) });
        save(); render(); return;
      }
    }
    S.msgs.push({ role: "user", text });
    const ta = document.getElementById("aiText"); if (ta) ta.value = "";
    S.busy = true; showConversation(); render();
    try {
      const r = await post("/api/ai/interpret", { text, session_id: S.sid });
      S.sid = r.session_id; S.lang = r.lang || S.lang;
      S.msgs.push({ role: "ai", reply: r });
    } catch (e) { S.msgs.push({ role: "ai", error: e.message }); }
    S.busy = false; save(); showConversation(); render(); redrawLeft();
  }
  async function answer(ans, auto) {
    if (!S.sid || S.busy) return;
    S.busy = true; showConversation(); render();
    try {
      const r = await post("/api/ai/answer", { session_id: S.sid, answers: ans || {}, auto: !!auto });
      const last = S.msgs[S.msgs.length - 1];
      if (last && last.role === "ai" && !last.done) last.reply = r; else S.msgs.push({ role: "ai", reply: r });
    } catch (e) { S.msgs.push({ role: "ai", error: e.message }); }
    S.busy = false; save(); showConversation(); render();
  }

  function render() {
    const el = document.getElementById("c-ai");
    if (el && el.classList.contains("on")) renderCenter(el);
  }
  function renderCenter(el) {
    const msgs = S.msgs.map((m, i) => {
      if (m.role === "user") return `<div class="ai-msg ai-user"><div class="ai-bubble">${esc(m.text)}</div></div>`;
      if (m.error) return `<div class="ai-msg"><div class="ai-card bad">${esc(m.error)}</div></div>`;
      if (m.note) {
        const waits = m.ask && S.loops.some((x) => x.id === m.loopId && x.wait === "answer" && x.askAt === i);
        const opts = waits
          ? `<div class="ai-opts" style="margin-top:6px">${m.ask.map((o) => `<button class="ai-opt" data-ailoopans="${esc(o.id)}" data-ailoopid="${esc(m.loopId)}">${esc(o.id === "stop" ? L("멈추기", "Stop") : o.label)}</button>`).join("")}</div>` : "";
        return `<div class="ai-msg"><div class="ai-card ai-note${m.loop ? " ai-loopmsg" : ""}">${m.note}${opts}</div></div>`;
      }
      if (m.design) return `<div class="ai-msg">${designCard(m.design, m.spec)}</div>`;
      if (m.check) return `<div class="ai-msg">${checkCard(m.check)}</div>`;
      return `<div class="ai-msg">${card(m.reply, i === S.msgs.length - 1 && !m.done, m.done)}</div>`;
    }).join("");
    const empty = S.msgs.length ? "" : `<div class="ai-empty">
        <div class="ai-empty-t">${icon("ai")}${L("무엇을 해석할까요?", "What should be analysed?")}</div>
        <div class="hint">${L("왼쪽에 자연어로 입력하세요. 예시를 누르면 입력란에 들어갑니다.", "Type a request on the left. An example below goes into the box.")}</div>
        <div class="ai-ex">${EXAMPLES.map((x) => `<button class="ai-exb" data-aiex="${esc(x)}">${esc(x)}</button>`).join("")}</div></div>`;
    el.innerHTML = `<div class="ai-wrap">${empty}${msgs}${loopStatus()}${S.busy ? `<div class="ai-msg"><div class="ai-card ai-busy">${L("읽는 중…", "Reading…")}</div></div>` : ""}</div>`;
    el.querySelectorAll("[data-ailoopans]").forEach((b) => b.onclick = () => loopAnswer(b.dataset.ailoopans, b.innerText, b.dataset.ailoopid));
    el.querySelectorAll("[data-ailoopstop]").forEach((b) => b.onclick = () => loopStop(b.dataset.ailoopstop));
    el.querySelectorAll("[data-aiex]").forEach((b) => b.onclick = () => { const ta = document.getElementById("aiText"); if (ta) { ta.value = b.dataset.aiex; ta.focus(); } });
    el.querySelectorAll("[data-aiopt]").forEach((b) => b.onclick = () => {
      const q = b.dataset.aiq;
      if (b.dataset.multi) { b.classList.toggle("on"); return; }
      answer({ [q]: b.dataset.aiopt });
    });
    el.querySelectorAll("[data-aimulti]").forEach((b) => b.onclick = () => {
      const q = b.dataset.aimulti;
      const vals = [...el.querySelectorAll(`[data-aiq="${q}"].on`)].map((x) => x.dataset.aiopt);
      if (vals.length) answer({ [q]: vals });
    });
    el.querySelectorAll("[data-aifree]").forEach((b) => b.onclick = () => {
      const inp = el.querySelector(`[data-aiin="${b.dataset.aifree}"]`);
      if (inp && inp.value.trim()) answer({ [b.dataset.aifree]: inp.value.trim() });
    });
    el.querySelectorAll("[data-aiin]").forEach((inp) => inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.isComposing && inp.value.trim()) answer({ [inp.dataset.aiin]: inp.value.trim() });
    }));
    const auto = el.querySelector("[data-aiauto]"); if (auto) auto.onclick = () => answer({}, true);
    const run = el.querySelector("[data-airun]"); if (run) run.onclick = () => execute(S.msgs[S.msgs.length - 1]);
    const edit = el.querySelector("[data-aiedit]"); if (edit) edit.onclick = () => openInTabs(S.msgs[S.msgs.length - 1].reply);
    el.querySelectorAll("[data-aiview]").forEach((b) => b.onclick = () => { H().attach(b.dataset.aiview); H().setCenter("res"); });
    const go = el.querySelectorAll("[data-aigo]"); go.forEach((b) => b.onclick = () => { const [t, c] = b.dataset.aigo.split(","); if (t) H().setTab(t); if (c) H().setCenter(c); });
    const w = el.querySelector(".ai-wrap"); if (w) el.scrollTop = el.scrollHeight;
  }

  function card(r, live, done) {
    if (!r) return "";
    const head = r.status === "ready" && (r.questions || []).length
      ? L("말하지 않은 조건은 추천값(*)으로 채웠습니다. 바꾸려면 아래에서 고르고, 그대로면 '진행'을 누르세요.", "What was not said is filled with recommended values (*). Change them below, or press Run as it is.")
      : r.status === "ready" ? L("아래 조건으로 진행합니다. 확인 후 '진행'을 누르세요.", "This is what will run. Check it and press Run.")
      : r.status === "invalid" ? L("MPSim이 이 조건을 받지 않습니다.", "MPSim does not accept these inputs.")
      : L("진행하려면 몇 가지가 더 필요합니다.", "A few things are still needed.");
    const rows = (r.summary || []).map((x) => `<tr><td>${esc(x.k)}</td><td>${esc(x.v)}${x.src ? `<div class="ai-src">${esc(x.src)}</div>` : ""}</td></tr>`).join("");
    const qs = live ? (r.questions || []).map((q) => question(q)).join("") : "";
    const probs = (r.problems || []).map((p) => `<div class="note bad">${esc(p)}</div>`).join("");
    const unres = (r.unresolved || []).filter((u) => u.kind === "content").map((u) => `<div class="note warn">${esc(L(`'${u.text}'가 어느 재료의 값인지 알 수 없어 쓰지 않았습니다.`, `'${u.text}' could not be tied to a material and was not used.`))}</div>`).join("");
    const opt = (r.questions || []).some((q) => !q.essential);
    const ess = (r.questions || []).some((q) => q.essential);
    const btns = !live ? "" : `<div class="row gap ai-actions">
        ${r.payload && !ess && !(r.problems || []).length ? `<button class="btn primary" data-airun>${icon("play")}${L("진행", "Run")}</button>` : ""}
        ${opt && !r.auto ? `<button class="btn" data-aiauto>${icon("auto")}${L("알아서 (추천값으로)", "Decide for me (recommended)")}</button>` : ""}
        ${r.payload ? `<button class="btn" data-aiedit>${icon("structure")}${L("탭에서 열어 고치기", "Open in the tabs to edit")}</button>` : ""}</div>`;
    const doneTxt = done ? `<div class="hint ai-done">${esc(done)}</div>` : "";
    const how = live && r.llm_used && r.llm_used.length
      ? `<div class="hint ai-how">${L("로컬 모델이 읽고 규칙이 검산했습니다", "Read by the local model, checked by the rules")}${r.llm_seconds != null ? ` · ${Number(r.llm_seconds).toFixed(1)} s` : ""}</div>`
      : live ? `<div class="hint ai-how">${L("규칙으로 읽었습니다", "Read by the rules")}</div>` : "";
    return `<div class="ai-card"><div class="ai-head">${esc(head)}</div>
      <table class="ai-sum">${rows}</table>${probs}${unres}${qs ? `<div class="ai-qs">${qs}</div>` : ""}${btns}${doneTxt}${how}</div>`;
  }
  function question(q) {
    const opts = (q.options || []).map((o) => `<button class="ai-opt${o.recommended ? " rec" : ""}" data-aiq="${esc(q.id)}" data-aiopt="${esc(o.value)}"${q.multi ? " data-multi=1" : ""}>${esc(o.label)}</button>`).join("");
    const multi = q.multi ? `<button class="btn sm" data-aimulti="${esc(q.id)}">${L("선택 완료", "Done")}</button>` : "";
    const free = q.free ? `<span class="ai-free"><input data-aiin="${esc(q.id)}" placeholder="${esc(L("직접 입력", "type an answer"))}"><button class="btn sm" data-aifree="${esc(q.id)}">OK</button></span>` : "";
    return `<div class="ai-q${q.essential ? " ess" : ""}"><div class="ai-qt">${q.essential ? `<b>${esc(q.text)}</b>` : esc(q.text)}${q.essential ? "" : `<span class="ai-def">${esc(L("말하지 않으면 추천값", "recommended if not answered"))}</span>`}</div>
      <div class="ai-opts">${opts}${multi}${free}</div></div>`;
  }

  // ------------------------------------------------------------ running it
  function openInTabs(r) {
    if (!r || !r.payload) return;
    const h = H(), p = r.payload;
    h.applyForm(p.form);
    if (p.doe) { h.setDoe(p.doe); h.setTab("doe"); return; }
    if (p.cal) { h.setCal(p.cal); h.setTab("calibration"); return; }
    h.setTab("structure"); h.setCenter("vis");
  }
  async function execute(m) {
    const r = m && m.reply;
    if (!r || !r.payload) return;
    const h = H(), p = r.payload;
    m.done = L("시작했습니다.", "Started.");
    try {
      h.applyForm(p.form);
      // the machine settings: only when the request named them, or for a study
      if (p.settings && (["text", "answer"].includes(p.settings_src) || !["run", "structure"].includes(p.kind))) {
        await h.settings(p.settings);
      }
      if (p.kind === "run" || p.kind === "structure") {
        await h.run(p.kind === "structure");
        // a comparison: the other alternatives queued after it, each on its own
        for (const f of p.more_forms || []) { h.applyForm(f); await h.run(false); }
        m.done = L("해석을 시작했습니다. 진행은 Runs와 Console에서, 결과는 Result Viewer에서 볼 수 있습니다.", "The run has started: follow it in Runs and the Console; the result opens in the Result Viewer.");
        S.msgs.push({ role: "ai", note: `${esc(m.done)} <button class="btn sm" data-aigo=",res">${L("Result Viewer", "Result Viewer")}</button>` });
      } else if (p.kind === "doe" || p.kind === "optimization" || p.kind === "design") {
        h.setDoe(p.doe);
        const before = h.state.doeId;
        await h.createDoe();
        const id = h.state.doeId;
        // MPSim shows why a study was refused; the study open before is not this one
        if (!id || id === before) throw new Error(L("DOE를 만들지 못했습니다 (MPSim 메시지 참고).", "The DOE was not created (see MPSim's message)."));
        if (p.kind === "doe") {
          m.done = L(`DOE ${p.doe.n_cases}케이스를 큐에 넣었습니다.`, `A DOE of ${p.doe.n_cases} cases is queued.`);
        } else if (p.kind === "optimization") {
          addLoop({ kind: "opt", doe: id, analysis: p.opt && p.opt.analysis, goal: (p.opt && p.opt.goal) || "max", target: p.opt && p.opt.target, state: {}, wait: "doe" });
          m.done = L(`DOE ${p.doe.n_cases}케이스를 큐에 넣었습니다. 끝나면 대리모델을 보고, 개선이 기대되는 점을 더 해석해 가며 최적점이 확정될 때까지 진행합니다.`,
            `A DOE of ${p.doe.n_cases} cases is queued. When it is done, the surrogate is examined and the points of highest expected improvement are run until the optimum stands.`);
        } else {
          addLoop({ kind: "design", doe: id, design: p.design, state: {}, wait: "doe" });
          m.done = L(`설계 DOE ${p.doe.n_cases}케이스를 큐에 넣었습니다. 끝나면 대리모델이 결정을 내릴 만큼 정확한지 보고, 모자라면 결정을 가르는 점을 더 해석해 가며 추천 조합이 확정되고 확인 해석이 목표를 만족할 때까지 진행합니다.`,
            `A design DOE of ${p.doe.n_cases} cases is queued. When it is done, the surrogate is checked for the decision; where it falls short, the points that settle it are run, until the recipe stands and its check run meets the target.`);
        }
        S.msgs.push({ role: "ai", note: `${esc(m.done)} <button class="btn sm" data-aigo="doe,doe">${L("DOE 결과", "DOE results")}</button>` });
        loopTick(3000);
      } else if (p.kind === "calibration") {
        h.setCal(p.cal);
        h.setTab("calibration");
        const jid = await h.runCal();
        if (jid) { addLoop({ kind: "cal", job: jid, form: p.form, cal: p.cal, round: 0, tried: [p.cal.plan_keys || ""], wait: "cal" }); loopTick(3000); }
        m.done = L("보정을 시작했습니다. 끝나면 결과를 읽고, 측정에 닿을 때까지 범위나 보정 대상을 바꿔 가며 계속합니다. 더 바꿀 것이 없으면 물어봅니다.",
          "The calibration has started. Its result is read when it is done, and ranges or unknowns are changed until it reaches the data; when nothing is left to change, you are asked.");
        S.msgs.push({ role: "ai", note: `${esc(m.done)} <button class="btn sm" data-aigo="calibration,cal">Calibration</button>` });
      }
    } catch (e) { S.msgs.push({ role: "ai", error: e.message }); }
    save();
    if (h.state.tab === "ai") { h.setCenter("ai"); }
    render();
  }

  // what a background step says: in the conversation, and as MPSim's toast while another tab is on screen
  function tell(msg, plain) {
    S.msgs.push(msg);
    try { if (H().state.center !== "ai" && plain) H().toast("AI: " + plain, 12000); } catch (e) { }
  }

  // a design: when its DOE is done, the recipe (/api/ai/design), then one run of it to check the prediction
  // n significant digits, trailing zeros of a decimal part dropped (20 stays 20, 1.50 is 1.5)
  const fmt = (v, n = 3) => {
    if (v == null || !isFinite(v)) return "-";
    if (Math.abs(v) >= Math.pow(10, n) && Math.abs(v) < 1e6) return String(Math.round(v));
    const t = Number(v).toPrecision(n);
    if (t.includes("e")) return t.replace(/\.?0+e/, "e");
    return t.includes(".") ? t.replace(/0+$/, "").replace(/\.$/, "") : t;
  };
  // ------------------------------------------------------------ loops
  // A study or a calibration runs until it answers: after every round the server (loop.py, calcheck.py) says
  // what to do next - more points, a check run, a new calibration, a question - and why. One loop at a time,
  // kept across reloads; words typed while it runs go to it first (stop, an answer, a condition).
  let loopTimer = null;
  function loopTick(ms) { clearTimeout(loopTimer); if (S.loops.length) loopTimer = setTimeout(loopStep, ms == null ? 10000 : ms); }
  function addLoop(lp) { lp.id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6); lp.t0 = Date.now(); S.loops.push(lp); return lp; }
  function endLoop(lp) { S.loops = S.loops.filter((x) => x.id !== lp.id); }
  const getJ = async (u) => (await fetch(u)).json();
  async function doeState(id) {
    const d = await getJ(`/api/doe/${id}`);
    const n = d.n_cases || 0, c = d.counts || {};
    const fin = (c.done || 0) + (c.failed || 0) + (c.stopped || 0);
    return { n, fin, queued: c.queued || 0, all: !!n && fin >= n };
  }
  // A few runs far slower than the rest (a packing that creeps on for hours) do not hold the study up: once nothing
  // is queued, at most a tenth of the cases (two at least) are left, and they have gone on for half as long again as
  // the study took to get there (ten minutes at least), the round goes on with the finished runs. The slow ones keep
  // running and join the round after they finish.
  function tailReady(lp, st) {
    const left = st.n - st.fin;
    if (st.queued > 0 || left > Math.max(2, Math.ceil(0.1 * st.n))) { lp.tailT = null; return false; }
    const now = Date.now();
    if (!lp.tailT) { lp.tailT = now; return false; }
    return now - lp.tailT > Math.max(10 * 60e3, 0.5 * (lp.tailT - (lp.t0 || lp.tailT)));
  }
  function loopNote(text, extra) { tell({ role: "ai", note: esc(text || "") + (extra || ""), loop: true }, text); }
  async function loopStep() {
    for (const lp of S.loops.slice()) {
      try { await loopOne(lp); } catch (e) { }     // the next look
    }
    save(); render();
    if (S.loops.length) loopTick();
  }
  async function loopOne(lp) {
    {
      if (lp.wait === "doe") {
        const st = await doeState(lp.doe);
        if (!st.all) {
          if (!tailReady(lp, st)) return;
          loopNote(L(`케이스 ${st.n - st.fin}개가 다른 케이스보다 훨씬 오래 걸려(예: 구조 생성), 끝난 ${st.fin}개로 이번 라운드를 판단합니다. 그 케이스는 계속 돌고, 끝나면 다음 라운드에 들어갑니다.`,
            `${st.n - st.fin} run(s) take far longer than the others (a structure still being packed, say): this round goes on with the ${st.fin} finished. They keep running and join the next round when done.`));
        }
        lp.tailT = null;
        if (lp.kind === "design") await designNext(lp); else await optNext(lp);
      } else if (lp.wait === "check" || lp.wait === "cal") {
        const j = await getJ(`/api/jobs/${lp.job}`);
        if (["failed", "stopped", "cancelled"].includes(j.state)) {
          endLoop(lp);
          S.msgs.push({ role: "ai", error: lp.wait === "cal" ? L(`보정이 끝나지 못했습니다 (${j.state}).`, `The calibration did not finish (${j.state}).`)
            : L(`확인 해석이 끝나지 못했습니다 (${j.state}).`, `The check run did not finish (${j.state}).`) });
          return;
        }
        if (j.state !== "done") return;
        const r = await getJ(`/api/jobs/${lp.job}/result`);
        if (lp.wait === "check") {
          // the check's mean and 95 % interval go back to the study's next round
          const tg = (lp.design || {}).target || {};
          const hl = {};
          (r.headline || []).forEach((x) => (hl[x.key] = x.value));
          const pe = (r.properties || r.props || {})[{ k: "thermal", sigma: "electrical", eps_r: "dielectric" }[tg.property] || ""] || {};
          const ci = Array.isArray(pe.ci95) ? pe.ci95.find((x) => x != null && isFinite(x)) : null;
          // every headline value too: a design with several targets is judged on all of them
          lp.state.check = Object.assign({}, lp.state.check || {}, { value: hl[tg.response || "k"], measured: hl, ci: ci == null ? null : ci, job: lp.job });
          tell({ role: "ai", check: { result: r, rec: lp.rec, spec: lp.design, job: lp.job, met: lp.met } },
            L("추천 조합의 확인 해석이 끝났습니다 (AI 탭)", "The check run of the recipe is done (AI tab)"));
          await designNext(lp);
        } else await calNext(lp, r);
      }
    }
  }
  async function designNext(lp) {
    const r = await post("/api/ai/design/next", { doe_id: lp.doe, design: lp.design, state: lp.state, lang: S.lang });
    lp.state = r.state || lp.state;
    lp.round = r.round;
    const res = r.result || {};
    if (r.action === "refine") {
      loopNote(r.text);
      await post(`/api/doe/${lp.doe}/cases`, { cases: r.points, label: L(`AI 라운드 ${r.round}`, `AI round ${r.round}`) });
      Object.assign(lp, { wait: "doe", t0: Date.now(), tailT: null });
      if (H().pollRuns) H().pollRuns();
    } else if (r.action === "check" && res.check_form) {
      tell({ role: "ai", design: res, spec: lp.design, doeId: lp.doe }, r.text);
      loopNote(r.text);
      const j = await post("/api/jobs", res.check_form);
      Object.assign(lp, { job: j.id, wait: "check", rec: res.recommended || res.best, met: (res.runs_met || [])[0] || null });
      if (H().pollRuns) H().pollRuns();
    } else {
      // done or stopped: the recipe as it stands, and why
      tell({ role: "ai", design: res, spec: lp.design, doeId: lp.doe }, r.text);
      loopNote(r.text);
      endLoop(lp);
    }
  }
  async function optNext(lp) {
    const r = await post("/api/ai/opt/next", { doe_id: lp.doe, analysis: lp.analysis, goal: lp.goal, target: lp.target, state: lp.state, lang: S.lang });
    lp.state = r.state || lp.state;
    lp.round = r.round;
    if (!(r.action === "done" && r.best)) loopNote(r.text);
    if (r.action === "refine" || r.action === "check") {
      // further points, or the predicted optimum run as a case of the study to check it
      await post(`/api/doe/${lp.doe}/cases`, { cases: r.points,
        label: r.action === "check" ? L("AI 최적점 확인", "AI optimum check") : L(`AI 라운드 ${r.round}`, `AI round ${r.round}`) });
      Object.assign(lp, { wait: "doe", t0: Date.now(), tailT: null });
      if (H().pollRuns) H().pollRuns();
      return;
    }
    endLoop(lp);
    if (r.action === "done" && r.best) {
      // the answer stands on a run; MPSim's Optimization tab shows the final study
      try { await H().openDoe(lp.doe); await H().optimize(r.response, lp.goal, lp.target); } catch (e) { }
      tell({ role: "ai", note: `${esc(r.text || "")} <button class="btn sm" data-aigo="optimization,opt">Optimization</button>`, loop: true }, r.text);
    }
  }
  async function calNext(lp, result, answer) {
    const body = { form: lp.form, cal: lp.cal, result: result || lp.result || {}, tried: lp.tried, round: lp.round, lang: S.lang };
    if (answer) body.answer = answer;
    const r = await post("/api/ai/calibration/next", body);
    if (r.action === "ask") {
      lp.wait = "answer";
      lp.result = result || lp.result;
      lp.askAt = S.msgs.length;
      tell({ role: "ai", note: esc(r.text || ""), loop: true, ask: (r.options || []), loopId: lp.id }, r.text);
      return;
    }
    tell({ role: "ai", note: `${esc(r.text || "")} <button class="btn sm" data-aigo="calibration,cal">Calibration</button>`, loop: true }, r.text);
    if (r.action === "rerun") {
      if (r.form) { lp.form = r.form; H().applyForm(r.form); }
      const cal = Object.assign({}, lp.cal, { unknowns: r.unknowns, plan_keys: r.keys });
      H().setCal(cal);
      const j2 = await H().runCal();
      if (!j2) { endLoop(lp); S.msgs.push({ role: "ai", error: L("다시 보정을 시작하지 못했습니다.", "The next calibration could not start.") }); return; }
      Object.assign(lp, { job: j2, cal, round: (lp.round || 0) + 1, tried: (lp.tried || []).concat([r.keys]), wait: "cal" });
      return;
    }
    endLoop(lp);      // done or stopped
  }
  async function loopAnswer(ans, shown, id) {
    const lp = S.loops.find((x) => x.kind === "cal" && x.wait === "answer" && (!id || x.id === id));
    if (!lp) return;
    S.msgs.push({ role: "user", text: shown || ans });
    S.busy = true; render();
    try { await calNext(lp, null, ans); } catch (e) { S.msgs.push({ role: "ai", error: e.message }); }
    S.busy = false; save(); render();
    loopTick();
  }
  async function loopStop(id) {
    // Stop means stop now: the study's runs and the calibration or check run that is going
    const which = S.loops.filter((x) => !id || x.id === id);
    if (!which.length) return;
    for (const lp of which) {
      endLoop(lp);
      try { if (lp.doe && lp.kind !== "cal") await post(`/api/doe/${lp.doe}/stop`, {}); } catch (e) { }
      try { if (lp.job && (lp.wait === "check" || lp.wait === "cal")) await post(`/api/jobs/${lp.job}/stop`, {}); } catch (e) { }
    }
    if (!S.loops.length) clearTimeout(loopTimer);
    S.msgs.push({ role: "ai", note: esc(L("멈췄습니다. 지금까지의 결과는 DOE·Calibration 탭에 남아 있습니다.", "Stopped. What was done so far stays in the DOE and Calibration tabs.")) });
    save(); render();
  }
  function loopStatus() {
    return S.loops.map((lp) => {
      const what = { doe: L("DOE 케이스 해석 중", "the study's runs are going"), check: L("추천 조합 확인 해석 중", "the recipe's check run is going"),
        cal: L("보정 해석 중", "the calibration is going"), answer: L("답을 기다리는 중", "waiting for your answer") }[lp.wait] || "";
      const kind = { design: L("설계", "Design"), opt: L("최적화", "Optimisation"), cal: L("보정", "Calibration") }[lp.kind] || "";
      return `<div class="ai-msg"><div class="ai-card ai-note ai-loop">${icon("auto")}<b>${esc(kind)}</b> · ${esc(L("라운드", "round"))} ${(lp.round || 0) + (lp.kind === "cal" ? 1 : 0)} · ${esc(what)}
        <span class="hint">${esc(L("'멈춰'로 멈추고, 조건을 말하면 다음 라운드부터 반영합니다.", "Type 'stop' to stop; a condition you type applies from the next round."))}</span>
        <button class="btn sm" data-ailoopstop="${esc(lp.id)}">${L("멈추기", "Stop")}</button></div></div>`;
    }).join("");
  }
  if (S.loops.length) loopTick(3000);

  function recipeText(rec, spec) {
    if (!rec) return "";
    const same = spec && spec.same_material, ph = (spec && spec.phases) || [];
    const parts = [L(`총 함량 ${fmt(rec.content, 3)} ${(spec && spec.basis) || "vol"}%`, `total ${fmt(rec.content, 3)} ${(spec && spec.basis) || "vol"}%`)];
    if (rec.shares) {
      // three sizes: each one's size and part of the filler
      const tag = [L("굵은", "coarse"), L("중간", "medium"), L("미세", "fine")];
      (rec.sizes_um || []).forEach((d, i) => parts.push(L(`${tag[i]} ${fmt(d, 2)} µm ${fmt(rec.shares[i], 2)}%`, `${tag[i]} ${fmt(d, 2)} µm ${fmt(rec.shares[i], 2)} %`)));
      return parts.join(" · ") + L(" (필러 중 비율)", " (of the filler)");
    }
    (rec.sizes_um || []).forEach((d, i) => parts.push(same ? (i === 0 ? L(`굵은 입자 ${fmt(d, 2)} µm`, `coarse ${fmt(d, 2)} µm`) : L(`미세 입자 ${fmt(d, 2)} µm`, `fine ${fmt(d, 2)} µm`))
      : `${(ph[i] || {}).name || ""} ${fmt(d, 2)} µm`));
    if (rec.share != null) parts.push(same ? L(`미세 입자 ${fmt(rec.share, 2)}% (필러 중)`, `fine ${fmt(rec.share, 2)}% of the filler`) : L(`두 번째 필러 ${fmt(rec.share, 2)}%`, `second filler ${fmt(rec.share, 2)}%`));
    return parts.join(" · ");
  }
  function designCard(res, spec) {
    const tg = res.target || {}, u = { k: "W/m·K", sigma: "S/m", alpha: "ppm/K", E: "GPa" }[tg.property] || "";
    const pn = { k: L("열전도도", "thermal conductivity"), sigma: L("전기전도도", "electrical conductivity"), eps_r: L("유전율", "permittivity"), alpha: "CTE", E: L("탄성률", "modulus") }[tg.property] || tg.property;
    const op = { ">=": "≥", "<=": "≤", "=": "=" }[tg.op] || "";
    const rows = [];
    const s = res.surrogate || {};
    if (res.reached) {
      const r = res.recommended;
      rows.push([L("추천 조합", "Recipe"), `<b>${esc(recipeText(r, spec))}</b>`]);
      if (r.from_run || (r.predicted_all || []).length < 2) rows.push(r.from_run
        ? [L("근거", "Basis"), `${esc(L("DOE에서 실제로 해석한 케이스", "a case the DOE actually ran"))}: ${esc(pn)} ${fmt(r.predicted)} ${u} (${L("목표", "target")} ${op} ${fmt(tg.value)})`]
        : [L("예측", "Predicted"), `${esc(pn)} ${fmt(r.predicted)} ± ${fmt(r.std, 2)} ${u} (${L("목표", "target")} ${op} ${fmt(tg.value)}; ${L("예측 − 1σ로 판정", "judged on the prediction − 1σ")})`]);
      if ((r.predicted_all || []).length > 1) {
        // several targets: every one's prediction, and the one that sets the content
        const PN = { k: "k", sigma: "σ", eps_r: "ε_r", alpha: "CTE", E: "E" };
        rows.push([L("목표별 예측", "Each target"), r.predicted_all.map((x) => `${esc(PN[x.property] || x.property)} ${fmt(x.predicted)} ± ${fmt(x.std, 2)} (${({ ">=": "≥", "<=": "≤", "=": "=" })[x.op] || ""} ${fmt(x.target)})${x.property === r.bind ? L(" ← 함량을 정하는 목표", " ← sets the content") : ""}`).join(" · ")]);
      }
      if (r.phi_m != null) rows.push([L("패킹·점도", "Packing, viscosity"), `φm ${fmt(r.phi_m)} · μr ${fmt(r.mu_r)} (Krieger-Dougherty)`]);
      if (res.lowest && Math.abs(res.lowest.content - r.content) > 0.05) rows.push([L("최저 함량 조합", "Lowest content"), esc(recipeText(res.lowest, spec)) + (res.lowest.mu_r != null ? ` · μr ${fmt(res.lowest.mu_r)}` : "")]);
    } else {
      const b = res.best || {};
      rows.push([L("목표 미달", "Not reached"), `<b>${esc(L(`범위 안에서 목표에 닿지 않습니다. 가장 높은 예측: ${fmt(b.predicted)} ± ${fmt(b.std, 2)} ${u}`, `the target is not reached in the range; the best prediction is ${fmt(b.predicted)} ± ${fmt(b.std, 2)} ${u}`))}</b>`]);
      rows.push([L("그 조합", "At"), esc(recipeText(b, spec))]);
    }
    rows.push([L("대리모델", "Surrogate"), esc(`${s.kind || ""} · ${L("교차검증", "cross-validated")} R² ${fmt(s.r2)} · RMSE ${fmt(s.rmse, 2)} ${u} · ${res.n_runs}/${res.n_cases} ${L("케이스", "cases")}`)]);
    const met = res.runs_met || [];
    rows.push([L("실제 해석", "Runs"), met.length ? esc(L("목표를 만족한 케이스 (함량 낮은 순): ", "cases that met the target, least filler first: ") + met.map((x) => `${fmt(x.content)}% → ${fmt(x.value)} ${u}`).join(", "))
      : esc(L(`목표를 만족한 케이스 없음 (최고 ${fmt((res.runs_best || {}).value)} ${u})`, `no case met the target (best ${fmt((res.runs_best || {}).value)} ${u})`))]);
    const hd = res.held || {};
    const notes = (res.notes || []).map((n) => ({
      packing_limit: L(`케이스 ${hd.n}개는 ${fmt(hd.set_min)}~${fmt(hd.set_max)} vol%로 설정했지만 구조에는 ${fmt(hd.held_min)}~${fmt(hd.held_max)} vol%만 들어갔습니다(겹침 없이 채울 수 있는 한계). 그 입자로는 최대 함량을 올려도 더 들어가지 않습니다.`,
        `${hd.n} cases set to ${fmt(hd.set_min)}-${fmt(hd.set_max)} vol% held only ${fmt(hd.held_min)}-${fmt(hd.held_max)} vol% (as far as they pack without overlap): a higher content does not put more of those particles in.`),
      at_lower_bound: L("최저 함량이 범위의 아래 끝입니다. 더 낮은 함량에서도 될 수 있으니 범위를 넓혀 다시 보세요.", "The lowest content is at the lower end of the range; lower may work - widen the range."),
      within_uncertainty: L("예측이 불확도 안에서 목표에 걸쳐 있습니다. 확인 해석이 판단합니다.", "The prediction meets the target only within its uncertainty; the check run decides."),
      not_reached: (res.notes || []).includes("packing_limit") ? L("R 값·크기 범위를 다시 보세요.", "Revisit the resistances and size range.")
        : L("최대 함량을 올리거나 R 값·크기 범위를 다시 보세요.", "Raise the highest content or revisit the resistances and size range."),
      weak_surrogate: L("대리모델의 교차검증이 약해(R² < 0.7) 예측 대신 목표를 실제로 만족한 최저 함량 케이스를 추천합니다. 대리모델의 조합은 '다른 조합'에 남겨 둡니다.", "The surrogate cross-validates weakly (R² < 0.7): the recommended recipe is the run that met the target with the least filler, not a prediction; the surrogate's recipes are listed below."),
    }[n] || n)).map((x) => `<div class="note warn">${esc(x)}</div>`).join("");
    const alts = (res.alternatives || []).length ? `<div class="hint" style="margin-top:6px">${L("비슷한 함량의 다른 조합", "Other recipes of about the same content")}</div><table class="ai-sum">${
      res.alternatives.map((a) => `<tr><td>${esc(recipeText(a, spec))}</td><td>${fmt(a.predicted)} ${u}${a.phi_m != null ? ` · φm ${fmt(a.phi_m)} · μr ${fmt(a.mu_r)}` : ""}</td></tr>`).join("")}</table>` : "";
    return `<div class="ai-card"><div class="ai-head">${L("설계 결과", "Design result")}</div><table class="ai-sum">${rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v}</td></tr>`).join("")}</table>${alts}${notes}</div>`;
  }
  function checkCard(c) {
    const r = c.result || {}, rec = c.rec || {}, tg = (c.spec || {}).target || {};
    const hl = {};
    (r.headline || []).forEach((h) => (hl[h.key] = h.value));
    const v = (r.properties || r.props || {}).viscosity || {};
    const got = hl[(tg.response) || "k"];
    // the realisations of the check run and their 95 % interval
    const pe = (r.properties || r.props || {})[{ k: "thermal", sigma: "electrical", eps_r: "dielectric" }[tg.property] || ""] || {};
    const nreal = Array.isArray(pe.seeds) ? pe.seeds.length : 0;
    const ci = Array.isArray(pe.ci95) ? pe.ci95.find((x) => x != null && isFinite(x)) : (isFinite(pe.ci95) ? pe.ci95 : null);
    const ok = got != null && (tg.op === "<=" ? got <= tg.value : tg.op === "=" ? Math.abs(got - tg.value) <= 0.02 * Math.abs(tg.value) : got >= tg.value);
    const rows = [[L("확인 해석", "Check run"), `<b>${fmt(got)}</b>${ci != null ? ` ± ${fmt(ci, 2)}` : ""}${nreal > 1 ? ` (${L(`구조 ${nreal}개의 평균, 95%`, `mean of ${nreal} realisations, 95 %`)})` : ""} · ${L("예측", "predicted")} ${fmt(rec.predicted)}${rec.from_run ? "" : ` ± ${fmt(rec.std, 2)}`} · ${ok ? L("목표 만족", "meets the target") : (ci != null && Math.abs(got - tg.value) <= ci ? L("목표 미달 (구조 산포 안)", "below the target (within the scatter)") : L("목표 미달", "below the target"))}`]];
    // several targets: each one measured against its own
    const tgs = (c.spec || {}).targets || [];
    if (tgs.length > 1) {
      const PN = { k: "k", sigma: "σ", eps_r: "ε_r", alpha: "CTE", E: "E" };
      rows.push([L("목표별", "Each target"), tgs.map((t) => {
        const g = hl[t.response], o = { ">=": "≥", "<=": "≤", "=": "=" }[t.op] || "";
        const okT = g != null && (t.op === "<=" ? g <= t.value : t.op === "=" ? Math.abs(g - t.value) <= 0.02 * Math.abs(t.value) : g >= t.value);
        return `${esc(PN[t.property] || t.property)} ${fmt(g)} (${o} ${fmt(t.value)}) ${okT ? "✓" : "✗"}`;
      }).join(" · ")]);
    }
    if (got != null && !ok) {
      // the loop takes it from here: the short check joins the data and the recipe is chosen again
      rows.push([L("다음", "Next"), esc(L("확인 해석이 목표에 미달해, 이 결과를 데이터에 넣고 다음 라운드에서 조합을 다시 고릅니다.",
        "The check run is below the target: it joins the data and the next round chooses the recipe again."))]);
    }
    if (v.mu_r != null) rows.push([L("점도", "Viscosity"), `μr ${fmt(v.mu_r)} (${esc(v.basis || "")})${rec.mu_r != null ? ` · Krieger-Dougherty ${fmt(rec.mu_r)}` : ""}${v.phi_m != null ? ` · φm ${fmt(v.phi_m)}` : ""}`]);
    return `<div class="ai-card"><div class="ai-head">${L("추천 조합 확인", "Recipe check")}</div><table class="ai-sum">${rows.map(([k, x]) => `<tr><td>${esc(k)}</td><td>${x}</td></tr>`).join("")}</table>
      <div class="row gap ai-actions"><button class="btn sm" data-aiview="${esc(c.job)}">${L("Result Viewer에서 보기", "Open in the Result Viewer")}</button></div></div>`;
  }

  function action(a) {
    if (a === "new") { S.sid = null; S.msgs = []; save(); render(); const ta = document.getElementById("aiText"); if (ta) { ta.value = ""; ta.focus(); } }
    if (a === "examples") { S.msgs = []; S.sid = null; save(); H().setCenter("ai"); }
  }

  // the Run buttons of MPSim (header and ribbon) run the request on the AI tab
  function ready() {
    const m = S.msgs[S.msgs.length - 1];
    return !!(m && m.reply && m.reply.payload && !m.done && m.reply.status === "ready");
  }
  function runReady() { if (ready()) return execute(S.msgs[S.msgs.length - 1]); }

  window.AIMPSim = { left, mountLeft, renderCenter, action, send, ready, runReady };
})();
