// edge/pack.html 화면 스크립트 — 기기용 팩 만들기 · 검색 · 평가(ED3), 오프라인 기능 범위 · 기기에서 묻기(ED4)
const STATUS = { ok: ["ok", "기기에서"], defer: ["warn", "연결될 때"], no: ["err", "안 됨"] };
const MODE = { faq: "자주 묻는 답(캐시)", answer: "기기 LLM 답", sources: "근거만", defer: "미룸" };
let INDEXES = [];
const list = s => s.split(",").map(x => x.trim()).filter(Boolean);
const mb = b => `${(b / 2 ** 20).toFixed(2)}MB`;

async function load() {
  const r = await api("/api/edge/packs");
  INDEXES = r.indexes;
  fillIndexes();
  $("#p-list").innerHTML = r.packs.length ? html`<div class="table-wrap"><table><tr><th>팩</th><th>판</th><th>모델</th><th>정밀도</th><th>문서 · 청크</th><th>크기</th><th>범위</th><th></th></tr>
    ${html.join(r.packs.map(p => html`<tr><td class="mono small">${p.name}</td><td>v${p.latest} <span class="small muted">(${p.versions.length}판)</span></td><td class="small mono">${p.model}</td>
      <td>${p.precision}</td><td>${p.n_docs} · ${p.n_chunks}</td><td>${mb(p.bytes)}</td><td class="small">${JSON.stringify(p.scope)}</td>
      <td><button class="btn sm danger" data-del="${p.name}">삭제</button></td></tr>`), "")}</table></div>` : html`<p class="small muted">아직 팩이 없습니다.</p>`;
  $$("[data-pack]").forEach(sel => { const v = sel.value; sel.innerHTML = html`${r.packs.map(p => html`<option>${p.name}</option>`)}`; if (v) sel.value = v; });
  $$("[data-del]").forEach(b => b.onclick = async () => {
    if (!(await ui.confirm(`팩 ${b.dataset.del} 의 모든 판을 지울까요?`))) return;
    api(`/api/edge/packs/${b.dataset.del}`, { method: "DELETE" }).then(load).catch(err => toast(err.message, "err"));
  });
}

function fillIndexes() {
  const rows = INDEXES.filter(i => i.collection_id === +$("#p-col").value);
  $("#p-idx").innerHTML = html`${rows.map(i => html`<option value="${i.id}">#${i.id} · ${i.model} · ${i.dim}차원 · ${i.n_vectors}개</option>`)}`;
}

function renderPack(m) {
  $("#p-out").innerHTML = html`<div class="small"><b>${m.name} v${m.version}</b> · 문서 ${m.n_docs} · 청크 ${m.n_chunks} · ${mb(m.bytes)} (청크당 벡터 ${m.bytes_per_chunk}B) ·
    새로 인코딩 ${m.encoded} · 앞 판에서 가져옴 ${m.reused} · 자주 묻는 답 ${m.n_cache} · 지문 <span class="mono">${m.hash}</span></div>`;
  load();
}

$("#p-build").onclick = e => runJobInto(e.target, "/api/edge/packs", { name: $("#p-name").value.trim(), index_id: +$("#p-idx").value, precision: $("#p-prec").value,
  product_model: list($("#p-pm").value), doc_type: list($("#p-dt").value), since_days: +$("#p-days").value || null, include_cache: $("#p-cache").checked }, $("#p-progress"), renderPack)
  .catch(err => ui.error($("#p-out"), err));

$("#q-run").onclick = e => busy(e.target, () => api(`/api/edge/packs/${$("#q-pack").value}/search`, { method: "POST", body: { query: $("#q-text").value, k: 5 } }))
  .then(r => { $("#q-out").innerHTML = html`<div class="small muted">검색 ${r.search_ms}ms · 질의 인코딩 ${r.encode_ms}ms${r.cache ? html` · <span class="badge ok">자주 묻는 답 ${r.cache.similarity}</span> ${r.cache.question}` : ""}</div>
    <ol class="small">${html.join(r.results.map(x => html`<li><b>${x.score}</b> ${x.filename}${x.heading ? ` · ${x.heading}` : ""} — ${x.text.slice(0, 140)}</li>`), "")}</ol>`; })
  .catch(err => ui.error($("#q-out"), err));

