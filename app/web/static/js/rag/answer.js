// rag/answer.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
let cols = [], detail = null;
const STATUS = {
  supported: ["ok", "근거 있음"], weak: ["warn", "근거 약함"], unsupported: ["err", "근거 없음"], uncited: ["warn", "인용 없음"], refusal: ["", "답 없음"],
};

async function loadCols() {
  cols = await api("/api/collections");
  $("#a-col").innerHTML = html.or(html.join(cols.map(c => html`<option value="${c.id}">${c.name} (문서 ${c.n_documents})</option>`), ""), html`<option value="">컬렉션 없음</option>`);
  applyCtx($("#a-col"));
  await loadDetail();
}
async function loadDetail() {
  if (!$("#a-col").value) return;
  detail = await api(`/api/collections/${$("#a-col").value}`);
  const idx = detail.indexes.filter(i => i.status === "ready");
  const csName = id => detail.chunk_sets.find(c => c.id === id)?.name || `#${id}`;
  $("#a-idx").innerHTML = html.or(html.join(idx.map(i => html`<option value="${i.id}">${i.model_hf_id.split("/").pop()} · ${csName(i.chunk_set_id)}</option>`), ""), html`<option value="">준비된 인덱스 없음</option>`);
  applyCtx($("#a-idx"));
  $("#a-cs").innerHTML = html.join(detail.chunk_sets.filter(c => c.status === "ready").map(c => html`<option value="${c.id}">${c.name}</option>`), "");
  applyCtx($("#a-cs"));
  if (!idx.length) $("#a-mode").value = "bm25";
  modeChanged();
  const all = (await api(`/api/collections/${detail.id}/eval-sets`)).filter(s => s.status === "ready");
  $("#e-set").innerHTML = html.or(html.join(all.map(s => html`<option value="${s.id}">#${s.id} ${s.name} (${s.n_items}문항)</option>`), ""), html`<option value="">평가 세트 없음 (컬렉션 ⑤ 평가 탭에서 만드세요)</option>`);
  applyCtx($("#e-set"));
  // 평가 세트 질문을 예시로
  const sets = all.filter(s => s.method !== "sentence");
  $("#a-examples").innerHTML = "";
  if (sets.length) {
    const s = await api(`/api/eval-sets/${sets[0].id}`);
    $("#a-examples").innerHTML = '<span class="muted">예시:</span>' + s.items.slice(0, 6).map(it => html`<button class="btn sm" data-q="${it.query}">${it.query.slice(0, 40)}</button>`).join("");
    $("#a-examples").querySelectorAll("[data-q]").forEach(b => (b.onclick = () => { $("#a-q").value = b.dataset.q; $("#a-q").focus(); }));
  }
}
function modeChanged() {
  const bm25 = $("#a-mode").value === "bm25";
  $("#a-idx-wrap").hidden = bm25; $("#a-cs-wrap").hidden = !bm25;
}
$("#a-col").addEventListener("change", () => { loadDetail(); });
$("#a-mode").addEventListener("change", modeChanged);

async function loadLlm() {
  const s = await api("/api/llm/status");
  $("#a-llm").innerHTML = s.default.error ? html`<span class="badge warn">LLM 미설정</span> <a href="/settings/llm">LLM 연결</a>에서 확인하세요.` : html`기본: <span class="mono">${s.default.model}</span>`;
  try { const m = await api("/api/llm/models"); $("#a-model-list").innerHTML = html.join(m.models.map(x => html`<option value="${x}">`), ""); } catch { /* 로컬 서버가 꺼져 있으면 목록 없음 */ }
  const rr = (await getModels()).filter(m => m.kind === "reranker" && m.cached);
  $("#a-rr").innerHTML += html.join(rr.map(r => html`<option value="${r.id}">${r.name}</option>`), "");
}

