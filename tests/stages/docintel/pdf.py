"""테스트용 작은 PDF 를 손으로 만든다 — PDF 를 쓰는 라이브러리(reportlab 등)를 의존성에 넣지 않으려고.

쪽마다 내용 스트림(PDF 그리기 명령)을 받아 xref 까지 맞춘 PDF 바이트를 돌려준다. 글꼴은 기본 Helvetica(영문만).
"""

TABLE_PAGE = "\n".join(
    [
        "BT /F1 14 Tf 72 720 Td (Sales report) Tj ET",
        # 2열 3행 표: 바깥 · 안쪽 선을 모두 그린다(pdfplumber 의 기본 'lines' 전략이 선으로 칸을 찾는다)
        "1 w",
        *[f"100 {y} m 300 {y} l S" for y in (500, 530, 560, 590)],
        *[f"{x} 500 m {x} 590 l S" for x in (100, 200, 300)],
        *[
            f"BT /F1 11 Tf {x} {y} Td ({t}) Tj ET"
            for (x, y, t) in [
                (110, 570, "Quarter"),
                (210, 570, "Sales"),
                (110, 540, "Q1"),
                (210, 540, "100"),
                (110, 510, "Q2"),
                (210, 510, "200"),
            ]
        ],
        "BT /F1 11 Tf 72 450 Td (Revenue grew in the second quarter compared with the first.) Tj ET",
    ]
)


def make_pdf(pages: list[str]) -> bytes:
    n = len(pages)
    # 1 카탈로그, 2 쪽 목록, 3 글꼴, 그 뒤로 쪽마다 (쪽, 내용) 두 객체
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, content in enumerate(pages):
        data = content.encode("latin-1")
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode()
        )
        objs.append(f"<< /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for k, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{k} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
