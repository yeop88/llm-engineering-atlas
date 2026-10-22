// memory/store.html 화면 스크립트 — 대화 → 기억 추출 · 갱신 판단(ME1 · ME4), 기억 DB · 시점 이력 · 연결 보기(ME2)
const ACTION = { add: ["ok", "추가"], update: ["warn", "고치기(예전 값 무효)"], noop: ["", "그대로"] };
const day = s => (s ? s.slice(0, 10) : "");

$("#m-at").value = new Date().toISOString().slice(0, 10);
$("#m-run").onclick = e => busy(e.target, () => api("/api/memory/remember", { method: "POST", body: { owner: $("#m-owner").value.trim(), text: $("#m-text").value,
  at: `${$("#m-at").value}T12:00:00`, extractor: $("#m-ext").value, provider: $("#m-provider").value || null, model: $("#m-model").value.trim() || null } })).then(r => {
  $("#m-out").innerHTML = html`<div class="small muted">뽑은 기억 ${r.extracted}개</div><ul class="small">${html.join(r.decisions.map(d => html`<li><span class="badge ${ACTION[d.action][0]}">${ACTION[d.action][1]}</span>
    ${d.key ? html`<b>${d.key}</b> = ${d.value}` : d.text}${d.replaced ? html` <span class="muted">(무효로 한 기억 #${d.replaced.join(", #")})</span>` : ""}</li>`), "")}</ul>`;
  loadOwners($("#m-owner").value.trim());
}).catch(err => ui.error($("#m-out"), err));

async function loadOwners(pick) {
  const r = await api("/api/memory/owners");
  $("#v-owner").innerHTML = html`${r.owners.map(o => html`<option value="${o.owner}">${o.owner} · 기억 ${o.items}(지금 ${o.current})</option>`)}`;
  if (pick) $("#v-owner").value = pick;
  if (r.owners.length) await show();
}

async function show() {
  const r = await api(`/api/memory/items?owner=${encodeURIComponent($("#v-owner").value)}&history=${$("#v-hist").checked}`);
  $("#v-core").innerHTML = r.core ? html`<b>핵심 기억</b> ${r.core}` : "";
  const links = {};
  r.links.forEach(l => { (links[l.a] = links[l.a] || []).push(`${l.kind} #${l.b}`); });
  $("#v-out").innerHTML = html`<div class="table-wrap"><table><tr><th>#</th><th>key</th><th>값 · 문장</th><th>종류</th><th>계층</th><th>맞았던 때</th><th>중요도</th><th>쓰임</th><th>연결</th></tr>
    ${html.join(r.items.map(i => html`<tr${i.valid_to ? html` class="muted"` : ""}><td>${i.id}</td><td>${i.key || "-"}</td><td class="small">${i.value || i.text}${i.happened_at ? html` <span class="muted">(일어난 날 ${day(i.happened_at)})</span>` : ""}</td>
      <td>${i.kind}</td><td>${i.tier}</td><td class="small">${day(i.valid_from)} ~ ${i.valid_to ? day(i.valid_to) : "지금"}${i.superseded_by ? html` → #${i.superseded_by}` : ""}</td><td>${i.importance}</td><td>${i.access_count}</td>
      <td class="small">${(links[i.id] || []).join(", ")}</td></tr>`), "")}</table></div>`;
}

$("#v-load").onclick = e => busy(e.target, show).catch(err => ui.error($("#v-out"), err));
$("#v-del").onclick = async () => {
  if (!(await ui.confirm(`${$("#v-owner").value} 의 기억을 모두 지울까요?`))) return;
  api(`/api/memory/owners/${encodeURIComponent($("#v-owner").value)}`, { method: "DELETE" }).then(() => loadOwners()).catch(err => toast(err.message, "err"));
};
loadOwners().catch(e => ui.error($("#v-out"), e));
