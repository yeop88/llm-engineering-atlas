// interop/tools.html 화면 스크립트 — 이 앱의 MCP 도구 목록 · 호출(IO1), 권한 표 · 샌드박스 실행(IO2), 다른 MCP 서버의 도구 목록 · 호출
const SCOPE = { read: "읽기", write: "쓰기", exec: "실행" };
const parseArgs = s => { try { return s.trim() ? JSON.parse(s) : {}; } catch { throw new Error("입력은 JSON 이어야 합니다"); } };

function resultHtml(r) {
  const text = (r.content || []).filter(c => c.type === "text").map(c => c.text).join("\n");
  return html`<div class="small">${r.isError ? html`<span class="badge err">도구 오류</span>` : html`<span class="badge ok">성공</span>`}
    ${r.trace_key ? html` · 추적 <a class="mono" href="/interop/audit?trace=${r.trace_key}">${r.trace_key}</a>` : ""}
    ${r._meta?.budget ? html` · 세션 호출 ${r._meta.budget.calls}/${r._meta.budget.max_calls}` : ""}</div>
    <pre class="pre small scroll-md">${r.structuredContent ? JSON.stringify(r.structuredContent, null, 1) : text}</pre>`;
}

async function load() {
  const d = await api("/api/interop/tools");
  $("#t-conn").innerHTML = html`주소 <span class="mono">${d.mcp_url}</span> · 규격 ${d.protocol} · Streamable HTTP(JSON 응답) — 인증이 켜져 있으면 <span class="mono">Authorization: Bearer &lt;토큰&gt;</span>
    <details><summary>MCP 클라이언트 설정 예</summary><pre class="pre small">${JSON.stringify({ mcpServers: { atlas: { type: "http", url: d.mcp_url } } }, null, 2)}</pre></details>`;
  $("#t-tools").innerHTML = html`<div class="table-wrap"><table><tr><th>도구</th><th>범위</th><th>설명</th><th>지금 역할(${d.role})</th></tr>
    ${html.join(d.tools.map(t => html`<tr><td class="small mono">${t.name}</td><td><span class="badge ${t.scope === "exec" ? "warn" : ""}">${SCOPE[t.scope]}</span>${t.untrusted ? html` <span class="badge" title="결과를 신뢰 경계 밖 입력으로 다룸">외부 결과</span>` : ""}</td>
      <td class="small">${t.description}</td><td>${t.allowed ? html`<span class="badge ok">허용</span>` : html`<span class="badge err">불가</span>`}</td></tr>`), "")}</table></div>`;
  $("#t-name").innerHTML = html`${d.tools.filter(t => t.allowed).map(t => html`<option>${t.name}</option>`)}`;
  $("#t-policy").innerHTML = html`역할별 허용 범위: ${html.join(Object.entries(d.policy).map(([r, s]) => html`<b>${r}</b> ${s.map(x => SCOPE[x]).join(" · ")}`), " / ")}
    · 샌드박스 ${d.docker ? html`<span class="badge ok">Docker</span> <span class="mono">${d.sandbox_image}</span> (네트워크 없음 · 읽기 전용 · 메모리 256MB · 프로세스 64)` : html`<span class="badge warn">Docker 없음 — 별도 프로세스(네트워크 · 파일 접근을 막지 못함)</span>`}`;
  const s = await api("/api/interop/servers");
  $("#t-servers").innerHTML = html`<option value="${s.self.mcp}">이 앱</option>${s.mcp_servers.map(x => html`<option value="${x.url}">${x.name || x.url}</option>`)}`;
  if (!$("#t-url").value) $("#t-url").value = s.self.mcp;
}

$("#t-call").onclick = e => {
  let args;
  try { args = parseArgs($("#t-args").value); } catch (err) { return toast(err.message, "err"); }
  busy(e.target, () => api(`/api/interop/tools/${$("#t-name").value}/call`, { method: "POST", body: { arguments: args } }))
    .then(r => { $("#t-out").innerHTML = resultHtml(r); }).catch(err => ui.error($("#t-out"), err));
};
$("#t-run").onclick = e => busy(e.target, () => api("/api/interop/sandbox", { method: "POST", body: { code: $("#t-code").value } }))
  .then(r => {
    const o = r.structuredContent || JSON.parse((r.content || [{}])[0].text || "{}");
    $("#t-run-out").innerHTML = r.isError ? resultHtml(r) : html`<div class="small"><span class="badge ${o.isolation === "docker" ? "ok" : "warn"}">${o.isolation}</span> 종료 코드 ${o.exit_code ?? "-"} · ${o.seconds}초${o.timed_out ? " · 시간 상한" : ""}
      · 추적 <a class="mono" href="/interop/audit?trace=${r.trace_key}">${r.trace_key}</a></div><pre class="pre small">${o.stdout}</pre>${o.stderr ? html`<pre class="pre small muted">${o.stderr}</pre>` : ""}`;
  }).catch(err => ui.error($("#t-run-out"), err));
$("#t-inspect").onclick = e => busy(e.target, () => api("/api/interop/remote/tools", { method: "POST", body: { url: $("#t-url").value.trim(), token: $("#t-token").value || null } }))
  .then(r => {
    $("#t-remote").innerHTML = html`<div class="small">${r.server?.title || r.server?.name || "서버"} · 규격 ${r.protocol}${r.instructions ? html` — <span class="muted">${r.instructions}</span>` : ""}</div>
      <div class="table-wrap"><table><tr><th>도구</th><th>설명</th><th>시험</th></tr>
      ${html.join(r.tools.map(t => html`<tr data-tool="${t.name}"><td class="small mono">${t.name}${t.annotations?.readOnlyHint ? html` <span class="badge">읽기</span>` : ""}</td>
        <td class="small">${t.description}${t._flags.length ? html` <span class="badge err" title="${t._flags.map(f => f.removed).join(" / ")}">설명에 지시 문장</span>` : ""}</td>
        <td><div class="row m-0"><input data-args class="mono w-md" placeholder="{}" aria-label="${t.name} 입력"><button class="btn sm" data-rcall>호출</button></div></td></tr>`), "")}</table></div><div id="t-remote-out"></div>`;
    $$("[data-rcall]", $("#t-remote")).forEach(b => b.onclick = () => {
      const tr = b.closest("tr");
      let args;
      try { args = parseArgs($("[data-args]", tr).value); } catch (err) { return toast(err.message, "err"); }
      busy(b, () => api("/api/interop/remote/call", { method: "POST", body: { url: $("#t-url").value.trim(), token: $("#t-token").value || null, name: tr.dataset.tool, arguments: args } }))
        .then(x => { $("#t-remote-out").innerHTML = html`<div class="small">${x.isError ? html`<span class="badge err">도구 오류</span>` : html`<span class="badge ok">성공</span>`} <span class="badge">외부 결과</span>
          ${x.flags.length ? html`<span class="badge err">지시 문장 ${x.flags.length}개 뺌</span>` : ""} · 추적 <a class="mono" href="/interop/audit?trace=${x.trace_key}">${x.trace_key}</a></div><pre class="pre small scroll-md">${x.text}</pre>`; })
        .catch(err => ui.error($("#t-remote-out"), err));
    });
  }).catch(err => ui.error($("#t-remote"), err));

load().catch(e => ui.error($("#t-tools"), e));
