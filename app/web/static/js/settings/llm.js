// rag/llm.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
async function loadStatus() {
  const s = await api("/api/llm/status");
  const o = s.providers.openai, a = s.providers.anthropic;
  const row = (name, ok, detail) => `<tr><td><b>${name}</b></td><td>${ok ? '<span class="badge ok">설정됨</span>' : '<span class="badge">미설정</span>'}</td><td class="small">${detail}</td></tr>`;
  $("#l-status").innerHTML = `<table>
    ${row("OpenAI 호환", o.configured, `<span class="mono">${esc(o.base_url)}</span> · 모델 <span class="mono">${esc(o.model || "-")}</span>${o.has_key ? " · 키 있음" : ""}`)}
    ${row("Claude", a.configured, `모델 <span class="mono">${esc(a.model)}</span>`)}
  </table>
  <div class="small mt-2">기본 제공자: ${s.default.error ? `<span class="badge warn">없음</span> ${esc(s.default.error)}` : `<b>${s.default.provider === "openai" ? "OpenAI 호환" : "Claude"}</b> · <span class="mono">${esc(s.default.model)}</span>`}</div>`;
}
async function loadModels() {
  $("#l-models").innerHTML = '<span class="muted">확인 중…</span>';
  try {
    const r = await api("/api/llm/models");
    $("#l-models").innerHTML = `<div class="muted">${esc(r.base_url)}</div>` + (r.models.map(m => `<span class="badge ok mono">${esc(m)}</span>`).join(" ") || '<span class="muted">모델 없음</span>');
    $("#t-model-list").innerHTML = r.models.map(m => `<option value="${esc(m)}">`).join("");
  } catch (e) {
    $("#l-models").innerHTML = `<div class="warnbox">서버에 연결할 수 없습니다. 로컬 서버를 켰는지, OPENAI_BASE_URL 이 맞는지 확인하세요.<div class="small muted">${esc(e.message)}</div></div>`;
  }
}
$("#l-refresh").onclick = loadModels;
$("#t-run").onclick = async e => {
  const body = { provider: $("#t-provider").value || null, model: $("#t-model").value.trim() || null, prompt: $("#t-prompt").value };
  const r = await busy(e.target, () => api("/api/llm/test", { method: "POST", body }));
  const u = r.usage || {};
  $("#t-out").innerHTML = `<div class="card bg-code">${esc(r.text || "(빈 응답)").replace(/\n/g, "<br>")}</div>
    <div class="small muted">${esc(r.config.model)} · ${r.seconds}s · 입력 ${u.input_tokens ?? "-"} / 출력 ${u.output_tokens ?? "-"} 토큰${r.tokens_per_second ? ` · ${r.tokens_per_second} 토큰/초` : ""}${u.truncated ? ' · <span class="badge warn">길이 한도에서 잘림</span>' : ""}${u.reasoning_only ? ' · <span class="badge warn">생각만 하고 답이 없음</span>' : ""}</div>`;
};
loadStatus(); loadModels();