// 답변 본문: [n] 을 근거로 가는 칩으로
function renderAnswer(text, turnId, nSources) {
  // 글자를 먼저 이스케이프한 뒤 [n] 을 근거 칩으로 · 줄바꿈을 <br> 로 바꾼다 — 결과는 이미 안전한 HTML 이라 raw
  return raw(esc(text).replace(/\[(\d{1,2}(?:\s*[,，]\s*\d{1,2})*)\]/g, (_, g) => html.join(g.split(/[,，]/).map(n => {
    const k = +n.trim();
    return html`<a href="#${turnId}-src-${k}" class="cite ${k >= 1 && k <= nSources ? "" : "bad"}" onclick="openSrc('${turnId}', ${k})">${k}</a>`;
  }), "")).replace(/\n/g, "<br>"));
}
function openSrc(turnId, k) {
  const el = document.getElementById(`${turnId}-src-${k}`);
  if (!el) return;
  el.closest("details").open = true;
  el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1200);
}

async function send() {
  const q = $("#a-q").value.trim();
  if (!q) return;
  if (!$("#a-col").value) return toast("컬렉션을 먼저 만드세요", "err");
  const bm25 = $("#a-mode").value === "bm25";
  const body = {
    question: q, context_top: +$("#a-top").value, max_tokens: +$("#a-max").value, judge: $("#a-judge").checked, compress: $("#a-compress").checked ? { keep: 3 } : null, images: $("#a-images").checked,
    provider: $("#a-provider").value || null, model: $("#a-model").value.trim() || null,
    config: { mode: $("#a-mode").value, index_id: bm25 ? null : +$("#a-idx").value || null, chunk_set_id: bm25 ? +$("#a-cs").value || null : null, reranker_id: +$("#a-rr").value || null },
  };
  if (!bm25 && !body.config.index_id) return toast("벡터 인덱스가 없습니다. BM25 를 고르거나 인덱스를 만드세요.", "err");
  const turnId = "t" + Date.now();
  if ($("#a-thread .empty")) $("#a-thread").innerHTML = "";
  $("#a-thread").insertAdjacentHTML("beforeend", html`<div class="card stack" id="${turnId}">
    <div class="q-bubble">${q}</div>
    <div class="small muted" data-status>검색 중…</div>
    <div class="answer" data-answer></div>
    <div data-verify></div>
    <details data-sources><summary class="small">근거 <span data-nsrc></span></summary><div data-srclist class="stack mt-2"></div></details>
    <div class="small muted" data-meta></div></div>`);
  const turn = document.getElementById(turnId), $t = s => turn.querySelector(s);
  turn.scrollIntoView({ behavior: "smooth", block: "end" });
  $("#a-q").value = ""; $("#a-send").disabled = true;
  let text = "", sources = [], verify = null;
  try {
    const res = await fetch(`/api/collections/${$("#a-col").value}/answer`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.statusText); }
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl); buf = buf.slice(nl + 1);
        if (!line.trim()) continue;
        const ev = JSON.parse(line);
        if (ev.type === "search") {
          sources = ev.sources;
          $t("[data-status]").textContent = `근거 ${sources.length}개 · ${ev.llm.model} 답변 생성 중…`;
          $t("[data-nsrc]").textContent = `${sources.length}개`;
          $t("[data-srclist]").innerHTML = html.join(sources.map((s, i) => html`<div class="src" id="${turnId}-src-${i + 1}"><span class="cite">${i + 1}</span> <b class="small">${s.filename}${s.page ? html` p.${s.page}` : ""}${s.heading ? html` · ${s.heading}` : ""}</b> <span class="small muted mono">${s.score?.toFixed?.(3) ?? ""}</span><div class="small">${s.text}</div></div>`), "");
        } else if (ev.type === "delta") {
          text += ev.text;
          $t("[data-answer]").innerHTML = renderAnswer(text, turnId, sources.length) + '<span class="caret">▍</span>';
        } else if (ev.type === "verify") {
          verify = ev;
          const cnt = {};
          ev.sentences.forEach(s => (cnt[s.status] = (cnt[s.status] || 0) + 1));
          $t("[data-answer]").innerHTML = html.join(ev.sentences.map(s => html`<span class="sent sent-${s.status}${s.off_topic ? " sent-offtopic" : ""}" title="${STATUS[s.status][1]} · 인용 근거와 글자 겹침 ${Math.round(s.support * 100)}%${s.best_source ? html` (가장 비슷한 근거 [${s.best_source}] ${Math.round(s.best_support * 100)}%)` : ""}${s.relevance != null ? html` · 질문 관련성 ${Math.round(s.relevance * 100)}%${s.off_topic ? " — 질문과 관련 낮음" : ""}` : ""}">${renderAnswer(s.text, turnId, sources.length)}</span>`), " ");
          $t("[data-verify]").innerHTML = html`<div class="row small gap-2">${html.join(Object.entries(cnt).map(([k, v]) => html`<span class="badge ${STATUS[k][0]}">${STATUS[k][1]} ${v}</span>`), "")}
            ${ev.invalid_citations.length ? html`<span class="badge err">없는 근거 번호 ${html.join(ev.invalid_citations, ", ")}</span>` : ""}
            ${ev.off_topic ? html`<span class="badge warn" title="근거에 있어도 질문과 상관없는 문장은 틀린 답입니다 (질문-문장 유사도 < ${ev.relevance_threshold})">질문과 관련 낮음 ${ev.off_topic}</span>` : ""}
            <span class="muted">문장에 마우스를 올리면 근거와의 겹침 · 질문 관련성이 보입니다. 점선 밑줄 = 질문과 관련 낮음.</span></div>${citeBox(ev.citations)}`;
          ev.cited_sources.forEach(k => document.getElementById(`${turnId}-src-${k}`)?.classList.add("cited"));
        } else if (ev.type === "judge") {
          if (ev.error) { $t("[data-verify]").insertAdjacentHTML("beforeend", html`<div class="warnbox small">LLM 판정 실패: ${ev.error}</div>`); continue; }
          const spans = turn.querySelectorAll(".sent");
          ev.judgements.forEach((j, i) => { if (j && spans[i]) spans[i].insertAdjacentHTML("beforeend", html` <span class="badge ${j.supported ? "ok" : "err"}" title="${j.reason}">LLM ${j.supported ? "✓" : "✗"}</span>`); });
          $t("[data-verify]").insertAdjacentHTML("beforeend", html`<div class="small muted">LLM 판정: 뒷받침 ${ev.supported_ratio == null ? "-" : Math.round(ev.supported_ratio * 100) + "%"} (${ev.seconds}s, 작은 모델의 판정은 참고용)</div>`);
        } else if (ev.type === "done") {
          const u = ev.usage || {};
          $t("[data-status]").remove();
          $t("[data-meta]").textContent = `검색 ${ev.timings.search_ms}ms · 답변 ${ev.timings.llm_s}s${ev.timings.ttft_s != null ? ` (근거 읽기 ${ev.timings.ttft_s}s` + (ev.tokens_per_second ? ` · 생성 ${ev.tokens_per_second} 토큰/초)` : ")") : ""}${ev.timings.judge_s ? ` · 판정 ${ev.timings.judge_s}s` : ""} · 토큰 ${u.input_tokens ?? "-"}→${u.output_tokens ?? "-"}${u.truncated ? " · 길이 한도에서 잘림" : ""}`;
        } else if (ev.type === "error") {
          $t("[data-status]")?.remove();
          $t("[data-answer]").insertAdjacentHTML("beforeend", html`<div class="errbox">${ev.message}</div>`);
        }
      }
    }
    if (!verify && text) $t("[data-answer]").innerHTML = renderAnswer(text, turnId, sources.length);
  } catch (e) {
    $t("[data-status]")?.remove();
    $t("[data-answer]").innerHTML = html`<div class="errbox">${e.message}</div>`;
  } finally { $("#a-send").disabled = false; }
}
$("#a-send").onclick = send;

