// duplex/timing.html 화면 스크립트 — 대화 하나 보기(FD4 · FD7), 정책 평가(FD4~FD7)
const pct = v => (v == null ? "-" : `${Math.round(v * 100)}%`);

$("#p-run").onclick = e => busy(e.target, () => api("/api/duplex/preview", { method: "POST", body: { seed: +$("#p-seed").value } })).then(r => {
  const ps = Object.keys(r.labels);
  $("#p-out").innerHTML = html`<div class="table-wrap"><table><tr><th>고객 차례(어절 · 끝 ms)</th>${ps.map(p => html`<th>${r.labels[p]}</th>`)}</tr>
    ${html.join(r.turns.map(t => html`<tr><td class="small">${t.words.map(w => `${w.w}(${w.end})`).join(" ")} <span class="muted">끝 ${t.end}</span></td>
      ${ps.map(p => { const x = t.policies[p]; return html`<td class="small">${x.cut_in ? html`<span class="badge err">끊어 먹음</span> ${x.decide}ms` : html`간격 <b>${x.gap}</b>ms`}</td>`; })}</tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#p-out"), err));

$("#e-run").onclick = e => busy(e.target, () => api("/api/duplex/evaluate", { method: "POST", body: { seeds: +$("#e-seeds").value } })).then(r => {
  const s = r.safety, d = r.duplex_stop;
  $("#e-out").innerHTML = html`<div class="small muted">대화 ${r.seeds} · 끝을 안 뒤 첫 소리 준비 ${r.prep_ms}ms(중앙) · ${r.seconds}초 · run #${r.run_id}</div>
    <h3>차례 넘기기</h3>
    <div class="table-wrap"><table><tr><th>정책</th><th>끊어 먹기</th><th>응답 간격 p50</th><th>p95</th></tr>
      ${html.join(r.policies.map(p => html`<tr><td>${p.label}</td><td>${pct(p.cut_in)}</td><td><b>${p.gap_p50}</b>ms</td><td>${p.gap_p95}ms</td></tr>`), "")}</table></div>
    <h3>맞장구 · 안전 끼어들기 · 말하는 중 멈춤</h3>
    <ul class="small">
      ${r.backchannel.map(b => html`<li>맞장구: 이어질 말끝 뒤 ${b.wait_ms}ms 기다림 — 기회 ${b.chances} 중 ${b.placed}번, 고객 말과 겹침 ${pct(b.overlap_rate)}</li>`)}
      <li>안전 끼어들기: 위험한 말 ${s.n}번 — 경고까지 평균 ${s.latency_ms}ms(차례가 끝나기를 기다렸다면 ${s.wait_policy_latency_ms}ms), 차례 끝 전에 ${pct(s.before_turn_end)}</li>
      <li>말하는 중 고객 소리: 길이만 보면 맞장구에 멈춤 ${pct(d.length_only.false_stop)} · 놓친 끼어들기 ${pct(d.length_only.missed_barge)} / 길이 + 인식 글 — ${pct(d.length_text.false_stop)} · ${pct(d.length_text.missed_barge)}</li></ul>`;
}).catch(err => ui.error($("#e-out"), err));
