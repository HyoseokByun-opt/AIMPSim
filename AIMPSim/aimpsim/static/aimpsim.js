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
  const S = { sid: null, msgs: [], busy: false, lang: "en", status: null, pendingOpt: null };
  try { const s = JSON.parse(localStorage.getItem(KEY) || "null"); if (s) Object.assign(S, s, { busy: false }); } catch (e) { }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify({ sid: S.sid, msgs: S.msgs.slice(-40), lang: S.lang, pendingOpt: S.pendingOpt })); } catch (e) { } };
  const L = (ko, en) => (S.lang === "ko" ? ko : en);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (n) => (H() ? H().I(n) : "");

  const EXAMPLES = [
    "에폭시 수지 45%와 구형 알루미나 필러 55 vol%가 섞인 복합재의 열전도도 구해줘",
    "애폭시에 실리카 0.55만큼, 입경 5마이크로, 열전도율이랑 CTE 알아서 해줘",
    "실리콘에 판상 질화붕소 30wt% 종횡비 10, 열전도도 3방향, 정확하게",
    "에폭시에 알루미나 10마이크로 구형 40~60% 범위로 5단계 DOE, 열전도도",
    "에폭시에 실리카 20%일 때 0.45 W/mK, 40%일 때 0.8 W/mK 측정됐어. 계면저항 보정해줘",
    "에폭시에 알루미나 함량을 40~60%로 바꿔가며 열전도도가 최대가 되는 조건 찾아줘",
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
  function left() {
    const st = S.status;
    const llm = !st ? "" : st.llm && st.llm.enabled
      ? `${L("로컬 모델", "Local model")}: ${st.llm.running ? L("실행 중", "running") : L("필요할 때 시작", "starts when needed")}`
      : L("로컬 모델 없음 - 규칙으로 읽습니다", "No local model - requests are read by rules");
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
        <div>${L("<b>물성값</b>은 MPSim 라이브러리 값만 씁니다. 라이브러리에 없는 재료는 지어내지 않고 묻습니다.", "<b>Material values</b> are the MPSim library's; a material it does not hold is asked about, never made up.")}</div>
        <div>${L("말하지 않은 정확도·병렬·형상·크기는 추천값과 함께 묻고, '알아서'라고 하면 문제에 맞게 정합니다.", "Accuracy, parallel runs, shape and size not given are asked with a recommendation; \"decide for me\" sets them for the problem.")}</div>
      </div></div>
      <div class="sec"><div class="sh">${icon("solver")}AIMPSim</div><div class="sb"><div class="hint">${esc(llm)}${st ? ` · v${esc(st.version)}` : ""}</div></div></div>`;
  }
  function mountLeft(body) {
    const ta = body.querySelector("#aiText");
    if (!ta) return;
    body.querySelector("#aiSend").onclick = () => send(ta.value);
    body.querySelector("#aiNew").onclick = () => action("new");
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(ta.value); } });
    if (!S.status) fetch("/api/ai/status").then((r) => r.json()).then((j) => { S.status = j; if (H().state.tab === "ai") H().renderLeft(); }).catch(() => { });
    setTimeout(() => ta.focus(), 0);
  }

  // ------------------------------------------------------------ conversation
  async function send(text) {
    text = String(text || "").trim();
    if (!text || S.busy) return;
    if (/[가-힣]/.test(text)) S.lang = "ko"; else if (!S.msgs.length) S.lang = "en";
    S.msgs.push({ role: "user", text });
    S.busy = true; render();
    const ta = document.getElementById("aiText"); if (ta) ta.value = "";
    try {
      const r = await post("/api/ai/interpret", { text, session_id: S.sid });
      S.sid = r.session_id; S.lang = r.lang || S.lang;
      S.msgs.push({ role: "ai", reply: r });
    } catch (e) { S.msgs.push({ role: "ai", error: e.message }); }
    S.busy = false; save(); render(); H().renderLeft();
  }
  async function answer(ans, auto) {
    if (!S.sid || S.busy) return;
    S.busy = true; render();
    try {
      const r = await post("/api/ai/answer", { session_id: S.sid, answers: ans || {}, auto: !!auto });
      const last = S.msgs[S.msgs.length - 1];
      if (last && last.role === "ai" && !last.done) last.reply = r; else S.msgs.push({ role: "ai", reply: r });
    } catch (e) { S.msgs.push({ role: "ai", error: e.message }); }
    S.busy = false; save(); render();
  }

  function render() {
    const el = document.getElementById("c-ai");
    if (el && el.classList.contains("on")) renderCenter(el);
  }
  function renderCenter(el) {
    const msgs = S.msgs.map((m, i) => {
      if (m.role === "user") return `<div class="ai-msg ai-user"><div class="ai-bubble">${esc(m.text)}</div></div>`;
      if (m.error) return `<div class="ai-msg"><div class="ai-card bad">${esc(m.error)}</div></div>`;
      if (m.note) return `<div class="ai-msg"><div class="ai-card ai-note">${m.note}</div></div>`;
      return `<div class="ai-msg">${card(m.reply, i === S.msgs.length - 1 && !m.done, m.done)}</div>`;
    }).join("");
    const empty = S.msgs.length ? "" : `<div class="ai-empty">
        <div class="ai-empty-t">${icon("ai")}${L("무엇을 해석할까요?", "What should be analysed?")}</div>
        <div class="hint">${L("왼쪽에 자연어로 입력하세요. 예시를 누르면 입력란에 들어갑니다.", "Type a request on the left. An example below goes into the box.")}</div>
        <div class="ai-ex">${EXAMPLES.map((x) => `<button class="ai-exb" data-aiex="${esc(x)}">${esc(x)}</button>`).join("")}</div></div>`;
    el.innerHTML = `<div class="ai-wrap">${empty}${msgs}${S.busy ? `<div class="ai-msg"><div class="ai-card ai-busy">${L("읽는 중…", "Reading…")}</div></div>` : ""}</div>`;
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
    return `<div class="ai-card"><div class="ai-head">${esc(head)}</div>
      <table class="ai-sum">${rows}</table>${probs}${unres}${qs ? `<div class="ai-qs">${qs}</div>` : ""}${btns}${doneTxt}</div>`;
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
        m.done = L("해석을 시작했습니다. 진행은 Runs와 Console에서, 결과는 Result Viewer에서 볼 수 있습니다.", "The run has started: follow it in Runs and the Console; the result opens in the Result Viewer.");
        S.msgs.push({ role: "ai", note: `${esc(m.done)} <button class="btn sm" data-aigo=",res">${L("Result Viewer", "Result Viewer")}</button>` });
      } else if (p.kind === "doe" || p.kind === "optimization") {
        h.setDoe(p.doe);
        await h.createDoe();
        const id = h.state.doeId;
        if (p.kind === "optimization") {
          S.pendingOpt = { id, analysis: p.opt && p.opt.analysis, goal: p.opt && p.opt.goal, target: p.opt && p.opt.target };
          m.done = L(`DOE ${p.doe.n_cases}케이스를 큐에 넣었습니다. 모두 끝나면 최적점을 찾습니다.`, `A DOE of ${p.doe.n_cases} cases is queued; its optimum is searched once they finish.`);
          watchOpt();
        } else m.done = L(`DOE ${p.doe.n_cases}케이스를 큐에 넣었습니다.`, `A DOE of ${p.doe.n_cases} cases is queued.`);
        S.msgs.push({ role: "ai", note: `${esc(m.done)} <button class="btn sm" data-aigo="doe,doe">${L("DOE 결과", "DOE results")}</button>` });
      } else if (p.kind === "calibration") {
        h.setCal(p.cal);
        h.setTab("calibration");
        await h.runCal();
        m.done = L("보정을 시작했습니다. Calibration 탭에서 진행을 볼 수 있습니다.", "The calibration has started; follow it in the Calibration tab.");
        S.msgs.push({ role: "ai", note: `${esc(m.done)} <button class="btn sm" data-aigo="calibration,cal">Calibration</button>` });
      }
    } catch (e) { S.msgs.push({ role: "ai", error: e.message }); }
    save();
    if (h.state.tab === "ai") { h.setCenter("ai"); }
    render();
  }

  // an optimisation: when every case of its DOE is done, the optimum of the
  // response the request named
  let optTimer = null;
  function watchOpt() {
    clearTimeout(optTimer);
    const po = S.pendingOpt;
    if (!po || !po.id) return;
    optTimer = setTimeout(async () => {
      try {
        const d = await (await fetch(`/api/doe/${po.id}`)).json();
        const n = d.n_cases || 0, c = d.counts || {};
        const finished = (c.done || 0) + (c.failed || 0) + (c.stopped || 0);
        if (n && finished >= n) {
          const want = (po.analysis && H().AN[po.analysis] ? H().AN[po.analysis].title : "").toLowerCase();
          const ms = d.metrics || [];
          const m = ms.find((x) => want && x.label.toLowerCase().includes(want.split(" ")[0])) || ms[0];
          S.pendingOpt = null; save();
          if (!m) { S.msgs.push({ role: "ai", error: L("DOE 결과에 응답값이 없습니다.", "The DOE gave no response to optimise.") }); render(); return; }
          await H().openDoe(po.id);
          await H().optimize(m.key, po.goal, po.target);
          S.msgs.push({ role: "ai", note: esc(L(`DOE가 끝나 '${m.label}'의 ${po.goal === "min" ? "최소" : po.goal === "target" ? "목표값" : "최대"} 조건을 찾았습니다. Optimization 탭을 보세요.`, `The DOE has finished; the ${po.goal === "min" ? "minimum" : po.goal === "target" ? "target" : "maximum"} of '${m.label}' is in the Optimization tab.`)) });
          save(); render();
          return;
        }
      } catch (e) { /* the next look */ }
      watchOpt();
    }, 15000);
  }
  if (S.pendingOpt) setTimeout(watchOpt, 3000);

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
