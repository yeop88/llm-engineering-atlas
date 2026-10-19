// apps/anomaly.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
let aSrc, aModel;
// 정답 범주: 정상 / 기존 유형 / 신종 (판정 상태라서 상태 색 사용, 항상 글자 라벨과 함께)
const CAT = { "정상": ["ok", "#7f9cc7"], "기존 유형": ["warn", "#e0a030"], "신종": ["err", "#d9534f"], "이상": ["err", "#d9534f"] };
const verdictBadge = (v, normal) => html`<span class="badge ${v === normal ? "ok" : v === "신종" ? "err" : "warn"}">${v}</span>`;
const pctf1 = v => (v * 100).toFixed(1) + "%";
$("#a-method").addEventListener("change", e => { $("#a-k").disabled = !["knn", "lof"].includes(e.target.value); });

function histHtml(hist) {
  const cats = [...new Set(hist.flatMap(h => Object.keys(h.by)))];
  const named = cats.some(c => c);
  const mx = Math.max(1, ...hist.map(h => h.n));
  const legend = named ? html`<div class="row small" style="gap:12px">${html.join(cats.map(c => html`<span class="row gap-1 m-0"><span style="width:10px;height:10px;border-radius:2px;background:${(CAT[c] || CAT["정상"])[1]}"></span>${c}</span>`), "")}</div>` : "";
  // legend + 목록을 + 로 이으면 글자열이 되어 넣는 곳에서 다시 이스케이프된다 — html 로 묶는다
  return html`${legend}${hist.map(h => html`<div class="row small nowrap-row gap-2">
    <span class="mono w-md">${h.from.toFixed(2)}${h.to == null ? " 이상" : "–" + h.to.toFixed(2)}</span>
    <div style="flex:1;background:var(--code);border-radius:4px;display:flex;gap:2px;${h.from >= 1 ? "outline:1px dashed var(--border)" : ""}">
      ${html.join(cats.map(c => h.by[c] ? html`<div title="${c || "개수"} ${h.by[c]}" style="height:12px;border-radius:4px;width:${h.by[c] / mx * 100}%;background:${named ? (CAT[c] || CAT["정상"])[1] : "var(--accent)"}"></div>` : ""), "")}
    </div><span class="mono w-xs text-right">${h.n}</span></div>`)}`;
}

$("#a-run").onclick = async e => {
  const test = Apps.parseLines($("#a-test").value).map(({ text, label }) => ({ text, label: label || "" }));
  const r = await Apps.run(e.target, $("#a-progress"), "/api/apps/anomaly", {
    ...aModel(), source: aSrc.get(), test: test.length ? test : null, method: $("#a-method").value, k: +$("#a-k").value,
    quantile: +$("#a-q").value, normal_label: $("#a-normal").value.trim() || "정상", save: $("#a-save").checked, name: $("#a-name").value,
  });
  if (!r) return;
  $("#a-out").innerHTML = r.mode === "explore" ? renderExplore(r) : renderDetect(r);
  if (r.saved) loadSaved();
};

function renderExplore(r) {
  return html`<div class="card stack">
    <div class="row between"><h2>학습 데이터 안의 이상치</h2><span class="small muted">${r.n_items}개 · ${r.seconds}s</span></div>
    <div class="grid cols-3">
      <div class="stat"><div class="label">경계 밖</div><div class="value">${r.n_flagged}</div><div class="small muted">전체의 ${pctf1(r.n_flagged / r.n_items)}</div></div>
      ${r.metrics ? html`<div class="stat"><div class="label">AUC (라벨 기준)</div><div class="value">${r.metrics.auc.toFixed(3)}</div><div class="small muted">1 = 이상을 모두 위로 정렬</div></div>` : ""}
      ${r.metrics && r.metrics.auc < 0.6 ? html`<div class="warnbox" style="grid-column:span 1">라벨 붙은 이상이 여러 개씩 반복되면 그들끼리 뭉쳐서 '외딴 점'으로 보이지 않습니다. 반복되는 이상 유형은 라벨을 붙여 학습하고 검사할 텍스트를 따로 넣으세요.</div>` : ""}
    </div>
    <h3>이상 점수 분포 <span class="small muted">1 = 경계, 점선 칸 = 경계 밖</span></h3>${histHtml(r.hist)}
    <h3>이상 점수 높은 순</h3>
    <table><tr><th class="num">#</th><th>텍스트</th><th>라벨</th><th class="num">이상 점수</th></tr>
    ${html.join(r.outliers.map(o => html`<tr><td class="num">${o.rank}</td><td>${o.text}</td><td class="small">${o.label || ""}</td><td class="num"><span class="${o.anomaly_score > 1 ? "badge err" : "mono"}">${o.anomaly_score.toFixed(2)}</span></td></tr>`), "")}</table>
  </div>`;
}

