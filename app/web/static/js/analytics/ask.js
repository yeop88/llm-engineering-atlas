// analytics/ask.html 화면 스크립트 — 분석 자료 · 스키마 카드(DA1), 질문 → SQL · 실행 검증 · 고치기 · 해석 · 막대(DA3~DA5)
function resultTable(res) {
  if (!res) return "";
  return html`<div class="small muted">${res.rows.length}행${res.truncated ? " (잘림)" : ""} · ${res.ms}ms</div><div class="table-wrap"><table><tr>${html.join(res.columns.map(c => html`<th>${c}</th>`), "")}</tr>
    ${html.join(res.rows.slice(0, 50).map(r => html`<tr>${html.join(r.map(v => html`<td>${v ?? "NULL"}</td>`), "")}</tr>`), "")}</table></div>`;
}

function chartHtml(c) {
  if (!c) return "";
  return html`<div class="table-wrap"><table><tr><th></th><th>${c.label}</th><th></th></tr>
    ${html.join(c.bars.map(b => html`<tr><td class="small">${b.name}</td><td class="small">${b.value ?? "-"}</td><td><progress value="${b.value ?? 0}" max="${b.max}">${b.value}</progress></td></tr>`), "")}</table></div>`;
}

async function loadSources(pick) {
  const r = await api("/api/analytics/sources");
  $("#a-source").innerHTML = html`${r.sources.map(s => html`<option value="${s.name}">${s.name} (${Object.entries(s.tables).map(([t, n]) => `${t} ${n}`).join(", ")})</option>`)}`;
  if (pick) $("#a-source").value = pick;
  if (r.sources.length) await loadSchema(); else ui.empty($("#a-schema"), "분석 자료가 없습니다 — 위에서 만드세요(예시 AS 자료).");
}

async function loadSchema() {
  const r = await api(`/api/analytics/sources/${$("#a-source").value}/schema`);
  $("#a-schema").innerHTML = html`<div class="muted">${r.description}</div>${html.join(Object.entries(r.cards).map(([t, c]) => html`<details><summary><b>${t}</b> — ${c.desc}</summary><ul>
    ${html.join(c.columns.map(col => html`<li><span class="mono">${col.name}</span> ${col.desc}${col.pii ? html` <span class="badge warn">개인정보 · 분석가에게 막힘</span>` : ""}${col.examples.length ? html` <span class="muted">예: ${col.examples.join(", ")}</span>` : ""}</li>`), "")}</ul></details>`), "")}`;
}

$("#a-build").onclick = e => busy(e.target, () => api("/api/analytics/sources", { method: "POST", body: { name: $("#a-new").value.trim(), kind: $("#a-kind").value } }))
  .then(r => loadSources(r.name)).catch(err => ui.error($("#a-schema"), err));
$("#a-source").onchange = () => loadSchema().catch(err => ui.error($("#a-schema"), err));

$("#a-run").onclick = e => busy(e.target, () => api("/api/analytics/ask", { method: "POST", body: { source: $("#a-source").value, question: $("#a-q").value, mode: $("#a-mode").value,
  role: $("#a-role").value, max_tries: +$("#a-tries").value || 3, full_schema: $("#a-full").checked, provider: $("#a-provider").value || null, model: $("#a-model").value.trim() || null } })).then(r => {
  const ans = r.answer;
  $("#a-out").innerHTML = html`<div class="small muted">${r.mode === "semantic" ? "의미 계층" : "SQL 생성"} · 역할 ${r.role === "admin" ? "관리자" : "분석가"} · 시도 ${r.tries} · ${r.seconds}초 · 연결한 표 ${r.link.tables.join(", ")}</div>
    ${r.plan ? html`<div class="small">계획: <span class="mono">${JSON.stringify(r.plan)}</span></div>` : ""}
    ${html.join(r.attempts.map((a, i) => html`<div class="small"><b>시도 ${i + 1}</b> ${a.error ? html`<span class="badge err">오류</span> ${a.error}` : a.blocked ? html`<span class="badge err">막힘</span> ${a.blocked}`
      : a.issues?.length ? html`<span class="badge warn">점검</span> ${a.issues.join("; ")}` : html`<span class="badge ok">통과</span>`}<pre class="small mono pre m-0">${a.sql}</pre></div>`), "")}
    ${resultTable(r.result)}
    ${ans ? html`<h3>답</h3><div class="pre">${ans.text || ans.error || ""}</div>${ans.check ? (ans.check.ok ? html`<span class="badge ok">숫자가 모두 결과에 있음</span>`
      : html`<span class="badge err">결과에 없는 수: ${ans.check.not_in_result.join(", ")}</span>`) : ""}` : ""}
    ${chartHtml(r.chart)}`;
  $("#a-sql").value = r.sql || "";
}).catch(err => ui.error($("#a-out"), err));

$("#a-exec").onclick = e => busy(e.target, () => api("/api/analytics/run", { method: "POST", body: { source: $("#a-source").value, sql: $("#a-sql").value, role: $("#a-role").value } }))
  .then(r => { $("#a-exec-out").innerHTML = r.ok ? resultTable(r.result) : html`<span class="badge err">${r.attempts[0].error}</span>`; }).catch(err => ui.error($("#a-exec-out"), err));

loadSources().catch(e => ui.error($("#a-schema"), e));
