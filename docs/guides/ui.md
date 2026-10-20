# 화면(UI) 가이드

화면을 새로 만들거나 고칠 때 따르는 규칙입니다. 1.0 에서 화면 뼈대를 다시 짜면서 정했고, 규칙 대부분은 테스트(`tests/test_architecture.py` 의 '화면 규칙', `tests/web/test_pages.py`)가 검사합니다.

## 왜 바꿨나 (0.x → 1.0)

| 0.x 의 문제 | 1.0 |
|---|---|
| 위쪽 한 줄 메뉴 13개 + 마우스를 올려야 펼쳐지는 드롭다운(맵 18개). 모바일에서 메뉴만 4줄, 터치로 드롭다운이 불안정 | 왼쪽 **사이드바**(레지스트리로 생성), 좁은 화면은 ☰ 서랍, **Ctrl K 빠른 이동**, **위치 표시** |
| 모든 도구 화면 위에 단계 설명(원리 · 왜 · 어떻게)이 펼쳐져 약 300px — 도구가 아래로 밀림 | 위쪽 바의 **ⓘ 단계 원리** 서랍. 화면 설명은 두 줄로 접고 '더 보기' |
| 컬렉션 · 인덱스 · 평가 세트 · LLM 선택이 12개 화면에 따로 — 화면을 옮길 때마다 다시 고름 | **작업 맥락**(Ctx): 한 번 고르면 모든 화면이 그 값으로 시작, 주소에도 담김 |
| 진행 표시 마크업 10가지, 불러오는 중 표시 4곳, 브라우저 기본 `confirm()` 20곳 | `ui.jobProgress` · `ui.loading` · `ui.empty` · `ui.error` · `ui.confirm` · `ui.choose` |
| 인라인 `style=""` 446곳, 색 하드코딩 | 간격 · 글자 토큰 + 유틸리티 클래스(87곳만 남음 — 대부분 막대 폭처럼 값이 바뀌는 것) |
| 이름표 302개 중 입력란과 연결된 것 0개, ARIA 6곳 | 모든 이름표 연결(`for`/`id`), 메뉴 · 서랍 · 대화상자 ARIA, 포커스 표시 |
| 주소 규칙이 섞임(`/collections`, `/llm`, `/hub`, `/rag/answer`) | `/<단계>/<화면>` · `/<단계>` · `/maps/<맵>` · `/settings/*`, 예전 주소는 308 로 넘김 | <!-- 예전 이름 -->
| 화면 하나를 더하려면 `PAGES` · 레지스트리 · 의미 응용 목록 · 메뉴 코드를 따로 고침 | 레지스트리의 `Page` 한 줄(주소 · 이름 · 템플릿) → 라우트 · 사이드바 · 위치 표시 · 빠른 이동 자동 |
| 다크 모드는 시스템 설정만 | ◐ 로 시스템 · 밝게 · 어둡게 (차트도 다시 그림) |

## 화면 뼈대

```
base.html
├─ 사이드바      app/web/pages.py sidebar() ← 레지스트리(단계 · 화면 · 맵)
├─ 위쪽 바       위치(crumbs) · ⓘ 단계 원리 · ⏳ 작업 · Ctrl K · ◐
├─ 작업 맥락 줄  맥락을 쓰는 화면에서만 보임
├─ 본문          {% block content %}
└─ 대화상자      빠른 이동 · 작업 맥락 · 확인(ui.confirm)
```

동작은 `static/js/lib/shell.js`(사이드바 · 서랍 · 설명 접기 · 테마 · 빠른 이동 · 작업 · 맥락 줄), 공용 함수는 `static/js/lib/common.js`.

## 새 화면 만들기

