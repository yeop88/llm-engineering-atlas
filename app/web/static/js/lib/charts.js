// 벤치마크 결과 시각화 (Chart.js 4.5.1, benchmark.html 에서 cdnjs + SRI 로 로드)
// 원칙: 색은 모델(엔티티)을 따라가고 순위로 다시 칠하지 않는다 · 축은 하나 · 가는 마크 · 표(결과 테이블)가 항상 함께 있다.

const BenchCharts = (() => {
  const instances = [];
  let last = null; // 다크/라이트 전환 시 다시 그리기 위한 마지막 입력
  let lastProjection = null;
  const projInstances = []; // 임베딩 지도 차트 (벤치마크 차트와 별도로 관리)

  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const tokens = () => ({
    series: Array.from({ length: 8 }, (_, i) => css(`--series-${i + 1}`)),
    other: css("--series-other"),
    text: css("--text"),
    muted: css("--muted"),
    grid: css("--chart-grid"),
    axis: css("--chart-axis"),
    panel: css("--panel"),
    border: css("--border"),
  });
  const alpha = (hex, a) => {
    const n = parseInt(hex.replace("#", ""), 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
  };
  const shortName = id => id.split("/").pop();

  // "568M", "1.1B", "740M (텍스트 270M)" → 백만 단위 숫자 (괄호 안 텍스트 경로 값이 있으면 그것을 사용)
  function paramsM(str) {
    if (!str) return null;
    const inner = /텍스트\s*([\d.]+)\s*([MB])/i.exec(str);
    const m = inner || /([\d.]+)\s*([MB])/i.exec(str);
    if (!m) return null;
    return Number(m[1]) * (m[2].toUpperCase() === "B" ? 1000 : 1);
  }

  function baseOptions(t) {
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = 12;
    Chart.defaults.color = t.muted;
    Chart.defaults.borderColor = t.grid;
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 250 },
      plugins: {
        legend: { position: "top", align: "start", labels: { color: t.text, boxWidth: 10, boxHeight: 10, useBorderRadius: true, borderRadius: 3, padding: 14 } },
        tooltip: {
          backgroundColor: t.panel, titleColor: t.text, bodyColor: t.text, borderColor: t.border, borderWidth: 1,
          padding: 10, cornerRadius: 8, boxPadding: 4, usePointStyle: true,
        },
      },
    };
  }
  const axis = (t, extra = {}) => ({
    grid: { color: t.grid, lineWidth: 1, drawTicks: false },
    border: { color: t.axis },
    ticks: { color: t.muted, padding: 6 },
    ...extra,
  });

  // 점 옆에 이름을 그리는 플러그인 (dataset.directLabels 가 켜진 데이터셋만 → 선택적 직접 라벨)
  const directLabels = {
    id: "directLabels",
    afterDatasetsDraw(chart) {
      const { ctx } = chart;
      const t = tokens();
      ctx.save();
      ctx.font = `600 11.5px ${Chart.defaults.font.family}`;
      ctx.fillStyle = t.text;
      ctx.textBaseline = "middle";
      ctx.textAlign = "left";
      const area = chart.chartArea;
      const hit = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
      // 겹침 방지: 이미 그린 라벨 + 모든 점(원)의 영역을 장애물로 둔다
      const placed = [];
      chart.data.datasets.forEach((ds, di) => {
        if (chart.getDatasetMeta(di).hidden) return;
        chart.getDatasetMeta(di).data.forEach((el, i) => {
          const r = (ds.data[i]?.r || 4) + 2;
          placed.push({ x: el.x - r, y: el.y - r, w: 2 * r, h: 2 * r, self: `${di}:${i}` });
        });
      });
      chart.data.datasets.forEach((ds, di) => {
        if (!ds.directLabels || chart.getDatasetMeta(di).hidden) return;
        chart.getDatasetMeta(di).data.forEach((el, i) => {
          const label = ds.data[i]?.label;
          if (!label) return;
          const r = (ds.data[i].r || 4) + 4;
          const w = ctx.measureText(label).width, h = 14;
          // 오른쪽 → 왼쪽 → 위 → 아래 순으로 빈 자리를 찾고, 없으면 생략(툴팁과 표가 값을 보여 줌)
          const candidates = [
            { x: el.x + r, y: el.y - h / 2 }, { x: el.x - r - w, y: el.y - h / 2 },
            { x: el.x - w / 2, y: el.y - r - h }, { x: el.x - w / 2, y: el.y + r },
          ].map(c => ({ ...c, w, h }));
          // 위쪽은 layout.padding 여백까지 허용 (축 최댓값에 붙은 점의 라벨이 사라지지 않게)
          const spot = candidates.find(c => c.x >= area.left && c.x + w <= area.right && c.y >= area.top - 12 && c.y + h <= area.bottom
            && !placed.some(p => p.self !== `${di}:${i}` && hit(p, c)));
          if (!spot) return;
          placed.push(spot);
          ctx.fillText(label, spot.x, spot.y + h / 2);
        });
      });
      ctx.restore();
    },
  };

  // 같은 결과 안에서는 모델 → 색이 고정 (결과 목록 순서 기준, 9번째부터는 '기타' 회색)
  function colorMap(results, t) {
    const map = {};
    results.forEach((r, i) => (map[r.hf_id] = i < 8 ? t.series[i] : t.other));
    return map;
  }

  function make(canvas, config) {
    const c = new Chart(canvas, config);
    instances.push(c);
    return c;
  }
  function destroyAll() { while (instances.length) instances.pop().destroy(); }

  // ── 1. 성능 vs 속도 버블 ─────────────────────────────────────────────────
  function bubble(canvas, ok, primary, params, t) {
    const pts = ok.map(r => ({
      x: r.texts_per_second || 0.1, y: r.metrics[primary], hf: r.hf_id,
      pm: params[r.hf_id] ?? null,
    }));
    const maxP = Math.max(1, ...pts.map(p => p.pm || 0));
    pts.forEach(p => (p.r = p.pm ? 5 + 13 * Math.sqrt(p.pm / maxP) : 6));
    // 파레토 최적: 자신보다 빠르고 동시에 더 정확한 모델이 없는 점
    const frontier = new Set(pts.filter(p => !pts.some(q => q !== p && q.x >= p.x && q.y >= p.y && (q.x > p.x || q.y > p.y))).map(p => p.hf));
    const ds = (label, color, filterFn, labels) => ({
      label, directLabels: labels,
      data: pts.filter(filterFn).map(p => ({ ...p, label: labels ? shortName(p.hf) : null })),
      backgroundColor: alpha(color, 0.75), borderColor: t.panel, borderWidth: 2, hoverBorderWidth: 2,
      clip: 24, // 축 끝(100% 등)에 걸친 원이 잘리지 않게
    });
    const datasets = [ds("파레토 최적", t.series[0], p => frontier.has(p.hf), true)];
    if (pts.length > frontier.size) datasets.push(ds("기타 모델", t.other, p => !frontier.has(p.hf), false));
    const o = baseOptions(t);
    const isPct = primary !== "spearman" && primary !== "pearson";
    // 원이 축 가장자리에서 잘리지 않도록 양쪽에 여유를 둔다 (x 는 로그 축이라 배수로)
    const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
    const ySpan = Math.max(0.02, Math.max(...ys) - Math.min(...ys));
    const yMax = Math.max(...ys) + ySpan * 0.15;
    make(canvas, {
      type: "bubble",
      data: { datasets },
      plugins: [directLabels],
      options: {
        ...o,
        interaction: { mode: "nearest", intersect: false },
        layout: { padding: { right: 8, top: 30 } },
        scales: {
          x: axis(t, { type: "logarithmic", min: Math.min(...xs) / 1.6, max: Math.max(...xs) * 1.6,
            title: { display: true, text: "처리 속도 (texts/s, 로그 축) → 빠름", color: t.muted },
            ticks: { color: t.muted, callback: v => (/^[125]0*$/.test(String(v)) ? v : "") } }), // 1·2·5 단위 눈금만 표시
          y: axis(t, { min: Math.min(...ys) - ySpan * 0.15, max: isPct ? Math.min(1, yMax) : yMax,
            title: { display: true, text: `${primary}${isPct ? " (%)" : ""} → 정확`, color: t.muted },
            ticks: { color: t.muted, callback: v => (isPct ? Math.round(v * 100) : v.toFixed(2)) } }),
        },
        plugins: {
          ...o.plugins,
          tooltip: { ...o.plugins.tooltip, callbacks: {
            title: items => items[0].raw.hf,
            label: c => [`${primary}: ${isPct ? (c.raw.y * 100).toFixed(1) + "%" : c.raw.y.toFixed(4)}`,
              `속도: ${c.raw.x} texts/s`, `파라미터: ${c.raw.pm ? (c.raw.pm >= 1000 ? (c.raw.pm / 1000).toFixed(1) + "B" : c.raw.pm + "M") : "?"}`],
          } },
        },
      },
    });
  }

  // ── 2. 언어 그룹별 가로 막대 ─────────────────────────────────────────────
  function groupBars(canvas, ok, primary, t) {
    const groups = [...new Set(ok.flatMap(r => Object.keys(r.by_group || {})))];
    make(canvas, {
      type: "bar",
      data: {
        labels: ok.map(r => shortName(r.hf_id)),
        datasets: groups.map((g, i) => ({
          label: `${g} (n=${ok[0].by_group[g]?.n ?? "?"})`,
          data: ok.map(r => r.by_group[g]?.[primary] ?? null),
          backgroundColor: t.series[i % 8],
          borderRadius: 4, borderSkipped: "start", maxBarThickness: 10, barPercentage: 0.9, categoryPercentage: 0.82,
        })),
      },
      options: {
        ...baseOptions(t),
        indexAxis: "y",
        interaction: { mode: "index", axis: "y", intersect: false },
        scales: {
          x: axis(t, { min: 0, max: 1, ticks: { color: t.muted, callback: v => `${Math.round(v * 100)}` }, title: { display: true, text: `${primary} (%)`, color: t.muted } }),
          y: axis(t, { grid: { display: false }, ticks: { color: t.text } }),
        },
        plugins: { ...baseOptions(t).plugins, tooltip: { ...baseOptions(t).plugins.tooltip, callbacks: {
          label: c => `${c.dataset.label}: ${c.raw == null ? "-" : (c.raw * 100).toFixed(1) + "%"}`,
        } } },
      },
    });
    return groups.length;
  }

  // ── 3. Recall@k 선 그래프 ────────────────────────────────────────────────
  function recallLines(canvas, ok, colors, t) {
    const ks = [1, 3, 5, 10].filter(k => ok[0].metrics[`recall@${k}`] != null);
    make(canvas, {
      type: "line",
      data: {
        labels: ks.map(k => `@${k}`),
        datasets: ok.map(r => ({
          label: shortName(r.hf_id),
          data: ks.map(k => r.metrics[`recall@${k}`]),
          borderColor: colors[r.hf_id], backgroundColor: colors[r.hf_id],
          borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, pointBorderColor: t.panel, pointBorderWidth: 2,
          borderJoinStyle: "round", borderCapStyle: "round", tension: 0,
        })),
      },
      options: {
        ...baseOptions(t),
        interaction: { mode: "index", intersect: false },
        scales: {
          x: axis(t, { title: { display: true, text: "상위 k개", color: t.muted } }),
          y: axis(t, { min: Math.max(0, Math.floor(Math.min(...ok.flatMap(r => ks.map(k => r.metrics[`recall@${k}`]))) * 20) / 20 - 0.05), max: 1, ticks: { color: t.muted, callback: v => `${Math.round(v * 100)}` }, title: { display: true, text: "Recall (%)", color: t.muted } }),
        },
        plugins: { ...baseOptions(t).plugins, tooltip: { ...baseOptions(t).plugins.tooltip, itemSort: (a, b) => b.raw - a.raw, callbacks: {
          label: c => `${c.dataset.label}: ${(c.raw * 100).toFixed(1)}%`,
        } } },
      },
    });
  }

  // ── 4. 모델 프로필 레이더 (최대 3개 — 겹치는 면적은 모든 쌍이 구분돼야 하므로) ─────
  function radar(canvas, ok, picked, colors, sts, t) {
    const maxSpeed = Math.max(...ok.map(r => r.texts_per_second || 0));
    const cross = r => {
      const v = ["ko→en", "en→ko"].map(g => r.by_group?.[g]?.["ndcg@10"]).filter(x => x != null);
      return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
    };
    const axes = [
      ["nDCG@10", r => r.metrics["ndcg@10"]],
      ["Recall@1", r => r.metrics["recall@1"]],
      ["MRR@10", r => r.metrics["mrr@10"]],
      ...(ok.some(r => cross(r) != null) ? [["교차언어", cross]] : []),
      ...(sts ? [["STS Spearman", r => sts[r.hf_id] ?? null]] : []),
      ["속도 (상대)", r => (maxSpeed ? (r.texts_per_second || 0) / maxSpeed : null)],
    ];
    make(canvas, {
      type: "radar",
      data: {
        labels: axes.map(a => a[0]),
        datasets: ok.filter(r => picked.has(r.hf_id)).map(r => ({
          label: shortName(r.hf_id),
          data: axes.map(a => a[1](r)),
          borderColor: colors[r.hf_id], backgroundColor: alpha(colors[r.hf_id], 0.1),
          borderWidth: 2, pointRadius: 4, pointBorderColor: t.panel, pointBorderWidth: 2, pointBackgroundColor: colors[r.hf_id],
        })),
      },
      options: {
        ...baseOptions(t),
        scales: { r: { min: 0, max: 1, angleLines: { color: t.grid }, grid: { color: t.grid }, pointLabels: { color: t.text, font: { size: 12 } },
          ticks: { display: false, stepSize: 0.25 } } },
        plugins: { ...baseOptions(t).plugins, tooltip: { ...baseOptions(t).plugins.tooltip, callbacks: {
          label: c => `${c.dataset.label}: ${c.raw == null ? "데이터 없음" : (c.raw * 100).toFixed(1) + "%"}`,
        } } },
      },
    });
  }

  // ── 5. STS 작은 다중 산점도 (모델별 1개 — 모델 수가 많아도 색 구분이 필요 없음) ────
  function stsMultiples(container, ok, t) {
    container.innerHTML = ok.map((r, i) => `<div class="mini"><h4 title="${esc(r.hf_id)}">${esc(shortName(r.hf_id))} <span class="muted">ρ=${r.metrics.spearman.toFixed(3)}</span></h4>
      <div class="chart-box h-sm"><canvas id="sts-mini-${i}" aria-label="${esc(r.hf_id)} STS 산점도"></canvas></div></div>`).join("");
    const lo = Math.min(...ok.flatMap(r => r.per_pair.map(p => p.cosine)));
    ok.forEach((r, i) => {
      const o = baseOptions(t);
      make(container.querySelector(`#sts-mini-${i}`), {
        type: "scatter",
        data: { datasets: [{
          label: "문장쌍", data: r.per_pair.map(p => ({ x: p.gold, y: p.cosine, p })),
          backgroundColor: alpha(t.series[0], 0.8), borderColor: t.panel, borderWidth: 2, pointRadius: 4.5, pointHoverRadius: 6,
          clip: 8, // 정답 0점·5점(축 끝) 점이 잘리지 않게
        }] },
        options: {
          ...o,
          layout: { padding: { right: 8, top: 6 } },
          interaction: { mode: "nearest", intersect: false },
          scales: {
            x: axis(t, { min: 0, max: 5, ticks: { color: t.muted, stepSize: 1 }, title: { display: true, text: "정답 점수", color: t.muted } }),
            y: axis(t, { suggestedMin: Math.floor(lo * 10) / 10, max: 1, title: { display: true, text: "코사인", color: t.muted } }),
          },
          plugins: { legend: { display: false }, tooltip: { ...o.plugins.tooltip, callbacks: {
            title: items => `정답 ${items[0].raw.p.gold} · 코사인 ${items[0].raw.p.cosine.toFixed(3)}`,
            label: c => [c.raw.p.s1, c.raw.p.s2].map(s => (s.length > 40 ? s.slice(0, 40) + "…" : s)),
          } } },
        },
      });
    });
  }

  // ── 6. Matryoshka 차원별 성능 곡선 ──────────────────────────────────────
  function dimSweep(canvas, tableBox, ok, primary, colors, mrlSet, mode, t) {
    const withSweep = ok.filter(r => (r.dim_sweep || []).length > 1);
    const dims = [...new Set(withSweep.flatMap(r => r.dim_sweep.map(s => s.dim)))].sort((a, b) => b - a);
    const isPct = primary !== "spearman" && primary !== "pearson";
    const valueOf = (r, d) => {
      const s = r.dim_sweep.find(x => x.dim === d);
      if (!s) return null;
      const v = s.metrics[primary];
      if (mode === "abs") return v;
      const full = r.dim_sweep[0].metrics[primary]; // dim_sweep[0] = 전체 차원
      return full ? v / full : null;
    };
    const fmt = v => (v == null ? "-" : mode === "rel" ? `${(v * 100).toFixed(1)}%` : isPct ? `${(v * 100).toFixed(1)}` : v.toFixed(3));
    make(canvas, {
      type: "line",
      data: {
        // x 를 숫자(로그) 축으로 두어 모델마다 차원 목록이 달라도 선이 끊기지 않게 한다
        datasets: withSweep.map(r => {
          const mrl = mrlSet.has(r.hf_id);
          return {
            label: `${shortName(r.hf_id)}${mrl ? "" : " (MRL 학습 안 됨)"}`,
            data: r.dim_sweep.map(s => ({ x: s.dim, y: valueOf(r, s.dim) })),
            borderColor: colors[r.hf_id], backgroundColor: colors[r.hf_id],
            borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, pointBorderColor: t.panel, pointBorderWidth: 2,
            pointStyle: mrl ? "circle" : "rectRot", // MRL 여부는 모양으로도 구분 (색만으로 구분하지 않음)
            spanGaps: false, tension: 0, hf: r.hf_id,
          };
        }),
      },
      options: {
        ...baseOptions(t),
        interaction: { mode: "nearest", axis: "x", intersect: false }, // 가장 가까운 차원의 모든 모델 값
        scales: {
          x: axis(t, {
            type: "logarithmic", reverse: true, min: Math.min(...dims) / 1.15, max: Math.max(...dims) * 1.15,
            afterBuildTicks: ax => { ax.ticks = dims.map(v => ({ value: v })); }, // 실제 평가한 차원만 눈금으로
            ticks: { color: t.muted, callback: v => v },
            title: { display: true, text: "임베딩 차원 (왼쪽 = 큼, 오른쪽으로 갈수록 축소 · 로그 축)", color: t.muted },
          }),
          y: axis(t, {
            ...(mode === "abs" && isPct ? { max: 1 } : {}),
            ticks: { color: t.muted, callback: v => (mode === "rel" || isPct ? `${Math.round(v * 100)}` : v.toFixed(2)) },
            title: { display: true, text: mode === "rel" ? "전체 차원 대비 유지율 (%)" : `${primary}${isPct ? " (%)" : ""}`, color: t.muted },
          }),
        },
        plugins: { ...baseOptions(t).plugins, tooltip: { ...baseOptions(t).plugins.tooltip, itemSort: (a, b) => (b.raw.y ?? -1) - (a.raw.y ?? -1), callbacks: {
          title: items => `${items[0].raw.x}차원 · 벡터당 ${fmtBytes(items[0].raw.x * 4)} (float32)`,
          label: c => `${c.dataset.label}: ${fmt(c.raw.y)}`,
        } } },
      },
    });
    // 표 보기 (차트와 같은 값)
    tableBox.innerHTML = `<details><summary>표로 보기</summary><div class="table-wrap" style="margin-top:8px"><table>
      <tr><th>모델</th>${dims.map(d => `<th class="num">${d}</th>`).join("")}</tr>
      ${withSweep.map(r => `<tr><td class="mono small">${esc(r.hf_id)}</td>${dims.map(d => `<td class="num">${fmt(valueOf(r, d))}</td>`).join("")}</tr>`).join("")}
    </table></div></details>`;
  }

  // ── 7. 임베딩 2D 지도 (플레이그라운드) ─────────────────────────────────────
  // 그룹 색: 서로 겹치는 산점도는 모든 색 쌍이 구분돼야 하므로 3개까지만 색, 나머지는 회색 + 모양으로 구분
  const SHAPES = ["circle", "triangle", "rect", "rectRot", "star", "crossRot"];
  function renderProjection(root, res, { showLabels = false } = {}) {
    lastProjection = { root, res, opts: { showLabels } };
    projInstances.splice(0).forEach(c => c.destroy());
    const t = tokens();
    const groupNames = [...new Set(res.groups)];
    const groupStyle = Object.fromEntries(groupNames.map((g, i) => [g, {
      color: i < 3 ? t.series[i] : t.other, shape: i < 3 ? "circle" : SHAPES[(i - 2) % SHAPES.length],
    }]));
    const okRes = res.results.filter(r => !r.error);
    root.innerHTML = `<div class="multiples" style="grid-template-columns:repeat(auto-fill,minmax(340px,1fr))">${res.results.map((r, mi) => `
      <div class="card chart-card"><div class="row between" style="flex-wrap:nowrap"><h3 class="mono" style="word-break:break-all">${esc(r.hf_id)}</h3>${r.error ? "" : '<button class="btn sm png-btn" title="PNG로 저장">PNG</button>'}</div>
      ${r.error ? `<div class="errbox">${esc(r.error)}</div>` : `
        <p class="chart-sub">${r.dim}차원 → 2D ${res.method.toUpperCase()}${r.explained_variance != null ? ` · 두 축이 전체 분산의 ${(r.explained_variance * 100).toFixed(0)}% 설명` : ""}</p>
        ${warningsHtml(r.warnings)}
        <div class="chart-box" style="height:340px"><canvas id="proj-${mi}" role="img" aria-label="${esc(r.hf_id)} 임베딩 2D 지도"></canvas></div>
        ${r.alignment ? alignmentHtml(r.alignment) : ""}`}
      </div>`).join("")}</div>
      ${okRes.some(r => r.alignment) ? alignmentTable(okRes) : ""}`;

    const pairLines = {
      id: "pairLines",
      beforeDatasetsDraw(chart) {
        const al = chart.options.plugins.pairLines?.pairs;
        if (!al) return;
        const { ctx } = chart;
        const pos = idx => {
          const ds = chart.data.datasets.findIndex(d => d.data.some(p => p.i === idx));
          const el = chart.getDatasetMeta(ds).data[chart.data.datasets[ds].data.findIndex(p => p.i === idx)];
          return el ? { x: el.x, y: el.y } : null;
        };
        ctx.save();
        ctx.strokeStyle = t.axis;
        ctx.lineWidth = 1;
        al.forEach(([a, b]) => {
          const p = pos(a), q = pos(b);
          if (!p || !q) return;
          ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke();
        });
        ctx.restore();
      },
    };

    res.results.forEach((r, mi) => {
      if (r.error) return;
      const o = baseOptions(t);
      const short = s => (s.length > 14 ? s.slice(0, 14) + "…" : s);
      const c = new Chart(root.querySelector(`#proj-${mi}`), {
        type: "scatter",
        data: {
          datasets: groupNames.map(g => ({
            label: g, directLabels: showLabels,
            data: r.points.map((p, i) => ({ x: p[0], y: p[1], i, text: res.texts[i], label: showLabels ? short(res.texts[i]) : null }))
              .filter(p => res.groups[p.i] === g),
            backgroundColor: groupStyle[g].color, borderColor: t.panel, borderWidth: 2,
            pointStyle: groupStyle[g].shape, pointRadius: 5, pointHoverRadius: 7, clip: 10,
          })),
        },
        plugins: [pairLines, directLabels],
        options: {
          ...o,
          layout: { padding: 8 },
          interaction: { mode: "nearest", intersect: false },
          scales: {
            x: axis(t, { min: -1.1, max: 1.1, ticks: { display: false }, title: { display: true, text: res.method === "pca" ? "PC1" : "t-SNE 1", color: t.muted } }),
            y: axis(t, { min: -1.1, max: 1.1, ticks: { display: false }, title: { display: true, text: res.method === "pca" ? "PC2" : "t-SNE 2", color: t.muted } }),
          },
          plugins: {
            ...o.plugins,
            legend: { ...o.plugins.legend, display: groupNames.length > 1, labels: { ...o.plugins.legend.labels, usePointStyle: true } },
            pairLines: { pairs: r.alignment?.pairs ?? null },
            tooltip: { ...o.plugins.tooltip, callbacks: {
              title: items => `#${items[0].raw.i + 1} · ${items[0].dataset.label}`,
              label: item => (item.raw.text.length > 60 ? item.raw.text.slice(0, 60) + "…" : item.raw.text),
            } },
          },
        },
      });
      projInstances.push(c);
    });
  }

  function alignmentHtml(a) {
    return `<div class="kv small" style="margin-top:10px">
      <div>의미 쌍 코사인 (평균)</div><div><b>${a.pair_cosine.toFixed(3)}</b></div>
      <div>다른 문장과 코사인</div><div>${a.other_cosine.toFixed(3)}</div>
      <div>차이 (클수록 좋음)</div><div><b>${a.margin.toFixed(3)}</b></div>
      <div>짝 찾기 정확도</div><div>${esc(a.groups[0])}→${esc(a.groups[1])} ${(a.top1_a_to_b * 100).toFixed(0)}% · ${esc(a.groups[1])}→${esc(a.groups[0])} ${(a.top1_b_to_a * 100).toFixed(0)}%</div>
    </div>`;
  }
  function alignmentTable(rs) {
    const rows = rs.filter(r => r.alignment);
    const best = Math.max(...rows.map(r => r.alignment.margin));
    return `<div class="card chart-card" style="margin-top:16px"><h3>의미 쌍 정렬도 비교</h3>
      <p class="chart-sub">원래 차원에서 계산한 값입니다(2D 투영 전). 같은 뜻의 문장끼리 가깝고(쌍 코사인↑) 다른 문장과는 멀수록(차이↑) 좋습니다.</p>
      <div class="table-wrap"><table><tr><th>모델</th><th class="num">쌍 코사인</th><th class="num">다른 문장</th><th class="num">차이</th><th class="num">짝 찾기 A→B</th><th class="num">짝 찾기 B→A</th></tr>
      ${rows.map(r => { const a = r.alignment; return `<tr><td class="mono small">${esc(r.hf_id)}</td><td class="num">${a.pair_cosine.toFixed(3)}</td><td class="num">${a.other_cosine.toFixed(3)}</td>
        <td class="num ${a.margin === best && rows.length > 1 ? "best" : ""}">${a.margin.toFixed(3)}</td><td class="num">${(a.top1_a_to_b * 100).toFixed(0)}%</td><td class="num">${(a.top1_b_to_a * 100).toFixed(0)}%</td></tr>`; }).join("")}
      </table></div></div>`;
  }

  // ── 8. 내보내기: 카드 안의 차트(여러 개여도)를 배경색을 깐 PNG 한 장으로 ─────────
  function cardToCanvas(cardEl, scale = 2) {
    const t = tokens();
    const canvases = [...cardEl.querySelectorAll("canvas")];
    if (!canvases.length) return null;
    const base = cardEl.getBoundingClientRect();
    const boxes = canvases.map(c => ({ c, r: c.getBoundingClientRect() }));
    const h4s = [...cardEl.querySelectorAll(".mini h4")]; // 작은 다중 차트의 제목도 그린다
    // 부제목·선택 상자 등은 그리지 않으므로, 첫 차트(또는 작은 차트 제목)를 카드 제목 바로 아래로 끌어올린다
    const top = Math.min(...boxes.map(b => b.r.top), ...h4s.map(h => h.getBoundingClientRect().top)) - base.top;
    const shift = 42 - top;
    const width = base.width, height = Math.max(...boxes.map(b => b.r.bottom)) - base.top + shift + 12;
    const title = cardEl.querySelector("h3")?.textContent.trim() || "";
    const out = document.createElement("canvas");
    out.width = width * scale; out.height = (height + 8) * scale;
    const ctx = out.getContext("2d");
    ctx.scale(scale, scale);
    ctx.fillStyle = t.panel; ctx.fillRect(0, 0, width, height + 8);
    ctx.fillStyle = t.text; ctx.font = `600 14px ${getComputedStyle(document.body).fontFamily}`; ctx.textBaseline = "top";
    ctx.fillText(title, 16, 14);
    ctx.font = `600 12px ${getComputedStyle(document.body).fontFamily}`;
    h4s.forEach(h => { const r = h.getBoundingClientRect(); ctx.fillText(h.textContent.trim(), r.left - base.left, r.top - base.top + shift); });
    boxes.forEach(({ c, r }) => ctx.drawImage(c, r.left - base.left, r.top - base.top + shift, r.width, r.height));
    return out;
  }
  function downloadCardPng(cardEl, filename) {
    const c = cardToCanvas(cardEl);
    if (!c) return;
    const a = document.createElement("a");
    a.href = c.toDataURL("image/png");
    a.download = filename;
    a.click();
  }
  // 카드 제목 옆 PNG 버튼 (이벤트 위임)
  document.addEventListener("click", e => {
    const b = e.target.closest(".png-btn");
    if (!b) return;
    const card = b.closest(".card");
    const name = (card.querySelector("h3")?.textContent || "chart").trim().replace(/[^\w가-힣@-]+/g, "_").slice(0, 60);
    downloadCardPng(card, `${name}.png`);
  });

  // ── 9. 이력 추세 (같은 데이터셋 실행들의 모델별 대표 지표) ─────────────────
  const trendInstances = [];
  function renderTrend(canvas, data) {
    trendInstances.splice(0).forEach(c => c.destroy());
    const t = tokens();
    const runIds = [...new Set(data.series.flatMap(s => s.points.map(p => p.run_id)))].sort((a, b) => a - b);
    const when = Object.fromEntries(data.series.flatMap(s => s.points.map(p => [p.run_id, p.created_at])));
    const label = id => `#${id} ${new Date(when[id]).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}`;
    const primary = data.primary_metric;
    const isPct = primary !== "spearman" && primary !== "pearson";
    const c = new Chart(canvas, {
      type: "line",
      data: {
        labels: runIds.map(label),
        datasets: data.series.map((s, i) => {
          const color = i < 8 ? t.series[i] : t.other;
          const byRun = Object.fromEntries(s.points.map(p => [p.run_id, p.value]));
          return {
            label: shortName(s.hf_id), data: runIds.map(id => byRun[id] ?? null), spanGaps: true,
            borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 4, pointHoverRadius: 6,
            pointBorderColor: t.panel, pointBorderWidth: 2, tension: 0,
          };
        }),
      },
      options: {
        ...baseOptions(t),
        interaction: { mode: "index", intersect: false },
        scales: {
          x: axis(t, { ticks: { color: t.muted, maxRotation: 0, autoSkip: true } }),
          y: axis(t, { ...(isPct ? { max: 1 } : {}), ticks: { color: t.muted, callback: v => (isPct ? `${Math.round(v * 100)}` : v.toFixed(2)) },
            title: { display: true, text: `${primary}${isPct ? " (%)" : ""}`, color: t.muted } }),
        },
        plugins: { ...baseOptions(t).plugins, tooltip: { ...baseOptions(t).plugins.tooltip, itemSort: (a, b) => (b.raw ?? -1) - (a.raw ?? -1),
          filter: item => item.raw != null,
          callbacks: { label: c => `${c.dataset.label}: ${isPct ? (c.raw * 100).toFixed(1) + "%" : c.raw.toFixed(4)}` } } },
      },
    });
    trendInstances.push(c);
  }

  // ── 10. 대시보드: 메모리 사용량 · 최근 벤치마크 ─────────────────────────────
  const dashInstances = {};
  function renderMemory(canvas, samples) {
    const t = tokens();
    const labels = samples.map(s => new Date(s.t).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    const series = [["이 앱 프로세스", "process_gb", t.series[0]], ["시스템 전체 사용", "used_gb", t.series[1]]];
    if (dashInstances.mem) {
      dashInstances.mem.data.labels = labels;
      series.forEach(([, key], i) => (dashInstances.mem.data.datasets[i].data = samples.map(s => s[key])));
      dashInstances.mem.update("none");
      return;
    }
    dashInstances.mem = new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: series.map(([label, key, color]) => ({
          label, data: samples.map(s => s[key]), borderColor: color, backgroundColor: alpha(color, 0.1), fill: key === "process_gb",
          borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.2,
        })),
      },
      options: {
        ...baseOptions(t),
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: axis(t, { ticks: { color: t.muted, maxTicksLimit: 6, maxRotation: 0 } }),
          y: axis(t, { min: 0, suggestedMax: samples[0]?.total_gb, ticks: { color: t.muted, callback: v => `${v}GB` } }),
        },
        plugins: { ...baseOptions(t).plugins, tooltip: { ...baseOptions(t).plugins.tooltip, callbacks: { label: c => `${c.dataset.label}: ${c.raw.toFixed(2)} GB` } } },
      },
    });
  }
  function renderLatestBench(canvas, res) {
    const t = tokens();
    dashInstances.bench?.destroy();
    const ok = res.results.filter(r => r.status === "ok");
    const primary = res.primary_metric;
    const isPct = primary !== "spearman" && primary !== "pearson";
    dashInstances.bench = new Chart(canvas, {
      type: "bar",
      data: { labels: ok.map(r => shortName(r.hf_id)), datasets: [{ label: primary, data: ok.map(r => r.metrics[primary]),
        backgroundColor: t.series[0], borderRadius: 4, borderSkipped: "start", maxBarThickness: 14 }] },
      options: {
        ...baseOptions(t),
        indexAxis: "y",
        scales: {
          x: axis(t, { min: isPct ? Math.max(0, Math.floor(Math.min(...ok.map(r => r.metrics[primary])) * 10) / 10 - 0.1) : undefined, max: isPct ? 1 : undefined,
            ticks: { color: t.muted, callback: v => (isPct ? `${Math.round(v * 100)}` : v.toFixed(2)) } }),
          y: axis(t, { grid: { display: false }, ticks: { color: t.text } }),
        },
        plugins: { ...baseOptions(t).plugins, legend: { display: false }, tooltip: { ...baseOptions(t).plugins.tooltip,
          callbacks: { label: c => `${primary}: ${isPct ? (c.raw * 100).toFixed(1) + "%" : c.raw.toFixed(4)}` } } },
      },
    });
  }
  function resetDashboard() { Object.values(dashInstances).forEach(c => c.destroy()); Object.keys(dashInstances).forEach(k => delete dashInstances[k]); }

  // ── 진입점 ──────────────────────────────────────────────────────────────
  async function render(root, res, { stsScores = null, stsTitle = "" } = {}) {
    last = { root, res, opts: { stsScores, stsTitle } };
    destroyAll();
    const t = tokens();
    const ok = res.results.filter(r => r.status === "ok");
    if (!ok.length) { root.innerHTML = ""; return; }
    const primary = res.primary_metric;
    const colors = colorMap(res.results, t);
    const models = await getModels();
    const params = Object.fromEntries(models.map(m => [m.hf_id, paramsM(m.params)]));
    const isRetrieval = res.dataset.type === "retrieval";
    const hasGroups = isRetrieval && ok.some(r => Object.keys(r.by_group || {}).length);
    const hasSweep = ok.some(r => (r.dim_sweep || []).length > 1);
    const mrlSet = new Set(models.filter(m => (m.mrl_dims || []).length || (m.tags || []).includes("matryoshka")).map(m => m.hf_id));

    const card = (title, sub, body, wide = false) =>
      `<div class="card chart-card" ${wide ? 'style="grid-column:1/-1"' : ""}><div class="row between"><h3>${title}</h3><button class="btn sm png-btn" title="이 차트를 PNG로 저장">PNG</button></div><p class="chart-sub">${sub}</p>${body}</div>`;
    let html = `<div class="grid cols-2" style="margin-top:16px">`;
    html += card("성능 vs 속도", `원 크기 = 파라미터 수. 오른쪽 위로 갈수록 빠르고 정확합니다. 파란 원은 파레토 최적(자기보다 빠르면서 더 정확한 모델이 없음)이고, 회색 원은 마우스를 올리면 이름이 보입니다.`,
      `<div class="chart-box h-md"><canvas id="ch-bubble" role="img" aria-label="성능 대 속도 버블 차트"></canvas></div>`, !isRetrieval);
    if (isRetrieval) {
      html += card("Recall@k", "상위 k개 안에 정답이 들어온 비율. 선이 왼쪽부터 높을수록 1위 정확도가 좋습니다. 범례를 눌러 모델을 숨길 수 있습니다.",
        `<div class="chart-box h-md"><canvas id="ch-recall" role="img" aria-label="Recall@k 선 그래프"></canvas></div>`);
    }
    if (hasGroups) {
      const h = Math.max(260, ok.length * 46 + 80);
      html += card(`언어 그룹별 ${primary}`, "막대가 짧은 곳이 그 모델의 약점입니다(특히 교차언어 ko→en / en→ko).",
        `<div class="chart-box" style="height:${h}px"><canvas id="ch-groups" role="img" aria-label="언어 그룹별 막대 차트"></canvas></div>`);
    }
    if (isRetrieval) {
      html += card("모델 프로필", `최대 3개 모델을 골라 비교합니다. 모든 축 0~100%.${stsScores ? ` STS는 최근 '${esc(stsTitle)}' 결과에서 가져왔습니다.` : " STS 벤치마크를 한 번 실행하면 STS 축이 추가됩니다."}`,
        `<div class="picker" id="radar-pick">${ok.map((r, i) => `<label><input type="checkbox" value="${esc(r.hf_id)}" ${i < 3 ? "checked" : ""}>
          <span class="swatch" style="background:${colors[r.hf_id]}"></span>${esc(shortName(r.hf_id))}</label>`).join("")}</div>
         <div class="chart-box h-md"><canvas id="ch-radar" role="img" aria-label="모델 프로필 레이더 차트"></canvas></div>`);
    }
    if (!isRetrieval) {
      html += card("모델별 정답 점수 vs 코사인 유사도", "점이 왼쪽 아래 → 오른쪽 위로 가지런히 놓일수록 모델이 사람의 판단과 비슷하게 유사도를 매깁니다. 점에 마우스를 올리면 문장쌍이 보입니다.",
        `<div class="multiples" id="ch-sts"></div>`, true);
    }
    if (hasSweep) {
      html += card(`차원별 ${primary} (Matryoshka)`,
        "임베딩을 앞에서부터 잘라 차원을 줄였을 때의 성능입니다. 곡선이 평평할수록 저장 공간을 줄여도 성능이 유지됩니다. ◆ 모양은 MRL로 학습되지 않은 모델(카탈로그 기준)로, 잘랐을 때 성능이 크게 떨어질 수 있습니다.",
        `<div class="row" style="margin-bottom:8px"><div class="tabs" id="sweep-mode" style="margin:0;border:none">
           <button data-mode="abs" class="active">절대값</button><button data-mode="rel">전체 차원 대비 %</button></div></div>
         <div class="chart-box h-md"><canvas id="ch-sweep" role="img" aria-label="차원별 성능 선 그래프"></canvas></div><div id="ch-sweep-table" style="margin-top:8px"></div>`, true);
    }
    html += `</div>`;
    root.innerHTML = html;

    bubble(root.querySelector("#ch-bubble"), ok, primary, params, t);
    if (isRetrieval) recallLines(root.querySelector("#ch-recall"), ok, colors, t);
    if (hasGroups) groupBars(root.querySelector("#ch-groups"), ok, primary, t);
    if (isRetrieval) {
      let radarChart = null;
      const draw = () => {
        const picked = new Set($$("#radar-pick input:checked", root).map(i => i.value));
        if (radarChart) { radarChart.destroy(); instances.splice(instances.indexOf(radarChart), 1); }
        radar(root.querySelector("#ch-radar"), ok, picked, colors, stsScores, t);
        radarChart = instances[instances.length - 1];
      };
      root.querySelector("#radar-pick").addEventListener("change", e => {
        const checked = $$("#radar-pick input:checked", root);
        if (checked.length > 3) { e.target.checked = false; toast("레이더는 최대 3개 모델까지 비교합니다"); return; }
        draw();
      });
      draw();
    }
    if (!isRetrieval) stsMultiples(root.querySelector("#ch-sts"), ok, t);
    if (hasSweep) {
      let sweepChart = null;
      const drawSweep = mode => {
        if (sweepChart) { sweepChart.destroy(); instances.splice(instances.indexOf(sweepChart), 1); }
        dimSweep(root.querySelector("#ch-sweep"), root.querySelector("#ch-sweep-table"), ok, primary, colors, mrlSet, mode, t);
        sweepChart = instances[instances.length - 1];
      };
      root.querySelector("#sweep-mode").addEventListener("click", e => {
        const b = e.target.closest("button[data-mode]");
        if (!b) return;
        $$("#sweep-mode button", root).forEach(x => x.classList.toggle("active", x === b));
        drawSweep(b.dataset.mode);
      });
      drawSweep("abs");
    }
  }

  // 테마가 바뀌면 새 색으로 다시 그리기: OS 다크/라이트 전환과 위쪽 바의 ◐ 전환(themechange, lib/shell.js) 둘 다
  function redraw() {
    if (last) render(last.root, last.res, last.opts);
    if (lastProjection) renderProjection(lastProjection.root, lastProjection.res, lastProjection.opts);
  }
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redraw);
  window.addEventListener("themechange", redraw);

  return { render, renderProjection, renderTrend, renderMemory, renderLatestBench, resetDashboard, cardToCanvas, paramsM };
})();
