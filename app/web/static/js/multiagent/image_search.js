// multiagent/image_search.html 화면 스크립트 — 사진(+ 질문)으로 멀티모달 인덱스 검색(MA1)
$("#i-file").addEventListener("change", () => {
  const f = $("#i-file").files[0];
  $("#i-preview").innerHTML = f ? html`<div class="thumbs"><figure><img src="${URL.createObjectURL(f)}" alt="올린 사진"></figure></div>` : "";
});
$("#i-run").onclick = e => {
  const f = $("#i-file").files[0];
  if (!f) return toast("사진을 고르세요", "err");
  const form = new FormData();
  form.append("collection_id", $("#i-col").value);
  form.append("image", f);
  form.append("question", $("#i-q").value);
  busy(e.target, () => api("/api/multiagent/image-search", { method: "POST", form }))
    .then(r => {
      $("#i-out").innerHTML = html`<div class="small muted">인덱스 #${r.index_id} · ${r.model}${r.with_question ? " · 사진 + 질문" : " · 사진만"}</div>
        <div class="table-wrap"><table><tr><th>#</th><th>점수</th><th>청크</th></tr>${html.join(r.results.map(x => html`<tr><td class="small">${x.rank}</td><td class="small">${x.score}</td>
          <td class="small">${x.media ? html`<div class="thumbs"><figure><img src="${x.media.url}" alt="검색된 그림 ${x.rank}"></figure></div>` : ""}<div>${x.text}</div></td></tr>`), "")}</table></div>`;
    }).catch(err => ui.error($("#i-out"), err));
};
setupCollectionPickers({ col: $("#i-col") }).catch(() => {});
