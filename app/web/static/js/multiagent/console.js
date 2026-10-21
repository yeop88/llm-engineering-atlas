// multiagent/console.html 화면 스크립트 — 오케스트레이터 실행(MA3), 에이전트 흐름(MA4~MA7), 글 · 차트 · 그림 · 음성 출력(MA8)
const AGENT = { orchestrator: "오케스트레이터", retrieval: "검색 전문가", analysis: "분석 · 코딩", writer: "작성", critic: "품질 검증", output: "출력" };
const DEC = { pass: ["ok", "통과"], revise: ["warn", "수정 요청"], reject: ["err", "반려"] };
let chart = null;

function eventHtml(e) {
  const head = html`<span class="mono muted">${e.t}s</span> <b>${AGENT[e.agent] || e.agent}</b>`;
  if (e.kind === "plan") return html`<li>${head} 계획: ${e.tasks.map(t => AGENT[t.agent]).join(" → ")}</li>`;
  if (e.agent === "retrieval") return html`<li>${head} 근거 ${e.n}개 ${e.enough ? html`<span class="badge ok">충분</span>` : html`<span class="badge warn">부족</span>`}
    <ol class="small">${html.join(e.rounds.map(r => html`<li>질의 '${r.query}' → ${r.found}개 · 덮음 ${r.coverage} (${r.by})${r.missing ? ` · 부족: ${r.missing}` : ""}</li>`), "")}</ol>
    ${e.vision?.length ? html`<div class="small muted">그림 점수 ${e.vision.join(", ")}</div>` : ""}</li>`;
  if (e.agent === "analysis") return html`<li>${head} ${e.ok ? html`<span class="badge ok">계산함</span> <span class="small">${JSON.stringify(e.result)}</span>` : html`<span class="badge warn">계산 못 함</span>`}
    ${html.join((e.attempts || []).map((a, i) => html`<details class="small"><summary>코드 ${i + 1} · ${a.isolation} · 종료 ${a.exit_code ?? "-"}</summary><pre class="pre small">${a.code}</pre>${a.stderr ? html`<pre class="pre small muted">${a.stderr}</pre>` : ""}</details>`), "")}</li>`;
  if (e.agent === "writer") return html`<li>${head} ${e.kind === "revision" ? `다시 씀 ${e.n}` : "초안"} <span class="badge">${e.level === "easy" ? "쉬움" : "어려움"} · ${e.model}</span>${e.why ? html` <span class="small muted">${e.why}</span>` : ""}
    <details class="small"><summary>글</summary><div class="pre small">${e.text}</div></details></li>`;
  if (e.agent === "critic") return html`<li>${head} <span class="badge ${(DEC[e.kind] || [""])[0]}">${(DEC[e.kind] || ["", e.kind])[1]}</span> <span class="small">근거 일치 ${e.supported ?? "-"}</span>
    ${e.issues?.length ? html`<ul class="small">${html.join(e.issues.map(i => html`<li>${i}</li>`), "")}</ul>` : ""}</li>`;
  return html`<li>${head} 차트 ${e.chart ? "있음" : "없음"} · 그림 ${e.images} · 음성 ${e.audio ? "있음" : "없음"}</li>`;
}

function drawChart(c) {
  $("#m-chart-table").innerHTML = c ? html`<details class="small"><summary>표로 보기 — ${c.title || "분석 결과"}</summary><table><tr><th>항목</th><th>값</th></tr>
    ${html.join(c.labels.map((l, i) => html`<tr><td>${l}</td><td>${c.values[i]}</td></tr>`), "")}</table></details>` : "";
  $("#m-chart-box").hidden = !c || typeof Chart === "undefined";
  if (chart) { chart.destroy(); chart = null; }
  if (!c || typeof Chart === "undefined") return;
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  chart = new Chart($("#m-chart"), {
    type: c.type === "line" ? "line" : "bar",
    data: { labels: c.labels, datasets: [{ label: c.title || "값", data: c.values, backgroundColor: css("--series-1"), borderColor: css("--series-1"), borderWidth: 2, borderRadius: 4 }] },
    options: { plugins: { legend: { display: false }, title: { display: !!c.title, text: c.title, color: css("--text") } },
      scales: { x: { ticks: { color: css("--muted") }, grid: { display: false } }, y: { ticks: { color: css("--muted") }, grid: { color: css("--border") } } } },
  });
}

