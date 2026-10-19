// 모든 맵: 이름 · 설명 · 상태로 거르기 (카드는 서버가 레지스트리로 그린다)
function filterMaps() {
  const words = $("#m-q").value.trim().toLowerCase().split(/\s+/).filter(Boolean), st = $("#m-st").value;
  let shown = 0;
  $$(".map-card").forEach(c => {
    const ok = words.every(w => c.dataset.text.includes(w)) && (!st || c.dataset.st === st);
    c.hidden = !ok;
    shown += ok;
  });
  $("#m-none").hidden = shown > 0;
}
$("#m-q").addEventListener("input", filterMaps);
$("#m-st").addEventListener("change", filterMaps);