$("#e-run").onclick = e => runJobInto(e.target, `/api/edge/packs/${$("#q-pack").value}/eval`, { eval_set_id: +$("#e-set").value, k: +$("#e-k").value || 5, max_queries: +$("#e-n").value || 100 },
  $("#e-progress"), r => {
    $("#e-out").innerHTML = html`<div class="small muted">${r.pack.name} v${r.pack.version} · ${r.pack.precision} · ${r.eval_set.name} · run #${r.run_id}</div>
      <div class="table-wrap"><table><tr><th></th><th>질문</th><th>팩 hit@${r.k}</th><th>서버 hit@${r.k}</th></tr>
      <tr><td>전체</td><td>${r.n}</td><td><b>${r.pack_hit}</b></td><td>${r.server_hit ?? "-"}</td></tr>
      <tr><td>정답이 팩 범위 안</td><td>${r.n_in_scope}</td><td><b>${r.in_scope.pack_hit ?? "-"}</b></td><td>${r.in_scope.server_hit ?? "-"}</td></tr></table></div>
      <p class="small muted">범위 안 차이 = 압축 · 청크 손실, 전체와 범위 안의 차이 = 안 담아서 못 찾은 몫. 팩 검색 ${r.search_ms}ms/질문.</p>`;
  }).catch(err => ui.error($("#e-out"), err));

$("#o-cap").onclick = e => busy(e.target, () => api(`/api/edge/capabilities?pack=${encodeURIComponent($("#o-pack").value)}&profile=${$("#o-profile").value}&llm_file=${encodeURIComponent($("#o-file").value)}`))
  .then(r => { $("#o-cap-out").innerHTML = html`<div class="table-wrap"><table><tr><th>기능</th><th>필요</th><th>상태</th><th>이유</th></tr>
    ${html.join(r.features.map(f => html`<tr><td>${f.label}</td><td class="small">${f.needs}</td><td><span class="badge ${STATUS[f.status][0]}">${STATUS[f.status][1]}</span></td><td class="small">${f.reason}</td></tr>`), "")}</table></div>`; })
  .catch(err => ui.error($("#o-cap-out"), err));

$("#o-ask").onclick = e => busy(e.target, () => api("/api/edge/ask", { method: "POST", body: { pack: $("#o-pack").value, question: $("#o-q").value, provider: $("#o-provider").value || null,
  model: $("#o-model").value.trim() || null, device_id: $("#o-device").value.trim() || null, online: $("#o-online").checked } }))
  .then(r => {
    const srcs = html`<ol class="small">${html.join((r.sources || []).slice(0, 4).map(x => html`<li>${x.score != null ? html`<b>${x.score}</b> ` : ""}${x.filename || x.title || ""} — ${(x.text || "").slice(0, 120)}</li>`), "")}</ol>`;
    $("#o-out").innerHTML = html`<div class="row small"><span class="badge ${r.mode === "defer" ? "warn" : "ok"}">${MODE[r.mode]}</span> 팩 v${r.pack_version} · ${r.seconds}초
      ${r.queued ? html`<span class="badge">대기열 #${r.queued}</span>` : ""}${r.llm_error ? html`<span class="badge err">LLM 오류</span>` : ""}</div>
      ${r.reason ? html`<p class="small">${r.reason}</p>` : ""}${r.answer ? html`<div class="pre">${r.answer}</div>` : ""}
      ${r.verify ? html`<div class="small muted">근거 일치 ${r.verify.supported_ratio ?? "-"}</div>` : ""}
      ${r.server ? html`<h3>서버 답</h3><div class="pre">${r.server.answer || r.server.error || ""}</div>` : ""}${srcs}`;
  }).catch(err => ui.error($("#o-out"), err));

(async () => {
  const pr = await api("/api/edge/profiles");
  $("#p-prec").innerHTML = html`${pr.precisions.map(p => html`<option ${p === "binary_rescore" ? "selected" : ""}>${p}</option>`)}`;
  $("#o-profile").innerHTML = html`${Object.entries(pr.profiles).map(([k, p]) => html`<option value="${k}" ${k === "tablet" ? "selected" : ""}>${p.label}</option>`)}`;
  const ov = await api("/api/edge/overview");
  $("#o-file").insertAdjacentHTML("beforeend", html`${ov.files.map(f => html`<option>${f}</option>`)}`);
  await setupCollectionPickers({ col: $("#p-col"), set: $("#e-set") });
  $("#p-col").addEventListener("change", fillIndexes);
  await load();
})().catch(e => ui.error($("#p-list"), e));