1. **레지스트리에 화면 한 줄** — `app/stages/registry/maps/<맵>.py` 의 단계 `pages` 에
   `Page("rag_answer", "/rag/answer", "답변 생성", "근거 인용 답변 · 환각 검증", "rag/answer.html")`
   (nav 키 · 주소 · 이름 · 설명 · 템플릿). 라우트 · 사이드바 · 위치 표시 · 빠른 이동 색인이 여기서 만들어집니다. 단계 밖 공통 화면만 `app/web/pages.py` 의 `COMMON_PAGES`.
   - 한 화면이 여러 단계를 다루면(운영 맵: 화면 14개 · 단계 30개) 나머지 단계는 그 화면의 부분을 가리킵니다:
     `Page("evalops_regression", "/evalops/sets#regression", "회귀 실행", "…")` — 템플릿 없이, 주소에 `#<카드 id>`. 라우트 · 사이드바 항목은 만들지 않고, 단계 소개 · 빠른 이동에서 그 카드로 갑니다. 카드에 같은 `id` 를 붙입니다.
   - 사이드바: LLM 맵 단계는 '실험', 그 밖에 화면이 있는 맵(문서 처리 · 보안 · 가드레일 · 평가 · 관측 · 고객 AS 상담)은 '운영 · 서비스'에 맵 하나 = 항목 하나로 묶입니다.
2. **템플릿** `app/web/templates/<단계>/<화면>.html`
   ```jinja
   {% extends "base.html" %}
   {% import "_ui/macros.html" as ui %}
   {% block title %}답변 생성{% endblock %}
   {% block content %}
   {% call ui.page_header("답변 생성") %}한두 줄 설명 — 길면 자동으로 접힙니다.{% endcall %}
   <div class="field"><label for="a-col">컬렉션</label><select id="a-col" data-ctx="col"></select></div>
   …
   {% endblock %}
   {% block scripts %}<script src="{{ url_for('static', path='js/rag/answer.js') }}"></script>{% endblock %}
   ```
3. **화면 스크립트** `app/web/static/js/<단계>/<화면>.js` — 템플릿과 같은 경로. 템플릿에는 서버 값 한 줄 설정(`const MODEL_ID = {{ model_id }};`)만 인라인.
4. **테스트** — `tests/web/test_pages.py` 가 모든 화면이 열리는지 · 링크가 새 주소인지 확인합니다.

## 부품

| 쓸 때 | 쓰는 것 |
|---|---|
| 제목 · 설명 · 동작 버튼 · 뒤로 가기 | `ui.page_header(title, back=(이름, 주소), actions=html, title_id=, badge=, prefix=)` — 모든 화면 필수(테스트) |
| 이름표 + 입력란 | `<label for="x">` + `id="x"`, 또는 `ui.field("x", "이름", '<select id="x">…')`. 체크박스는 `<label><input type="checkbox"> 글</label>`. 체크박스 묶음 제목은 `<span class="field-label">` |
| 맵 흐름의 단계 상자 | `ui.flow_box(key, text=None)` |
| HTML 만들기 (JS) | `` html`<b>${name}</b>` `` — 값은 자동 이스케이프, `html` 결과 · `raw()` · 그 배열은 그대로. 목록은 `` ${items.map(x => html`<li>${x}</li>`)} `` 처럼 배열째 넣거나, 구분자가 있으면 `html.join(items, " · ")`(구분자는 코드에 적은 HTML 이라 그대로). `html` 결과는 객체라 빈 목록도 `\|\|` 에서 참 — 대신 보일 것은 `html.or(목록, html`<tr>…없음</tr>`)`. 손으로 부르는 `esc()` 는 쓰지 않습니다(테스트, 예외: 글자를 먼저 이스케이프한 뒤 `<mark>` 를 끼우고 `raw()` 로 돌려주는 형광펜 함수) |
| HTML 만들 때 주의 | ① `+` 로 이은 결과는 글자열이 되어 다른 `html` 안에서 다시 이스케이프됩니다 — 이을 땐 배열이나 `html` 안에서. ② 속성 조각(`'style="…"'`)도 `` html`style="…"` `` 로. ③ 함수 안 지역 변수 이름을 `html` 로 짓지 않습니다(태그 함수를 가림, 테스트) |
| 불러오는 중 · 빈 화면 · 오류 | `ui.loading(el)` · `ui.empty(el, "인덱스가 없습니다", { href, label })` · `ui.error(el, e)` |
| 백그라운드 작업 | `runJobInto(btn, path, body, box, render)` 또는 `pollJob(id, j => box.innerHTML = ui.jobProgress(j))` — 진행률 · 경과 시간 · 취소가 같은 모양 |
| 삭제 · 되돌릴 수 없는 동작 | `await ui.confirm(글, { ok: "삭제", danger: true })`. 선택지가 여럿이면 `ui.choose(글, [{ label, value, danger }])` → 고른 value 또는 `null`(취소). 브라우저 `confirm()` 금지(테스트) |
| 상세 화면의 대상 이름 | `setCrumb(name)` — 위치 표시 끝에 붙고 목록은 링크가 됨 |
| 알림 | `toast(글, "ok" \| "err")` |

