// 화면 뼈대의 동작: 사이드바 · 단계 서랍 · 설명 접기 · 테마 · 빠른 이동(Ctrl K) · 작업 표시 · 작업 맥락 줄.
// 모든 화면이 base.html 로 같은 뼈대를 쓰므로, 화면 스크립트는 이 파일을 신경 쓰지 않아도 된다.
(() => {
  // ── 사이드바: 좁은 화면에서는 ☰ 로 여는 서랍, 묶음(맵 목록 등)의 펼침 상태는 기억 ──
  const side = $("#sidebar"), menuBtn = $("#menu-btn");
  let scrim = null;
  function overlay(onClose) {
    scrim?.remove();
    scrim = document.createElement("div");
    scrim.className = "scrim";
    scrim.addEventListener("click", onClose);
    document.body.appendChild(scrim);
  }
  function closeSide() { side.classList.remove("open"); menuBtn?.setAttribute("aria-expanded", "false"); scrim?.remove(); scrim = null; }
  menuBtn?.addEventListener("click", () => {
    if (side.classList.toggle("open")) { menuBtn.setAttribute("aria-expanded", "true"); overlay(closeSide); $("a", side)?.focus(); } else closeSide();
  });
  $$(".side-group", side).forEach(d => {
    const key = "side-" + d.dataset.group;
    if (!d.classList.contains("active") && localGet(key) === "open") d.open = true;
    d.addEventListener("toggle", () => { if (!d.classList.contains("active")) localSet(key, d.open ? "open" : "closed"); });
  });
  $(".side-link.active", side)?.scrollIntoView({ block: "nearest" });

  // ── 단계 설명 서랍(ⓘ) ──
  const drawer = $("#stage-drawer"), stageBtn = $("#stage-btn");
  function closeDrawer() {
    drawer?.classList.remove("open"); drawer?.setAttribute("aria-hidden", "true");
    stageBtn?.setAttribute("aria-expanded", "false"); scrim?.remove(); scrim = null; stageBtn?.focus();
  }
  stageBtn?.addEventListener("click", () => {
    drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); stageBtn.setAttribute("aria-expanded", "true");
    overlay(closeDrawer); $("[data-close]", drawer).focus();
  });
  $("[data-close]", drawer || document.createElement("div"))?.addEventListener("click", closeDrawer);

  // ── 긴 설명은 두 줄로 접고 '더 보기' (설명이 700자를 넘는 화면이 있어 도구가 아래로 밀렸다) ──
  $$(".page-head .lead").forEach(p => {
    p.classList.add("clamped");
    if (p.scrollHeight <= p.clientHeight + 2) { p.classList.remove("clamped"); return; }
    const b = document.createElement("button");
    b.type = "button"; b.className = "more-btn"; b.textContent = "더 보기"; b.setAttribute("aria-expanded", "false");
    b.addEventListener("click", () => {
      const open = p.classList.toggle("clamped") === false;
      b.textContent = open ? "접기" : "더 보기"; b.setAttribute("aria-expanded", String(open));
    });
    p.after(b);
  });

  // ── 테마: 시스템 → 밝게 → 어둡게. 차트는 themechange 로 새 색을 다시 그린다(lib/charts.js) ──
  const themeBtn = $("#theme-btn");
  const THEME_LABEL = { "": "시스템 설정", light: "밝게", dark: "어둡게" };
  function showTheme() {
    const t = document.documentElement.dataset.theme || "";
    themeBtn.title = `테마: ${THEME_LABEL[t]} (눌러서 바꾸기)`;
    themeBtn.setAttribute("aria-label", themeBtn.title);
  }
  themeBtn?.addEventListener("click", () => {
    const order = ["", "light", "dark"], cur = document.documentElement.dataset.theme || "";
    const next = order[(order.indexOf(cur) + 1) % order.length];
    if (next) document.documentElement.dataset.theme = next; else delete document.documentElement.dataset.theme;
    localSet("atlas-theme", next);
    showTheme();
    window.dispatchEvent(new Event("themechange"));
    toast(`테마: ${THEME_LABEL[next]}`);
  });
  if (themeBtn) showTheme();

  // ── 빠른 이동(Ctrl K · /): 화면 · 단계 · 맵(/ui/search-index.json) + 컬렉션(/api) ──
  const pal = $("#palette"), palQ = $("#palette-q"), palList = $("#palette-list");
  let index = null, hits = [], sel = 0;
  async function loadIndex() {
    if (index) return index;
    const [pages, cols] = await Promise.all([api("/ui/search-index.json"), api("/api/collections").catch(() => [])]);
    index = pages.concat(cols.map(c => ({ type: "컬렉션", label: c.name, desc: c.description || "", href: `/rag/collections/${c.id}` })));
    return index;
  }
  function renderHits() {
    const words = palQ.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const score = x => {
      const l = x.label.toLowerCase(), d = (x.desc || "").toLowerCase();
      if (!words.every(w => l.includes(w) || d.includes(w))) return -1;
      return words.reduce((s, w) => s + (l.startsWith(w) ? 3 : l.includes(w) ? 2 : 0), 0) + (x.type === "화면" ? 1 : 0);
    };
    hits = (index || []).map(x => [score(x), x]).filter(([s]) => s >= 0).sort((a, b) => b[0] - a[0]).slice(0, 40).map(([, x]) => x);
    sel = Math.min(sel, Math.max(0, hits.length - 1));
    palList.innerHTML = hits.length
      ? html`${hits.map((x, i) => html`<li role="option" aria-selected="${i === sel}"><a href="${x.href}" class="${i === sel ? "sel" : ""}"><span class="t">${x.type}</span><span class="l">${x.label}</span><span class="d">${x.desc}</span></a></li>`)}`
      : html`<li class="empty">찾는 이름이 없습니다</li>`;
    $(".sel", palList)?.scrollIntoView({ block: "nearest" });
  }
  async function openPalette() {
    if (!pal?.showModal || pal.open) return;
    palQ.value = ""; sel = 0;
    pal.showModal();
    palList.innerHTML = html`<li class="loading">불러오는 중…</li>`;
    await loadIndex().catch(e => toast(e.message, "err"));
    renderHits();
  }
  $("#palette-btn")?.addEventListener("click", openPalette);
  palQ?.addEventListener("input", () => { sel = 0; renderHits(); });
  palQ?.addEventListener("keydown", e => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + hits.length) % Math.max(1, hits.length); renderHits(); }
    if (e.key === "Enter" && hits[sel]) { e.preventDefault(); location.href = hits[sel].href; }
  });
  pal?.addEventListener("click", e => { if (e.target === pal) pal.close(); });
  document.addEventListener("keydown", e => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); }
    else if (e.key === "/" && !typing) { e.preventDefault(); openPalette(); }
    else if (e.key === "Escape") { if (drawer?.classList.contains("open")) closeDrawer(); else if (side.classList.contains("open")) closeSide(); else if (!jobsPop.hidden) closeJobs(); }
  });

  // ── 작업 표시: 다른 화면으로 옮겨도 백그라운드 작업 진행을 보고, 끝나면 알림 ──
  const jobsBtn = $("#jobs-btn"), jobsPop = $("#jobs-pop"), jobsN = $("#jobs-n");
  const STATUS = { pending: ["대기", ""], running: ["진행 중", ""], done: ["완료", "ok"], error: ["오류", "err"], cancelled: ["취소", "muted"], interrupted: ["중단됨", "warn"] };
  const seenLive = new Set();
  let jobs = [], timer = null;
  const live = j => ["pending", "running"].includes(j.status);
  function renderJobs() {
    const n = jobs.filter(live).length;
    jobsN.textContent = n;
    jobsBtn.classList.toggle("busy", n > 0);
    jobsBtn.title = n ? `진행 중인 작업 ${n}개` : "백그라운드 작업";
    if (jobsPop.hidden) return;
    jobsPop.innerHTML = jobs.length
      ? html`${jobs.slice(0, 12).map(j => live(j) ? html`<div class="job-row">${ui.jobProgress(j)}</div>` : html`<div class="job-row">
          <div class="row between small"><span>${j.title}</span><span class="badge ${STATUS[j.status]?.[1] ?? ""}">${STATUS[j.status]?.[0] ?? j.status}</span></div>
          <div class="small muted">${fmtDate(j.finished_at || j.created_at)}${j.error ? html` · <span class="break-all">${j.error.split("\n")[0].slice(0, 160)}</span>` : ""}</div></div>`)}
         <div class="small mt-2"><a href="/history">실행 이력 →</a></div>`
      : html`<div class="empty">작업이 없습니다</div>`;
  }
  async function pollJobs() {
    clearTimeout(timer);
    try {
      jobs = await api("/api/jobs?limit=20");
      jobs.forEach(j => {
        if (live(j)) seenLive.add(j.id);
        else if (seenLive.delete(j.id)) toast(`작업 ${STATUS[j.status]?.[0] ?? j.status}: ${j.title}`, j.status === "done" ? "ok" : "err");
      });
      renderJobs();
    } catch { /* 로그인 화면 이동 등 — 다음 주기에 다시 */ }
    // 진행 중이면 자주, 아니면 드물게 (작업이 없을 때 서버를 계속 두드리지 않게)
    timer = setTimeout(pollJobs, jobs.some(live) || !jobsPop.hidden ? 2000 : 15000);
  }
  function closeJobs() { jobsPop.hidden = true; jobsBtn.setAttribute("aria-expanded", "false"); }
  jobsBtn?.addEventListener("click", e => {
    e.stopPropagation();
    jobsPop.hidden = !jobsPop.hidden;
    jobsBtn.setAttribute("aria-expanded", String(!jobsPop.hidden));
    if (!jobsPop.hidden) { renderJobs(); pollJobs(); }
  });
  document.addEventListener("click", e => { if (!jobsPop.hidden && !jobsPop.contains(e.target) && e.target !== jobsBtn) closeJobs(); });
  if (jobsBtn) pollJobs();

  // ── 작업 맥락 줄 + 바꾸기 대화상자 ──
  const bar = $("#ctxbar"), dlg = $("#ctx-dlg");
  function renderCtx() {
    const c = Ctx.get();
    const chip = (name, label, id) => html`<span class="ctx-chip${label || id ? "" : " unset"}" title="${label || ""}"><b>${name}</b><span>${label || (id ? `#${id}` : "기본")}</span></span>`;
    bar.innerHTML = html`<span>작업 맥락</span>${chip("컬렉션", c.colLabel, c.col)}${chip("인덱스", c.idxLabel, c.idx)}${chip("평가 세트", c.setLabel, c.set)}${chip("LLM", [c.providerLabel, c.model].filter(Boolean).join(" · "), "")}
      <button type="button" class="btn sm" id="ctx-edit">바꾸기</button>`;
    $("#ctx-edit").onclick = openCtx;
  }
  async function fillCtxDialog() {
    const c = Ctx.get();
    const cols = await api("/api/collections");
    $("#ctx-col").innerHTML = html`<option value="">고르지 않음</option>${cols.map(x => html`<option value="${x.id}">${x.name}</option>`)}`;
    $("#ctx-col").value = c.col && cols.some(x => String(x.id) === c.col) ? c.col : "";
    await fillCtxDetail(c);
    $("#ctx-provider").value = c.provider || "";
    $("#ctx-model").value = c.model || "";
  }
  async function fillCtxDetail(c = {}) {
    const id = $("#ctx-col").value;
    const d = id ? await api(`/api/collections/${id}`) : { indexes: [] };
    const sets = id ? (await api(`/api/collections/${id}/eval-sets`)).filter(s => s.status === "ready") : [];
    $("#ctx-idx").innerHTML = html`<option value="">고르지 않음</option>${d.indexes.filter(i => i.status === "ready").map(i => html`<option value="${i.id}">${i.model_hf_id.split(/[\/]/).pop()} · #${i.id}</option>`)}`;
    $("#ctx-set").innerHTML = html`<option value="">고르지 않음</option>${sets.map(s => html`<option value="${s.id}">#${s.id} ${s.name} (${s.n_items}문항)</option>`)}`;
    if (c.idx) $("#ctx-idx").value = c.idx;
    if (c.set) $("#ctx-set").value = c.set;
  }
  async function openCtx() {
    if (!dlg?.showModal) return;
    dlg.showModal();
    await fillCtxDialog().catch(e => toast(e.message, "err"));
  }
  if (dlg) {
    $("#ctx-col").addEventListener("change", () => fillCtxDetail().catch(e => toast(e.message, "err")));
    $("[data-close]", dlg).addEventListener("click", () => dlg.close());
    $("#ctx-clear").addEventListener("click", () => { Ctx.clear(); dlg.close(); reloadClean(); });
    $("#ctx-save").addEventListener("click", () => {
      const lab = id => $(id).value ? $(id).selectedOptions[0].textContent.trim() : "";
      Ctx.set({ col: $("#ctx-col").value, colLabel: lab("#ctx-col") });  // 컬렉션이 바뀌면 딸린 값이 먼저 비워진다
      Ctx.set({ idx: $("#ctx-idx").value, idxLabel: lab("#ctx-idx"), set: $("#ctx-set").value, setLabel: lab("#ctx-set"),
                provider: $("#ctx-provider").value, providerLabel: lab("#ctx-provider"), model: $("#ctx-model").value.trim() });
      dlg.close();
      reloadClean();  // 화면마다 맥락을 읽는 시점이 달라, 새 맥락으로 화면을 다시 연다
    });
  }
  function reloadClean() {
    const u = new URL(location.href);
    ["col", "cs", "idx", "set"].forEach(k => u.searchParams.delete(k));
    location.href = u.toString();
  }
  Ctx.on(renderCtx);
  // 화면 스크립트가 먼저 돌고(같은 동기 순서) 맥락을 쓰는지 정해진 뒤에 줄을 보인다
  window.addEventListener("DOMContentLoaded", () => {
    bindCtx();
    if (Ctx.used && bar) { bar.hidden = false; renderCtx(); }
  });
})();