function currentConfig() {
  const bm25 = $("#a-mode").value === "bm25";
  return { mode: $("#a-mode").value, index_id: bm25 ? null : +$("#a-idx").value || null, chunk_set_id: bm25 ? +$("#a-cs").value || null : null, reranker_id: +$("#a-rr").value || null };
}
$("#e-run").onclick = async e => {
  if (!$("#e-set").value) return toast("평가 세트가 없습니다", "err");
  const body = { config: currentConfig(), max_queries: +$("#e-n").value || null, context_top: +$("#a-top").value, provider: $("#a-provider").value || null, model: $("#a-model").value.trim() || null };
  const job = await busy(e.target, () => api(`/api/eval-sets/${$("#e-set").value}/answer-eval`, { method: "POST", body }));
  const box = $("#e-progress"); box.hidden = false; e.target.disabled = true;
  try {
    const done = await pollJob(job.id, j => { box.innerHTML = ui.jobProgress(j); }, 1500);
    if (done.status !== "done") { ui.error(box, done.status === "cancelled" ? "취소했습니다." : (done.error || done.status)); return; }
    box.hidden = true; renderEval(done.result);
  } finally { e.target.disabled = false; }
};
function renderEval(r) {
  const s = r.summary, p = v => (v == null ? "-" : Math.round(v * 100) + "%");
  const stat = (label, v, sub) => html`<div class="stat"><div class="label">${label}</div><div class="value">${v}</div><div class="small muted">${sub}</div></div>`;
  const yes = v => (v == null ? "-" : v ? html`<span class="badge ok">예</span>` : html`<span class="badge err">아니오</span>`);
  $("#e-out").innerHTML = html`<div class="small muted">${r.llm.model} · 질문 ${s.n}개 · ${r.seconds}s · run #${r.run_id}</div>
    <div class="grid cols-4">
      ${stat("답변률", p(s.answer_rate), "'찾을 수 없음'이 아닌 답 (답 있는 질문)")}
      ${s.n_unanswerable ? stat("답 없음 거절", p(s.correct_refusal), `답 없는 질문 ${s.n_unanswerable}개 중 '찾을 수 없다'고 한 비율 — 낮으면 지어냄`) : ""}
      ${stat("근거 검색률", p(s.evidence_retrieved), "근거 문장 청크가 LLM 에 전달됨")}
      ${stat("정답 근거 인용률", p(s.evidence_cited), `검색됐을 때 인용 ${p(s.cited_given_retrieved)}`)}
      ${stat("문장 근거율", p(s.sentence_support), `잘못된 인용 ${p(s.invalid_citation_rate)} · 지나친 거절 ${p(s.false_refusal)}`)}
      ${s.relevant_ratio != null ? stat("질문 관련 문장", p(s.relevant_ratio), `관련 없는 문장이 섞인 답 ${p(s.off_topic_rate)}`) : ""}
    </div>
    <div class="table-wrap scroll-lg"><table><tr><th>질문</th><th>답변</th><th>근거 검색</th><th>근거 인용</th><th class="num">문장 근거</th><th class="num">시간</th></tr>
    ${html.join(r.rows.map(x => html`<tr><td class="small">${x.query}</td><td class="small">${x.answer}${x.invalid_citations.length ? html` <span class="badge err">없는 번호 ${html.join(x.invalid_citations, ",")}</span>` : ""}</td>
      <td>${yes(x.evidence_retrieved)}</td><td>${yes(x.evidence_cited)}</td><td class="num">${p(x.supported_ratio)}</td><td class="num small">${x.seconds}s</td></tr>`), "")}</table></div>`;
}
$("#a-q").addEventListener("keydown", e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(); });
loadCols(); loadLlm();
