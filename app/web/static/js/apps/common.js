// 응용 화면 공통: 입력 소스 선택기 · 모델 선택 · 백그라운드 작업 실행
const Apps = (() => {
  // 직접 입력 형식: 한 줄에 하나, 라벨이 있으면 "[라벨] 텍스트"
  function parseLines(raw) {
    return raw.split("\n").map(s => s.trim()).filter(Boolean).map((line, i) => {
      const m = /^\[([^\]]{1,40})\]\s*(.+)$/.exec(line);
      return m ? { id: String(i + 1), label: m[1].trim(), text: m[2] } : { id: String(i + 1), text: line };
    });
  }
  const toLines = items => items.map(it => (it.label ? `[${it.label}] ${it.text}` : it.text)).join("\n");

  // 입력 소스 선택기. opts: {app, labels: "none"|"optional"|"required", placeholder}
  async function sourcePicker(root, opts = {}) {
    const id = Math.random().toString(36).slice(2, 7);
    root.innerHTML = `
      <div class="row mb-2">
        <label class="row m-0"><input type="radio" name="src-${id}" value="texts" checked> 직접 입력</label>
        <label class="row m-0"><input type="radio" name="src-${id}" value="collection"> 문서 검색 컬렉션</label>
      </div>
      <div data-pane="texts" class="stack">
        <div class="row"><div class="field grow"><label for="${id}-preset">예시 데이터</label><select id="${id}-preset" data-preset><option value="">— 직접 입력 —</option></select></div></div>
        <div><label for="${id}-text">텍스트 (한 줄에 하나${opts.labels !== "none" ? ", 라벨은 <code>[라벨] 텍스트</code>" : ""})</label>
          <textarea id="${id}-text" data-text rows="10" class="small" placeholder="${esc(opts.placeholder || "")}"></textarea></div>
        <div class="small muted" data-count></div>
      </div>
      <div data-pane="collection" class="stack" hidden>
        <div class="row">
          <div class="field grow"><label for="${id}-col">컬렉션</label><select id="${id}-col" data-col></select></div>
          <div class="field"><label for="${id}-unit">단위</label><select id="${id}-unit" data-unit><option value="document">문서</option><option value="chunk">청크</option></select></div>
          <div class="field grow" data-cs-wrap hidden><label for="${id}-cs">청크 세트</label><select id="${id}-cs" data-cs></select></div>
        </div>
        <div class="small muted">문서 단위는 제목 + 앞부분 2,000자를 씁니다. 청크가 많으면 처음 한 번은 임베딩에 시간이 걸립니다(이후 캐시).</div>
      </div>`;
    const $r = sel => root.querySelector(sel);
    const updateCount = () => {
      const items = parseLines($r("[data-text]").value);
      const labels = new Set(items.map(i => i.label).filter(Boolean));
      $r("[data-count]").textContent = `${items.length}개${labels.size ? ` · 라벨 ${labels.size}종 (${[...labels].slice(0, 8).join(", ")}${labels.size > 8 ? "…" : ""})` : ""}`;
    };
    $r("[data-text]").addEventListener("input", updateCount);
    root.querySelectorAll(`input[name="src-${id}"]`).forEach(r => r.addEventListener("change", () => {
      const v = root.querySelector(`input[name="src-${id}"]:checked`).value;
      root.querySelectorAll("[data-pane]").forEach(p => (p.hidden = p.dataset.pane !== v));
    }));
    // 예시 데이터
    const presets = await api(`/api/apps/presets${opts.app ? `?app=${opts.app}` : ""}`);
    $r("[data-preset]").innerHTML += presets.map(p => `<option value="${esc(p.name)}">${esc(p.title)} (${p.n})</option>`).join("");
    $r("[data-preset]").addEventListener("change", async e => {
      if (!e.target.value) return;
      const p = await api(`/api/apps/presets/${e.target.value}`);
      $r("[data-text]").value = toLines(opts.labels === "none" ? p.items.map(({ text }) => ({ text })) : p.items);
      root.dispatchEvent(new CustomEvent("preset", { detail: p }));
      updateCount();
    });
    // 컬렉션
    const cols = await api("/api/collections");
    $r("[data-col]").innerHTML = cols.map(c => `<option value="${c.id}">${esc(c.name)} (문서 ${c.n_documents})</option>`).join("") || '<option value="">컬렉션 없음</option>';
    // 작업 맥락의 컬렉션을 기본으로 (이 화면들은 직접 입력이 기본이라 맥락 줄은 띄우지 않는다)
    const ctxCol = Ctx.get().col;
    if (ctxCol && cols.some(c => String(c.id) === ctxCol)) $r("[data-col]").value = ctxCol;
    const loadSets = async () => {
      const cid = $r("[data-col]").value;
      if (!cid) return;
      const d = await api(`/api/collections/${cid}`);
      $r("[data-cs]").innerHTML = d.chunk_sets.filter(c => c.status === "ready").map(c => `<option value="${c.id}">#${c.id} ${esc(c.name)} (${c.n_chunks})</option>`).join("") || '<option value="">청크 세트 없음</option>';
    };
    $r("[data-col]").addEventListener("change", loadSets);
    $r("[data-unit]").addEventListener("change", e => { $r("[data-cs-wrap]").hidden = e.target.value !== "chunk"; });
    await loadSets();

    return {
      get() {
        const v = root.querySelector(`input[name="src-${id}"]:checked`).value;
        if (v === "texts") return { type: "texts", items: parseLines($r("[data-text]").value) };
        return { type: "collection", collection_id: +$r("[data-col]").value || null, unit: $r("[data-unit]").value, chunk_set_id: +$r("[data-cs]").value || null };
      },
      setText(items) { $r("[data-text]").value = toLines(items); updateCount(); },
      root,
    };
  }

  // 임베딩 모델 + Matryoshka 차원
  async function modelPicker(modelSel, dimSel) {
    await fillModelSelect(modelSel, { preferred: [] });
    const fill = () => fillDimSelect(modelSel, dimSel);
    modelSel.addEventListener("change", fill);
    fill();
    return () => ({ model_id: +modelSel.value, truncate_dim: dimSel.value ? +dimSel.value : null });
  }

  // 작업 실행 → 진행률 표시 → 결과
  async function run(btn, box, path, body) {
    const job = await busy(btn, () => api(path, { method: "POST", body }));
    box.hidden = false;
    btn.disabled = true;
    try {
      const done = await pollJob(job.id, j => { box.innerHTML = ui.jobProgress(j); }, 700);
      if (done.status !== "done") { ui.error(box, done.status === "cancelled" ? "취소했습니다." : (done.error || done.status)); return null; }
      box.hidden = true;
      return done.result;
    } finally { btn.disabled = false; }
  }

  return { sourcePicker, modelPicker, run, parseLines };
})();
