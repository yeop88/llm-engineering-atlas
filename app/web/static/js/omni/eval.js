// omni/eval.html 화면 스크립트 — 채널별 응답 형식 미리 보기(OM7), 채널 바꿈 시나리오 평가(OM8)
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(0)}%`);

$("#f-run").onclick = e => busy(e.target, () => api("/api/omni/render", { method: "POST", body: { text: $("#f-text").value,
  channels: ["web_chat", "messenger", "sms", "email", "voice"] } })).then(r => {
  $("#f-out").innerHTML = html`<div class="table-wrap"><table><tr><th>채널</th><th>보내는 글</th><th>버튼</th><th>글자</th><th>가림</th><th>규칙 위반</th></tr>
    ${html.join(r.results.map(x => html`<tr><td class="nowrap">${x.label}</td><td><div class="pre small m-0">${x.text}</div>${x.spoken ? html`<div class="small"><b>읽는 글</b> ${x.spoken}</div>` : ""}</td>
      <td class="small">${x.buttons.join(" | ") || "-"}</td><td>${x.chars}${x.truncated ? html` <span class="badge warn">줄임</span>` : ""}</td>
      <td class="small">${Object.entries(x.masked).map(([k, v]) => `${k} ${v}`).join(", ") || "-"}</td>
      <td>${x.violations.length ? html`<span class="badge err">${x.violations.join(", ")}</span>` : html`<span class="badge ok">통과</span>`}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#f-out"), err));

api("/api/omni/scenarios").then(r => {
  $("#e-scenarios").innerHTML = html`${r.scenarios.map(s => html`<label class="row small m-0"><input type="checkbox" value="${s.id}" checked> ${s.title} <span class="muted">(${s.channels.join(" → ")} · ${s.steps}걸음)</span></label>`)}`;
}).catch(err => ui.error($("#e-scenarios"), err));

$("#e-run").onclick = e => runJobInto(e.target, "/api/omni/eval", { collection_id: +$("#e-col").value || null, provider: $("#e-provider").value || null,
  model: $("#e-model").value.trim() || null, scenarios: [...document.querySelectorAll("#e-scenarios input:checked")].map(x => x.value) }, $("#e-progress"), r => {
  const s = r.summary;
  $("#e-out").innerHTML = html`<div class="small muted">${r.model} · 시나리오 ${r.scenarios}개 · ${s.steps}걸음 · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>답에 필요한 표기</th><th>넘김 요약에 사실</th><th>채널 바꿔도 같은 세션</th><th>재전송 한 번만</th><th>형식 준수</th><th>지연 예산 안</th><th>채널 간 일관성</th></tr>
      <tr><td><b>${pct(s.expect)}</b></td><td>${pct(s.carry)}</td><td>${pct(s.same_session)}</td><td>${pct(s.dedup)}</td><td>${pct(s.format_ok)}</td><td>${pct(s.in_budget)}</td><td>${pct(s.consistency)}</td></tr></table></div>
    <div class="table-wrap"><table><tr><th>채널</th><th>걸음</th><th>지연 중앙값(ms)</th><th>최대(ms)</th><th>예산 안</th><th>형식 준수</th></tr>
      ${html.join(Object.entries(r.by_channel).map(([k, c]) => html`<tr><td>${k}</td><td>${c.n}</td><td>${c.p50_ms}</td><td>${c.max_ms}</td><td>${pct(c.in_budget)}</td><td>${pct(c.format_ok)}</td></tr>`), "")}</table></div>
    <details><summary>걸음별</summary><div class="table-wrap"><table><tr><th>시나리오</th><th>채널</th><th>말</th><th>표기</th><th>넘김</th><th>중복</th><th>ms</th><th>형식</th><th>답</th></tr>
      ${html.join(r.rows.map(x => html`<tr><td class="small">${x.scenario}</td><td>${x.channel}${x.switched ? html` <span class="badge">바꿈</span>` : ""}</td><td class="small">${x.text}</td>
        <td>${x.expect_of ? `${x.expect_hit}/${x.expect_of}` : "-"}</td><td>${x.carry ? `${x.carry.carried}/${x.carry.of}` : "-"}</td><td>${x.dup_ok == null ? "-" : x.dup_ok ? "✓" : "✗"}</td>
        <td>${x.ms}</td><td class="small">${x.violations.join(", ") || "✓"}</td><td class="small">${x.reply}</td></tr>`), "")}</table></div></details>`;
}).catch(err => ui.error($("#e-out"), err));

setupCollectionPickers({ col: $("#e-col") }).catch(e => ui.error($("#e-out"), e));
