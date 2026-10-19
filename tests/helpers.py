"""테스트 공용 헬퍼 — 여러 테스트 파일이 같은 것을 따로 정의하던 것(_wait · _model · DOCS)을 한 곳에."""

import time

LAW = """국어기본법
제1조(목적) 이 법은 국어 사용을 촉진하고 국어의 발전과 보전의 기반을 마련함을 목적으로 한다.
제3조(정의) 이 법에서 사용하는 용어의 뜻은 다음과 같다.
제14조(공문서의 작성) ① 공공기관등의 공문서는 어문규범에 맞추어 한글로 작성하여야 한다.
② 공문서에 쓰는 한글 및 한자 등의 표기에 관하여 필요한 사항은 대통령령으로 정한다.
제14조의2(공공언어 개선) 공공기관등은 공공언어의 개선을 위하여 노력하여야 한다.
【주문】
피고인을 징역 1년에 처한다.
【이유】
피고인은 등록 없이 해외직구 물품을 판매하였다."""
DOCS = {
    "법령.txt": LAW,
    "보도자료.txt": "관세청은 7월 1일부터 해외직구 구매대행업체 등록제를 시행한다. 등록하지 않은 업체는 통관이 제한된다.",
    "AS안내.md": "# 제품 AS 안내\n세탁기 배수가 안 될 때는 배수 필터를 청소하세요. 냉장고 소음은 수평 조절로 줄일 수 있습니다.",
}
EVIDENCE = "배수 필터를 청소하세요"


def wait_job(client, job, steps: int = 400):
    """백그라운드 작업이 끝날 때까지 기다린다(최대 steps × 0.05초)."""
    for _ in range(steps):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] not in ("pending", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError(job)


def model_id(client, hf_id: str = "nlpai-lab/KURE-v1") -> int:
    return next(m["id"] for m in client.get("/api/models").json() if m["hf_id"] == hf_id)
