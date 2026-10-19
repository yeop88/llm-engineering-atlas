// agent/agent.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
setupCollectionPickers({ col: $("#a-col"), idx: $("#a-idx") });
const ACT = { search: ["검색", ""], read: ["읽기", ""], calc: ["계산", ""], finish: ["답하기", "ok"], error: ["형식 오류", "err"], forced_finish: ["모은 근거로 답함", "warn"], lookup: ["번호 조회", ""] };

$("#a-run").onclick = async e => {
  const q = $("#a-q").value.trim();
  if (!q) return toast("질문을 입력하세요", "err");
  const body = { question: q, config: { mode: $("#a-mode").value, index_id: +$("#a-idx").value }, agent: { max_steps: +$("#a-steps").value || 5, top_k: +$("#a-k").value || 4, lookup: $("#a-lookup").checked },
    model: $("#a-model").value.trim() || null };
  $("#a-steps-out").innerHTML = ""; $("#a-final").innerHTML = "";
  e.target.disabled = true;
  try {
    // 단계가 끝날 때마다 한 줄(NDJSON)씩 받아 바로 그린다 — 로컬 LLM 은 단계마다 수 초~수십 초
    const resp = await fetch("/api/agent/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!resp.ok) { toast((await resp.json()).detail || "실패", "err"); return; }
    const reader = resp.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n")) >= 0) { const line = buf.slice(0, i); buf = buf.slice(i + 1); if (line.trim()) show(JSON.parse(line)); }
    }
  } finally { e.target.disabled = false; }
};

function show(ev) {
  if (ev.type === "step") {
    const [name, cls] = ACT[ev.action] || [ev.action, ""];
    $("#a-steps-out").insertAdjacentHTML("beforeend", html`<div class="card stack p-2">
      <div class="row between"><span><span class="stage-no">${ev.n}</span> <span class="badge ${cls}">${name}</span> <span class="mono small">${ev.input || ""}</span></span><span class="small muted">${ev.ms ? (ev.ms / 1000).toFixed(1) + "s" : "주어진 첫 검색"}</span></div>
      ${ev.thought ? html`<div class="small muted">생각: ${ev.thought}</div>` : ""}
      ${ev.observation ? html`<pre class="small pre m-0">${ev.observation}</pre>` : ""}</div>`);
  } else if (ev.type === "final") {
    const v = ev.verify;
    $("#a-final").innerHTML = html`<div class="card stack mt-3"><div class="row between"><h2>답변</h2><span class="small muted">${ev.n_steps}단계 · ${ev.seconds}s${ev.run_id ? html` · run #${ev.run_id}` : ""}</span></div>
      <div class="pre">${ev.answer}</div>
      <div class="small muted">근거 있는 문장 ${v.supported_ratio != null ? (v.supported_ratio * 100).toFixed(0) + "%" : "-"} · 인용 ${html.join(v.cited_sources.map(n => html`[${n}]`), "") || "없음"}${v.invalid_citations.length ? html` · <span class="badge err">없는 근거 ${html.join(v.invalid_citations, ", ")}</span>` : ""}</div>
      ${citeBox(ev.citations)}
      <h3>모은 근거 (${ev.sources.length})</h3>${html.join(ev.sources.map((s, i) => html`<div class="small"><span class="badge">[${i + 1}]</span> <b>${s.filename || ""}</b>${s.page ? html` p.${s.page}` : ""} <span class="muted">${(s.text || "").slice(0, 160)}</span></div>`), "")}</div>`;
  } else if (ev.type === "error") {
    $("#a-final").innerHTML = html`<div class="errbox">${ev.message}</div>`;
  }
}
