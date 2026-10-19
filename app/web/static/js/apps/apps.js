// apps/apps.html 화면 스크립트 — 서버 값(AVAILABLE)은 템플릿의 한 줄 설정에서 받는다
const APPS = [
  { key: "recommend", title: "콘텐츠 추천", use: "뉴스·상품·강의·문서 추천, 연관 콘텐츠", how: "좋아요/싫어요와 관심사로 취향 벡터를 만들고 MMR 로 비슷하면서도 겹치지 않게 고릅니다." },
  { key: "classify", title: "텍스트 분류", use: "감성분석, 고객·AS 문의 자동 분류·라우팅, 스팸 판별", how: "라벨 설명만으로 분류(제로샷)하거나, 예시 몇 개로 분류기를 학습해 저장·API 로 씁니다." },
  { key: "cluster", title: "클러스터링", use: "문서 군집화, VOC·리뷰 주제 발굴, 중복 이슈 묶기", how: "K-means·계층·HDBSCAN 으로 묶고 군집별 키워드와 대표 문장을 뽑습니다." },
  { key: "dedup", title: "중복·표절 검사", use: "중복 데이터 제거, 표절·재사용 문장 검사", how: "의미가 거의 같은 텍스트를 그룹으로 묶고, 문장 단위로 원문과 대조해 표절 구간을 찾습니다." },
  { key: "anomaly", title: "이상·신종 탐지", use: "스팸·피싱 필터링, 해킹 징후, 신종 공격 문구 감지", how: "정상 데이터를 학습해 벗어난 텍스트를 찾고, 알려진 유형과 비교해 '새로운 유형'을 가려냅니다." },
  { key: "keywords", title: "키워드·요약", use: "문서 태깅, 검색 색인어, 긴 문서 핵심 문장", how: "형태소 후보 중 문서 의미와 가까운 키워드를 고르고(MMR), 중심 문장으로 추출 요약합니다." },
];
$("#apps").innerHTML = html.join(APPS.filter(a => AVAILABLE.includes(a.key)).map(a => html`<a class="card stack" href="/apps/${a.key}" style="color:inherit;text-decoration:none">
  <h2 class="m-0">${a.title}</h2><div class="small"><b>활용</b> ${a.use}</div><div class="small muted">${a.how}</div></a>`), "");