## 작업 맥락 (Ctx)

컬렉션(`col`) · 청크 세트(`cs`) · 인덱스(`idx`) · 평가 세트(`set`) · LLM(`provider` · `model`).

- 입력란에 `data-ctx="col"` 처럼 붙이면 맥락 값으로 시작하고, 바꾸면 맥락에 저장됩니다. 옵션을 나중에 채우는 `<select>` 는 채운 뒤 `applyCtx(el)`.
- 컬렉션 → 인덱스 · 청크 세트 · 평가 세트 묶음은 `setupCollectionPickers({ col, idx, cs, set, onDetail })` 가 맥락까지 처리합니다.
- 주소의 `?col=` · `?cs=` · `?idx=` · `?set=` 가 브라우저에 저장된 값보다 먼저입니다 — 링크로 같은 실험 설정을 공유할 수 있습니다. 상세 화면처럼 주소가 이미 대상을 가리키면 `Ctx.set(patch, { url: false })`.
- 브라우저(localStorage)에만 저장합니다. 막혀 있어도 화면은 기본값으로 동작합니다.
- 맥락을 쓰는 화면에만 위쪽 맥락 줄이 보입니다(의미 응용 화면은 직접 입력이 기본이라 컬렉션 기본값만 씀).

## 스타일

- 색은 `style.css` 의 토큰(`--text` · `--muted` · `--accent` · `--ok` · `--warn` · `--err` …)만. 차트 색은 `--series-*`(바꾸면 색각이상 검증, [시각화](../stages/llm/1-embedding/visualization.md)).
- 다크 테마 값은 `@media (prefers-color-scheme: dark)` 와 `:root[data-theme="dark"]` 두 곳에 같이 있습니다 — 하나를 고치면 둘 다.
- 간격 · 크기는 유틸리티: `mt-1…5` `mb-2` `mb-4` `m-0` `my-1` `my-2` `p-1…3` `gap-1` `gap-2` `gap-4` `grow` `self-end` `items-start` `items-end` `justify-end` `nowrap-row` `w-xs…xl` `pre` `scroll` `scroll-sm/md/lg` `text-right` `bg-code` `min-0`. 인라인 `style=""` 은 값이 바뀌는 것(막대 폭 등)에만 — 늘면 테스트가 실패합니다.
- 화면 폭 900px 이하: 사이드바는 서랍, 2 · 3 · 4열 격자는 1열, 위쪽 바의 글자 버튼은 아이콘만.

## 접근성 점검

- 이름표는 입력란과 연결(테스트), 버튼에는 글자 또는 `aria-label`.
- 메뉴 · 서랍 · 대화상자: `aria-expanded` · `aria-controls` · `aria-current="page"`, Esc 로 닫기, 서랍을 닫으면 연 버튼으로 초점이 돌아감.
- 위험한 확인(`danger`)은 초점이 '취소'에 — Enter 한 번으로 삭제되지 않게.
- 키보드: Ctrl K / `/` 빠른 이동, ↑↓ Enter, 탭 이동 시 `:focus-visible` 표시.
