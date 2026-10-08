"""把技术报告导出为 A4 PDF。

依赖本机的 Python 包 markdown，以及带中文字体的 Chrome。
正文页数按「九、附录」之前单独计，附录不计入这 15 页建议。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "技术报告.md"
PDF = ROOT / "技术报告.pdf"
FONT = Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")
CHROME = "/usr/bin/google-chrome"


STYLE = """
@page { size: A4; margin: 16mm 15mm 16mm 15mm; }
html { font-family: "WenQuanYi Micro Hei", sans-serif; }
body { font-size: 10.5pt; line-height: 1.45; color: #1c1a17; }
h1 { font-size: 16pt; line-height: 1.3; margin: 0 0 0.6em; }
h2 { font-size: 13pt; margin: 1.1em 0 0.4em; page-break-after: avoid; }
h3 { font-size: 11.5pt; margin: 0.8em 0 0.3em; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
ul, ol { padding-left: 1.3em; }
code { font-family: "WenQuanYi Micro Hei", sans-serif; font-size: 0.92em; }
pre { white-space: pre-wrap; background: #f6f3ee; padding: 8px 10px; font-size: 9pt; }
table { width: 100%; border-collapse: collapse; margin: 0.4em 0 0.8em; font-size: 9pt; page-break-inside: avoid; }
th, td { border: 1px solid #c8c2b8; padding: 3px 5px; text-align: left; vertical-align: top; }
th { background: #f3efe8; }
img { width: 78%; height: auto; display: block; margin: 0.4em auto 0.8em; }
h2.appendix { page-break-before: always; }
"""


def to_html(text: str) -> str:
    body = markdown.markdown(text, extensions=["tables", "fenced_code"])
    body = body.replace("<h2>九、附录</h2>", '<h2 class="appendix">九、附录</h2>', 1)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>文脉弹幕六维读法</title>
<style>
@font-face {{
  font-family: "WenQuanYi Micro Hei";
  src: url("file://{FONT}") format("truetype");
}}
{STYLE}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def print_pdf(html_path: Path, pdf_path: Path) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            CHROME,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--user-data-dir=/tmp/chrome-wenmai-report",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ],
        check=True,
        capture_output=True,
    )


def page_count(pdf_path: Path) -> int:
    raw = pdf_path.read_bytes()
    return raw.count(b"/Type /Page") - raw.count(b"/Type /Pages")


def main() -> None:
    import tempfile

    text = SOURCE.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        html = folder / "report.html"
        html.write_text(to_html(text), encoding="utf-8")
        print_pdf(html, PDF)
        body_html = folder / "body.html"
        body_pdf = folder / "body.pdf"
        body_text = text.split("## 九、附录", 1)[0].rstrip() + "\n"
        body_html.write_text(to_html(body_text), encoding="utf-8")
        print_pdf(body_html, body_pdf)
        body_pages = page_count(body_pdf)
    print(
        {
            "pdf": str(PDF),
            "bytes": PDF.stat().st_size,
            "pages": page_count(PDF),
            "body_pages": body_pages,
        }
    )


if __name__ == "__main__":
    main()