function renderDetect(r) {
  const m = r.metrics;
  const normal = r.normal_label;
  const stat = (label, value, sub = "", small = false) => html`<div class="stat"><div class="label">${label}</div><div class="value"${small ? html` style="font-size:16px;margin-top:6px"` : ""}>${value}</div>${sub ? html`<div class="small muted">${sub}</div>` : ""}</div>`;
  return html`<div class="card stack">
    <div class="row between"><h2>결과</h2><span class="small muted">학습 ${r.n_items}개 · 검사 ${r.n_test}개 · ${r.seconds}s</span></div>
    ${html.join(r.warnings.map(w => html`<div class="warnbox">${w}</div>`), "")}
    ${r.saved ? html`<div class="warnbox" style="border-color:var(--ok)">탐지기 #${r.saved.id} "${r.saved.name}" 저장됨 — <a href="#t-saved">저장된 탐지기</a>에서 판정하거나 API 로 호출하세요.</div>` : ""}
    <div class="grid cols-4">
      ${stat("판정", html.join(Object.entries(r.counts).map(([k, v]) => html`${k} ${v}`), " · "), "", true)}
      ${m ? stat("판정 정확도", pctf1(m.accuracy), "정상 / 기존 유형 / 신종 3분류") : ""}
      ${m ? stat("이상 탐지 재현율", pctf1(m.anomaly.recall), `정밀도 ${pctf1(m.anomaly.precision)} · 오탐률 ${pctf1(m.false_alarm_rate)}`) : ""}
      ${m && m.novel ? stat("신종 재현율", pctf1(m.novel.recall), `정밀도 ${pctf1(m.novel.precision)}${m.auc != null ? ` · AUC ${m.auc.toFixed(3)}` : ""}`) : ""}
    </div>
    <div class="small muted">학습한 그룹: ${html.join(r.groups.map(g => html`<b>${g.label}</b> ${g.n}개`), " · ")}</div>
    <h3>정상 경계 대비 이상 점수 <span class="small muted">1 = 정상 경계, 점선 칸 = 정상 범위 밖</span></h3>${histHtml(r.hist)}
    ${m ? html`<h3>혼동 행렬 <span class="small muted">행 = 정답, 열 = 판정</span></h3><table><tr><th></th>${html.join(m.confusion.labels.map(l => html`<th class="num">${l}</th>`), "")}</tr>
      ${html.join(m.confusion.matrix.map((row, i) => html`<tr><th>${m.confusion.labels[i]}</th>${html.join(row.map((v, j) => html`<td class="num" style="${v && i === j ? "font-weight:700" : v ? "color:var(--status-critical)" : "color:var(--muted)"}">${v}</td>`), "")}</tr>`), "")}</table>` : ""}
    <h3>항목별 판정</h3>
    <table><tr><th>텍스트</th>${m ? html`<th>정답</th>` : ""}<th>판정</th><th class="num">이상 점수</th><th>가장 비슷한 학습 예시</th></tr>
    ${html.join(r.items.map(it => html`<tr><td>${it.text}</td>${m ? html`<td class="small">${it.gold}</td>` : ""}<td>${verdictBadge(it.verdict, normal)}</td>
      <td class="num mono" title="${html.join(Object.entries(it.boundary).map(([g, v]) => html`${g} 경계 대비 ${v}`), "\n")}">${it.anomaly_score.toFixed(2)}</td>
      <td class="small muted">[${it.nearest.label}] ${it.nearest.text.slice(0, 60)} <span class="mono">${it.nearest.similarity.toFixed(3)}</span></td></tr>`), "")}</table>
  </div>`;
}

// ── 저장된 탐지기 ──
async function loadSaved() {
  const rows = await api("/api/apps/models?kind=anomaly");
  $("#sv-rows").innerHTML = html.or(html.join(rows.map(m => html`<tr><td>${m.id}</td><td><b>${m.name}</b></td><td class="small">${html.join(m.labels, ", ")}</td>
    <td class="small">${m.method} · <span class="mono">${m.model_hf_id}</span>${m.truncate_dim ? html` · ${m.truncate_dim}d` : ""}</td><td class="num">${m.n_train}</td>
    <td class="num">${m.metrics.accuracy != null ? pctf1(m.metrics.accuracy) : "-"}</td><td class="small nowrap">${fmtDate(m.created_at)}</td>
    <td class="right"><button class="btn sm danger" onclick="delSaved(${m.id})">삭제</button></td></tr>`), ""), html`<tr><td colspan="8" class="empty">저장된 탐지기가 없습니다. 탐지 탭에서 "탐지기로 저장"을 켜고 실행하세요.</td></tr>`);
  $("#sc-model").innerHTML = html.join(rows.map(m => html`<option value="${m.id}">#${m.id} ${m.name}</option>`), "");
  updateApi();
}
function updateApi() {
  const id = $("#sc-model").value || "{id}";
  $("#sc-api").textContent = `curl -X POST ${location.origin}/api/apps/detectors/${id}/score \\\n  -H "Content-Type: application/json" \\\n  -d '{"texts": ["[국제발신] 결제 승인 완료. 본인 아니면 신고 http://..."]}'`;
}
$("#sc-model").addEventListener("change", updateApi);
async function delSaved(id) {
  if (!(await ui.confirm(`탐지기 #${id} 를 삭제할까요?`, { ok: "삭제", danger: true, title: "삭제" }))) return;
  await api(`/api/apps/models/${id}`, { method: "DELETE" }); toast("삭제했습니다", "ok"); loadSaved();
}
$("#sc-run").onclick = async e => {
  if (!$("#sc-model").value) return toast("저장된 탐지기가 없습니다", "err");
  const texts = $("#sc-text").value.split("\n").map(s => s.trim()).filter(Boolean);
  const r = await busy(e.target, () => api(`/api/apps/detectors/${$("#sc-model").value}/score`, { method: "POST", body: { texts } }));
  const normal = r.detector.groups[0];
  $("#sc-out").innerHTML = html`<div class="small muted">${r.seconds}s</div><table><tr><th>텍스트</th><th>판정</th><th class="num">이상 점수</th><th>가장 비슷한 학습 예시</th></tr>
    ${html.join(r.results.map(x => html`<tr><td>${x.text}</td><td>${verdictBadge(x.verdict, normal)}</td><td class="num mono">${x.anomaly_score.toFixed(2)}</td><td class="small muted">[${x.nearest.label}] ${x.nearest.text.slice(0, 60)}</td></tr>`), "")}</table>`;
};

(async () => {
  initTabs();
  aSrc = await Apps.sourcePicker($("#a-src"), { app: "anomaly", labels: "optional", placeholder: "정상 텍스트 한 줄에 하나\n[스미싱] 알려진 이상 유형은 라벨을 붙여서" });
  aSrc.root.addEventListener("preset", e => {
    if (e.detail.test) $("#a-test").value = e.detail.test.map(it => (it.label ? `[${it.label}] ${it.text}` : it.text)).join("\n");
  });
  aModel = await Apps.modelPicker($("#a-model"), $("#a-dim"));
  loadSaved();
})();
