// rlvr/train.html 화면 스크립트 — GRPO 학습(RV5), 학습 곡선 · 보상 해킹 경고(RV4)
function curve(c) {
  if (!c?.length) return "";
  const w = Math.max(1, Math.floor(c.length / 10));
  const pts = [];
  for (let i = 0; i < c.length; i += w) {
    const seg = c.slice(i, i + w);
    pts.push({ step: seg.at(-1).step, reward: (seg.reduce((a, x) => a + (x.reward || 0), 0) / seg.length).toFixed(3), correct: (seg.reduce((a, x) => a + (x.correct || 0), 0) / seg.length).toFixed(2),
      chars: Math.round(seg.reduce((a, x) => a + (x.chars || 0), 0) / seg.length) });
  }
  return html`<div class="table-wrap"><table><tr><th>걸음</th><th>평균 보상</th><th>정답률</th><th>길이</th></tr>${html.join(pts.map(p => html`<tr><td>~${p.step}</td><td>${p.reward}</td><td>${p.correct}</td><td>${p.chars}자</td></tr>`), "")}</table></div>`;
}

function hack(h) {
  return h ? (h.ok ? html`<span class="badge ok">해킹 신호 없음</span>` : html`${html.join(h.flags.map(f => html`<div><span class="badge err">해킹 의심</span> ${f}</div>`), "")}`) : "";
}

async function load() {
  const o = await api("/api/rlvr/overview");
  $("#g-tasks").innerHTML = html`${o.tasks.map(t => html`<option>${t.name}</option>`)}`;
  $("#g-list").innerHTML = o.policies.length ? html.join(o.policies.map(p => html`<div class="card stack mt-2"><div class="row"><b>#${p.id} ${p.name}</b> <span class="mono small">${p.endpoint_model}</span>
      <span class="small muted">${p.base} · ${p.metrics.steps ?? "-"}걸음 · 건너뜀 ${p.metrics.skipped ?? 0} · ${p.metrics.seconds ?? "-"}초 · 환경 재생 ${p.metrics.env?.replayed ?? 0}/실제 ${p.metrics.env?.live ?? 0}</span></div>
      <div class="small">${hack(p.metrics.hacking)}</div><details class="small"><summary>학습 곡선</summary>${curve(p.curve)}</details></div>`), "")
    : html`<div class="small muted">학습한 정책이 없습니다.</div>`;
}

$("#g-run").onclick = e => runJobInto(e.target, "/api/rlvr/train", { name: $("#g-name").value.trim(), tasks: $("#g-tasks").value, steps: +$("#g-steps").value || 30,
  group: +$("#g-group").value || 4, beta: +$("#g-beta").value }, $("#g-progress"), r => {
  $("#g-out").innerHTML = html`<div class="small"><b>#${r.model_id}</b> ${r.steps}걸음 · 건너뜀 ${r.skipped} · ${r.seconds}초</div><div class="small">${hack(r.hacking)}</div>${curve(r.curve)}`;
  load();
}).catch(err => toast(err.message, "err"));
load().catch(e => ui.error($("#g-list"), e));
