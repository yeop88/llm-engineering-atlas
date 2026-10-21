// conversation/eval.html 화면 스크립트 — 후속 질문 검색(풀어 쓰기 방법별) · 되묻기 · 메모리 실측과 실행 기록
const M = { none: "그대로", history: "앞 질문 이어 붙이기", rule: "규칙", llm: "LLM" };
const DOM = { as: "AS 매뉴얼", legal: "법률", all: "전체" };
const rate = v => (v == null ? "-" : `${Math.round(v * 100)}%`);  // common.js 의 pct 는 소수 한 자리라 정수 % 로 따로
const checked = name => $$(`input[name="${name}"]:checked`).map(x => x.value);

async function loadPreset() {
  try {
    const p = await api("/api/conversation/eval/preset");
    const n = d => p.dialogs.filter(x => x.domain === d).length;
    $("#e-preset").innerHTML = html`${p.name} — 후속 질문 ${p.dialogs.length}개(AS ${n("as")} · 법률 ${n("legal")}) · 되묻기 ${p.clarify.length}개.
      ${html.join(Object.entries(p.collections).map(([d, c]) => (c.id ? html`${DOM[d]}: <a href="/rag/collections/${c.id}">${c.name}</a>` : html`${DOM[d]}: <span class="badge warn">없음</span> ${c.name}`)), " · ")}`;
  } catch (e) { $("#e-preset").textContent = e.message; }
}

function render(r) {
  const methods = r.methods;
  const doms = Object.keys(r.summary);
  const best = (dom, k) => Math.max(...methods.map(m => r.summary[dom][m][k]));
  const cell = (dom, m, k) => { const v = r.summary[dom][m][k]; return v === best(dom, k) ? html`<b>${rate(v)}</b>` : rate(v); };
  const sum = html`<div class="table-wrap"><table><tr><th>분야</th><th>방법</th><th class="num">Hit@1</th><th class="num">Hit@3</th><th class="num">MRR</th><th class="num">풀어 쓰기 시간</th></tr>
    ${html.join(doms.map(d => html.join(methods.map((m, i) => html`<tr>${i === 0 ? html`<td rowspan="${methods.length}"><b>${DOM[d] || d}</b> <span class="small muted">${r.summary[d].n}문항</span></td>` : ""}
      <td>${M[m]}</td><td class="num">${cell(d, m, "hit@1")}</td><td class="num">${cell(d, m, "hit@3")}</td><td class="num">${(r.summary[d][m].mrr).toFixed(3)}</td><td class="num">${r.summary[d][m].seconds}초</td></tr>`), "")), "")}</table></div>`;
  const rank = x => (x.rank == null ? html`<span class="badge err">밖</span>` : x.rank === 1 ? html`<span class="badge ok">1</span>` : html`<span class="badge warn">${x.rank}</span>`);
  const rows = html`<details><summary class="small">대화별 순위 · 풀어 쓴 질문 (${r.rows.length})</summary><div class="table-wrap scroll-lg"><table>
    <tr><th>대화</th><th>후속 질문</th>${html.join(methods.map(m => html`<th>${M[m]}</th>`), "")}</tr>
    ${html.join(r.rows.map(x => html`<tr><td class="small nowrap">${x.id}${x.depends ? "" : html` <span class="badge" title="앞 대화에 기대지 않는다고 판단">독립</span>`}</td><td class="small">${x.question}</td>
      ${html.join(methods.map(m => html`<td class="small">${rank(x[m])} <span class="muted">${x[m].query === x.question ? "" : x[m].query}</span></td>`), "")}</tr>`), "")}</table></div></details>`;
  const cl = r.clarify ? html`<h3>되묻기 판단 <span class="small muted">정확도 ${rate(r.clarify.accuracy)} · 정밀도 ${rate(r.clarify.precision)} · 재현율 ${rate(r.clarify.recall)}</span></h3>
    <div class="table-wrap"><table><tr><th>질문</th><th>기대</th><th>판단</th></tr>${html.join(r.clarify.rows.map(c => html`<tr><td class="small">${c.question}</td><td>${c.expected ? "되물음" : "답함"}</td>
      <td>${c.ok ? html`<span class="badge ok">${c.ask ? "되물음" : "답함"}</span>` : html`<span class="badge err">${c.ask ? "되물음" : "답함"}</span>`}</td></tr>`), "")}</table></div>` : "";
  const mem = r.memory ? html`<div class="small">메모리(대화 끝의 제품 · 오류 코드가 라벨과 같음): <b>${rate(r.memory.accuracy)}</b> (${r.memory.n}개 대화)</div>` : "";
  $("#e-out").innerHTML = html`${sum}${rows}${cl}${mem}<div class="small muted">${r.run_id ? html`run #${r.run_id} · ` : ""}${r.llm ? html`LLM ${r.llm.model}` : "LLM 없이"} · 정답 = 그 대화의 정답 문서가 처음 나온 순위(문서 단위)</div>`;
}

async function loadRuns() {
  const runs = await api("/api/conversation/eval/runs");
  $("#e-runs").innerHTML = html.or(html`<div class="table-wrap"><table><tr><th>#</th><th>시각</th><th>실행</th><th></th></tr>${html.join(runs.map(r => html`<tr><td class="num">${r.id}</td><td class="small nowrap">${fmtDate(r.created_at)}</td><td class="small">${r.title}</td>
    <td><button class="btn sm" data-run="${r.id}">보기</button></td></tr>`), "")}</table></div>`, "");
  if (!runs.length) ui.empty($("#e-runs"), "아직 실행 기록이 없습니다.");
  $$("[data-run]").forEach(b => { b.onclick = async () => { render(await api(`/api/conversation/eval/runs/${b.dataset.run}`)); $("#retrieval").scrollIntoView({ behavior: "smooth" }); }; });
}

$("#e-run").onclick = e => {
  const methods = checked("e-method"), domains = checked("e-domain");
  if (!methods.length || !domains.length) return toast("방법과 분야를 하나 이상 고르세요", "err");
  const body = { methods, domains, provider: $("#e-provider").value || null, model: $("#e-model").value.trim() || null };
  return runJobInto(e.target, "/api/conversation/eval", body, $("#e-progress"), r => { render(r); loadRuns(); }).catch(() => {});
};

loadPreset();
loadRuns().catch(e => ui.error($("#e-runs"), e));
