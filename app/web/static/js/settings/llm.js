// rag/llm.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
async function loadStatus() {
  const s = await api("/api/llm/status");
  const o = s.providers.openai, a = s.providers.anthropic;
  const row = (name, ok, detail) => html`<tr><td><b>${name}</b></td><td>${ok ? html`<span class="badge ok">설정됨</span>` : html`<span class="badge">미설정</span>`}</td><td class="small">${detail}</td></tr>`;
  $("#l-status").innerHTML = html`<table>
    ${row("OpenAI 호환", o.configured, html`<span class="mono">${o.base_url}</span> · 모델 <span class="mono">${o.model || "-"}</span>${o.has_key ? " · 키 있음" : ""}`)}
    ${row("Claude", a.configured, html`모델 <span class="mono">${a.model}</span>`)}
  </table>
  <div class="small mt-2">기본 제공자: ${s.default.error ? html`<span class="badge warn">없음</span> ${s.default.error}` : html`<b>${s.default.provider === "openai" ? "OpenAI 호환" : "Claude"}</b> · <span class="mono">${s.default.model}</span>`}</div>`;
}
async function loadModels() {
  $("#l-models").innerHTML = html`<span class="muted">확인 중…</span>`;
  try {
    const r = await api("/api/llm/models");
    $("#l-models").innerHTML = html`<div class="muted">${r.base_url}</div>` + (html.or(html.join(r.models.map(m => html`<span class="badge ok mono">${m}</span>`), " "), html`<span class="muted">모델 없음</span>`));
    $("#t-model-list").innerHTML = html.join(r.models.map(m => html`<option value="${m}">`), "");
  } catch (e) {
    $("#l-models").innerHTML = html`<div class="warnbox">서버에 연결할 수 없습니다. 로컬 서버를 켰는지, OPENAI_BASE_URL 이 맞는지 확인하세요.<div class="small muted">${e.message}</div></div>`;
  }
}
$("#l-refresh").onclick = loadModels;
$("#t-run").onclick = async e => {
  const body = { provider: $("#t-provider").value || null, model: $("#t-model").value.trim() || null, prompt: $("#t-prompt").value };
  const r = await busy(e.target, () => api("/api/llm/test", { method: "POST", body }));
  const u = r.usage || {};
  $("#t-out").innerHTML = html`<div class="card bg-code pre">${r.text || "(빈 응답)"}</div>
    <div class="small muted">${r.config.model} · ${r.seconds}s · 입력 ${u.input_tokens ?? "-"} / 출력 ${u.output_tokens ?? "-"} 토큰${r.tokens_per_second ? html` · ${r.tokens_per_second} 토큰/초` : ""}${u.truncated ? html` · <span class="badge warn">길이 한도에서 잘림</span>` : ""}${u.reasoning_only ? html` · <span class="badge warn">생각만 하고 답이 없음</span>` : ""}</div>`;
};
loadStatus(); loadModels();
