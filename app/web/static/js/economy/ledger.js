// economy/ledger.html 화면 스크립트 — 견적(EC1~EC4), 일 처리 흉내(EC5~EC8), 규칙 있음 vs 없음
const won = v => `${(v ?? 0).toLocaleString()}원`;
const STAT = { unapproved_paid: "승인 없이 결제", over_budget: "월 한도 넘은 돈", off_mandate_paid: "위임 밖 결제", double_paid: "이중 결제", paid_unverified: "검증 없이 낸 건",
  lost_to_bad: "엉터리 · 미납품에 잃은 돈", refunded: "돌려받은 돈", blocked: "막은 건", approvals_asked: "승인 요청", spent: "쓴 돈" };
const MONEY = new Set(["over_budget", "lost_to_bad", "refunded", "spent"]);

$("#k-run").onclick = e => busy(e.target, () => api("/api/economy/quote", { method: "POST", body: { skill: $("#k-skill").value, qty: +$("#k-qty").value, spent: +$("#k-spent").value,
  need: { min_quality: +$("#k-q").value, refund_required: $("#k-refund").checked } } })).then(r => {
  $("#k-out").innerHTML = html`<div class="table-wrap"><table><tr><th>서비스</th><th>가격</th><th>품질</th><th>납기(초)</th><th>환불</th><th>품질 대비 가격</th><th>가능</th></tr>
      ${html.join(r.candidates.map(c => html`<tr><td>${c.name}</td><td>${won(c.price)}/${c.unit}</td><td>${c.quality}</td><td>${c.deliver_s}</td><td>${c.refund}</td><td>${c.value}</td>
        <td>${c.eligible ? html`<span class="badge ok">예</span>` : html`<span class="badge">아니오</span> <span class="small muted">${c.excluded_why.join(" · ")}</span>`}</td></tr>`), "")}</table></div>
    ${r.pick ? html`<div class="small">고름: <b>${r.pick.name}</b> ${won(r.amount)} — 위임 검사 ${r.mandate_violations.length ? html`<span class="badge err">막음</span> ${r.mandate_violations.join(" · ")}` : html`<span class="badge ok">통과</span>`}
      · 사람 승인 ${r.approval_needed.length ? html`<span class="badge warn">필요</span> ${r.approval_needed.join(" · ")}` : "불필요"}</div>` : html`<div class="small">요구를 맞추는 서비스가 없습니다</div>`}`;
}).catch(err => ui.error($("#k-out"), err));

$("#s-run").onclick = e => busy(e.target, () => api("/api/economy/simulate", { method: "POST", body: { n: +$("#s-n").value, seed: +$("#s-seed").value, guarded: $("#s-guard").checked } })).then(r => {
  $("#s-out").innerHTML = html`<div class="small">장부 합 ${r.audit.balanced ? "맞음" : "어긋남"} · 해시 사슬 ${r.audit.chain_ok ? "이어짐" : "끊김"} · 에스크로에 남은 돈 ${won(r.audit.in_escrow)}</div>
    <div class="small">${Object.entries(r.stats).map(([k, v]) => `${STAT[k]} ${MONEY.has(k) ? won(v) : v}`).join(" · ")}</div>
    <div class="table-wrap scroll-md"><table><tr><th>#</th><th>기능</th><th>서비스</th><th>금액</th><th>섞은 공격</th><th>결과</th><th>이유</th></tr>
      ${html.join(r.events.map(x => html`<tr><td>${x.i}</td><td>${x.skill}</td><td>${x.service ?? "-"}</td><td>${x.amount ? won(x.amount) : "-"}</td><td>${x.attack ?? ""}</td><td>${x.result}</td>
        <td class="small">${(x.why || []).join(" · ")}${x.verify ? ` ${x.verify}` : ""}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#s-out"), err));

$("#e-run").onclick = e => busy(e.target, () => api("/api/economy/evaluate", { method: "POST", body: { seeds: +$("#e-seeds").value, n: 40 } })).then(r => {
  const keys = Object.keys(STAT);
  $("#e-out").innerHTML = html`<div class="small muted">씨앗 ${r.seeds} × 일 ${r.n} · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>항목</th><th>규칙 있음</th><th>규칙 없음</th></tr>
      ${html.join(keys.map(k => html`<tr><td>${STAT[k]}</td><td><b>${MONEY.has(k) ? won(r.guarded.stats[k]) : r.guarded.stats[k]}</b></td><td>${MONEY.has(k) ? won(r.naive.stats[k]) : r.naive.stats[k]}</td></tr>`), "")}
      <tr><td>장부 합 · 해시 사슬</td><td>${r.guarded.balanced && r.guarded.chain_ok ? "맞음" : "어긋남"}</td><td>${r.naive.balanced && r.naive.chain_ok ? "맞음" : "어긋남"}</td></tr></table></div>
    <h3>공격마다 규칙 있는 에이전트의 결과</h3>
    <ul class="small">${Object.entries(r.guarded.by_attack).map(([a, rs]) => html`<li>${a}: ${Object.entries(rs).map(([k, v]) => `${k} ${v}`).join(" · ")}</li>`)}</ul>`;
}).catch(err => ui.error($("#e-out"), err));

api("/api/economy/market").then(p => {
  const m = p.mandate;
  $("#k-mandate").textContent = `위임: ${m.principal} → ${m.agent} · 기능 ${m.skills.join(", ")} · 건당 ${won(m.per_tx)} · 월 ${won(m.monthly)} · ${won(m.approve_over)} 넘으면 사람 승인 · 기한 ${m.expires}`;
}).catch(err => ui.error($("#k-mandate"), err));
