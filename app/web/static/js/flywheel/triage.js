// flywheel/triage.html 화면 스크립트 — 서비스 로그 개요(FW1), 실패 유형 · 날짜별 추이(FW2), 처방(FW5)
let chart = null;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

function trend(r) {
  const keys = Object.keys(r.trend.series);
  const label = k => r.categories.find(c => c.key === k)?.label || k;
  $("#f-trend-table").innerHTML = keys.length ? html`<details class="small"><summary>표로 보기</summary><div class="table-wrap"><table><tr><th>날짜</th><th>요청</th>${html.join(keys.map(k => html`<th>${label(k)}</th>`), "")}</tr>
    ${html.join(r.trend.days.map((d, i) => html`<tr><td>${d}</td><td>${r.trend.total[i]}</td>${html.join(keys.map(k => html`<td>${r.trend.series[k][i]}</td>`), "")}</tr>`), "")}</table></div></details>` : "";
  $("#f-trend-box").hidden = !keys.length || typeof Chart === "undefined";
  if (chart) { chart.destroy(); chart = null; }
  if (!keys.length || typeof Chart === "undefined") return;
  // 계열 색은 정해진 순서(--series-1…)로 — 필터로 계열 수가 바뀌어도 유형마다 같은 색이 되게 유형 목록의 순서를 쓴다
  const order = r.categories.map(c => c.key);
  chart = new Chart($("#f-trend"), {
    type: "line",
    data: { labels: r.trend.days, datasets: keys.map(k => ({ label: label(k), data: r.trend.series[k], borderColor: css(`--series-${order.indexOf(k) + 1}`), backgroundColor: css(`--series-${order.indexOf(k) + 1}`), borderWidth: 2, pointRadius: 3, tension: 0 })) },
    options: { plugins: { legend: { labels: { color: css("--text") } } }, scales: { x: { ticks: { color: css("--muted") }, grid: { display: false } }, y: { beginAtZero: true, ticks: { color: css("--muted"), precision: 0 }, grid: { color: css("--border") } } } },
  });
}

async function load() {
  const q = new URLSearchParams({ days: $("#f-days").value || 30 });
  if ($("#f-col").value) q.set("collection_id", $("#f-col").value);
  const r = await api(`/api/flywheel/triage?${q}`);
  $("#f-logs").innerHTML = html`요청 ${fmtNum(r.n)}건 · 실패로 분류 ${fmtNum(r.failed)}건(${r.fail_rate == null ? "-" : pct(r.fail_rate) + "%"}) · ${html.join(Object.entries(r.kinds).map(([k, v]) => html`<span class="badge">${k} ${v}</span>`), " ")}
    · 보관 ${r.retention_days ? `${r.retention_days}일` : html`<span class="badge warn">기한 없음(TRACE_RETENTION_DAYS=0)</span>`}`;
  $("#f-cats").innerHTML = html`<div class="table-wrap"><table><tr><th>유형</th><th>건수</th><th>고칠 곳</th><th>예</th></tr>
    ${html.join(r.categories.map(c => html`<tr><td class="small"><b>${c.label}</b></td><td>${c.n}</td><td class="small">${c.fix}</td>
      <td class="small">${c.examples.length ? html`<details><summary>${c.examples.length}개</summary><ul>${html.join(c.examples.map(e => html`<li><a href="/compliance/records?trace=${e.id}">#${e.id}</a> ${e.question}</li>`), "")}</ul></details>` : ""}</td></tr>`), "")}</table></div>`;
  $("#f-rx").innerHTML = r.prescriptions.length ? html`<ol class="small">${html.join(r.prescriptions.map(p => html`<li><span class="badge">${p.tier}</span> <b>${p.label}</b> ${p.n}건 — <a href="${p.href}">${p.what}</a></li>`), "")}</ol>`
    : html`<div class="small muted">실패로 분류된 요청이 없습니다.</div>`;
  trend(r);
}

(async () => {
  const cols = await api("/api/collections");
  $("#f-col").innerHTML = html`<option value="">모두</option>${cols.map(c => html`<option value="${c.id}">${c.name}</option>`)}`;
  await load();
})().catch(e => ui.error($("#f-cats"), e));
$("#f-load").onclick = e => busy(e.target, load).catch(err => ui.error($("#f-cats"), err));
