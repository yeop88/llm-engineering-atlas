// computer_use/screen.html 화면 스크립트 — 시험용 사이트의 접근성 트리 · 숨은 글(CU1), 설명으로 요소 찾기 정확도
const START = { legacy: "http://legacy.local/new", manual: "http://manual.local/", admin: "http://admin.local/" };
$("#p-site").onchange = () => { $("#p-url").value = START[$("#p-site").value]; };

$("#p-run").onclick = e => busy(e.target, () => api("/api/computer-use/perceive", { method: "POST", body: { site: $("#p-site").value, url: $("#p-url").value.trim(), logged_in: $("#p-login").checked } }))
  .then(r => {
    $("#p-tree").textContent = r.tree;
    $("#p-hidden").innerHTML = html`${r.hidden_text.length ? html`<ul>${html.join(r.hidden_text.map(t => html`<li>${t}</li>`), "")}</ul>` : html`<p class="muted">숨은 글 없음</p>`}
      ${r.injection.length ? html`<div><span class="badge err">인젝션 의심</span> ${r.injection.join(", ")}</div>` : html`<span class="badge ok">인젝션 표현 없음</span>`}`;
  }).catch(err => ui.error($("#p-hidden"), err));

$("#f-run").onclick = e => busy(e.target, () => api("/api/computer-use/perceive/eval", { method: "POST", body: { provider: $("#f-provider").value || null, model: $("#f-model").value.trim() || null } }))
  .then(r => {
    $("#f-out").innerHTML = html`<div class="small"><b>${(r.acc * 100).toFixed(1)}%</b> (${r.n}개) · ${r.model} · run #${r.run_id}</div><div class="table-wrap"><table><tr><th>설명</th><th>정답</th><th>고른 요소</th><th></th></tr>
      ${html.join(r.rows.map(x => html`<tr><td>${x.desc}</td><td>${x.gold}</td><td>${x.got ?? "-"}</td><td><span class="badge ${x.correct ? "ok" : "err"}">${x.correct ? "맞음" : "틀림"}</span></td></tr>`), "")}</table></div>`;
  }).catch(err => ui.error($("#f-out"), err));
