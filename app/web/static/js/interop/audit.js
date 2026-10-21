// interop/audit.html 화면 스크립트 — 호출 · 비용 상한과 세션 사용량(IO5), 추적 id 로 이은 호출 · 위임(IO6), 호출 기록
const STATUS = { ok: ["ok", "성공"], denied: ["err", "권한 거절"], limit: ["warn", "상한"], error: ["err", "오류"] };
const CH = { mcp: "MCP", mcp_remote: "외부 MCP", sandbox: "샌드박스", a2a_in: "A2A 받음", a2a_out: "A2A 맡김" };

function rows(calls) {
  return html`<div class="table-wrap scroll-lg"><table><tr><th>#</th><th>때</th><th>통로</th><th>대상</th><th>부른 쪽</th><th>결과</th><th>입력 · 결과</th></tr>
    ${html.join(calls.map(c => html`<tr><td class="small">${c.id}</td><td class="small nowrap">${c.at.slice(11, 19)}</td><td class="small">${CH[c.channel] || c.channel}</td>
      <td class="small mono">${c.target} <span class="badge">${c.scope}</span></td><td class="small">${c.client}</td>
      <td class="small"><span class="badge ${(STATUS[c.status] || ["", ""])[0]}">${(STATUS[c.status] || ["", c.status])[1]}</span>${c.untrusted ? html` <span class="badge" title="신뢰 경계 밖에서 온 결과">외부 결과</span>` : ""}
        ${c.flags.length ? html` <span class="badge err" title="${c.flags.map(f => f.removed).join(" / ")}">지시 문장 ${c.flags.length}</span>` : ""} <span class="muted">${Math.round(c.ms)}ms</span>
        ${c.trace_key ? html`<div><a href="#" class="mono" data-key="${c.trace_key}">${c.trace_key}</a></div>` : ""}</td>
      <td class="small"><details><summary>보기</summary><pre class="pre small">${JSON.stringify({ args: c.args, result: c.result }, null, 1)}</pre></details></td></tr>`), "")}</table></div>`;
}
function bindKeys(box) { $$("[data-key]", box).forEach(a => a.onclick = ev => { ev.preventDefault(); openTrace(a.dataset.key); }); }

async function openTrace(key) {
  $("#u-key").value = key;
  const t = await api(`/api/interop/trace/${encodeURIComponent(key)}`);
  $("#u-trace").innerHTML = html`<div class="small">호출 ${t.calls.length} · 위임 작업 ${t.tasks.length} · 외부 결과 ${t.untrusted}</div>
    ${t.tasks.length ? html`<ul class="small">${html.join(t.tasks.map(x => html`<li><span class="mono">${x.id}</span> ${x.direction === "out" ? "맡김 →" : "받음 ←"} ${x.peer} · ${x.skill} · ${x.status}</li>`), "")}</ul>` : ""}
    ${t.calls.length ? rows(t.calls) : ""}`;
  bindKeys($("#u-trace"));
}

async function loadCalls() {
  const q = new URLSearchParams();
  if ($("#u-channel").value) q.set("channel", $("#u-channel").value);
  if ($("#u-status").value) q.set("status", $("#u-status").value);
  const calls = await api(`/api/interop/calls?${q}`);
  $("#u-calls").innerHTML = calls.length ? rows(calls) : html`<div class="small muted">기록이 없습니다.</div>`;
  bindKeys($("#u-calls"));
}

async function loadLimits() {
  const l = await api("/api/interop/limits");
  const d = l.default;
  const ss = Object.entries(l.sessions);
  $("#u-limits").innerHTML = html`세션 · 위임 하나에 호출 <b>${d.max_calls}</b>회 · 시간 <b>${d.max_seconds}</b>초 · 비용 <b>${d.max_cost ? `$${d.max_cost}` : "상한 없음"}</b>
    <span class="muted">(INTEROP_MAX_CALLS · INTEROP_MAX_SECONDS · INTEROP_MAX_COST)</span>
    ${ss.length ? html`<div class="table-wrap"><table><tr><th>세션</th><th>호출</th><th>경과</th></tr>${html.join(ss.map(([k, b]) => html`<tr><td class="small mono">${k.slice(0, 16)}</td>
      <td class="small">${b.calls}/${b.max_calls}</td><td class="small">${b.seconds}/${b.max_seconds}초</td></tr>`), "")}</table></div>` : html`<div class="muted">지금 열린 세션 없음</div>`}`;
}

$("#u-open").onclick = () => { if ($("#u-key").value.trim()) openTrace($("#u-key").value.trim()).catch(e => ui.error($("#u-trace"), e)); };
["#u-channel", "#u-status"].forEach(s => $(s).addEventListener("change", () => loadCalls().catch(e => ui.error($("#u-calls"), e))));
loadLimits().catch(e => ui.error($("#u-limits"), e));
loadCalls().catch(e => ui.error($("#u-calls"), e));
const want = new URLSearchParams(location.search).get("trace");
if (want) openTrace(want).catch(e => ui.error($("#u-trace"), e));