function render(r) {
  $("#m-events").innerHTML = html`<ol class="stack m-0">${html.join(r.events.map(eventHtml), "")}</ol>
    <div class="small muted">${r.seconds}초 · 토큰 ${fmtNum(r.usage.input_tokens + r.usage.output_tokens)} · 재작성 ${r.revisions}${r.run_id ? ` · run #${r.run_id}` : ""}</div>`;
  const o = r.output;
  $("#m-out").innerHTML = html`<div class="row"><span class="badge ${(DEC[r.decision] || [""])[0]}">${(DEC[r.decision] || ["", r.decision])[1]}</span> <span class="small muted">근거 일치 ${r.verify.supported_ratio ?? "-"}</span></div>
    <div class="pre">${o.text}</div>${ui.aiNotice(r.notice, r.trace_id)}
    ${o.images.length ? html`<div class="thumbs">${html.join(o.images.map(im => html`<figure><img src="${im.url}" alt="근거 그림 ${im.n} ${im.filename || ""}"><figcaption class="small muted">[${im.n}] ${im.filename || ""}</figcaption></figure>`), "")}</div>` : ""}
    ${o.audio?.url ? html`<audio controls src="${o.audio.url}"></audio>` : o.audio?.error ? html`<div class="small muted">${o.audio.error}</div>` : !o.tts_available ? html`<div class="small muted">음성: TTS_URL 이 없어 끔</div>` : ""}
    <details class="small"><summary>근거 ${r.sources.length}</summary><ol>${html.join(r.sources.map(s => html`<li><b>${s.filename}</b> <span class="muted">${s.round ? `${s.round}회차 '${s.query}'` : ""}</span><div class="muted">${(s.text || "").slice(0, 200)}</div></li>`), "")}</ol></details>`;
  drawChart(o.chart);
}

async function loadRuns() {
  const rows = await api("/api/multiagent/runs");
  $("#m-runs").innerHTML = rows.length ? html`<div class="table-wrap"><table><tr><th>#</th><th>질문</th><th>결정</th><th>재작성</th><th>시간</th></tr>
    ${html.join(rows.map(r => html`<tr><td><a href="#" data-run="${r.id}">${r.id}</a></td><td class="small">${r.title}</td><td><span class="badge ${(DEC[r.decision] || [""])[0]}">${(DEC[r.decision] || ["", r.decision])[1]}</span></td>
      <td class="small">${r.revisions}</td><td class="small">${r.seconds}초</td></tr>`), "")}</table></div>` : html`<div class="small muted">기록이 없습니다.</div>`;
  $$("[data-run]", $("#m-runs")).forEach(a => a.onclick = ev => { ev.preventDefault(); api(`/api/multiagent/runs/${a.dataset.run}`).then(render).catch(e => toast(e.message, "err")); });
}

$("#m-run").onclick = e => {
  if (!$("#m-q").value.trim()) return toast("질문을 입력하세요", "err");
  const c = Ctx.get();
  runJobInto(e.target, "/api/multiagent/run", { collection_id: +$("#m-col").value, question: $("#m-q").value.trim(), analyze: $("#m-analyze").value,
    rounds: +$("#m-rounds").value || 3, revisions: +$("#m-rev").value, vision: $("#m-vision").checked, tts: $("#m-tts").checked, provider: c.provider || null, model: c.model || null },
    $("#m-progress"), r => { render(r); loadRuns(); }).catch(err => toast(err.message, "err"));
};

setupCollectionPickers({ col: $("#m-col") }).catch(() => {});
loadRuns().catch(e => ui.error($("#m-runs"), e));
