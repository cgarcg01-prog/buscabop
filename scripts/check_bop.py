"""Check today's BOP León bulletin for keyword matches.

Exits 0 in all normal cases (no bulletin today, matches, no matches). Writes
`report.html` only when there are matches, and emits `matches_found=true|false`
to `$GITHUB_OUTPUT` so the workflow can decide whether to send the email.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

BOP_BASE = "https://bop.dipuleon.es"
BULLETIN_URL_TEMPLATE = BOP_BASE + "/publica/consulta-de-bops/buscador/BOP-{date}/"
PDF_HREF_MARKER = "Documentos-BOPs-en-PDF"
SNIPPET_PADDING = 100
USER_AGENT = "buscabop/1.0 (+https://github.com/) python-requests"


@dataclass
class Match:
    keyword: str
    page: int
    snippet: str


@dataclass
class BulletinReport:
    bop_date: date
    bulletin_url: str
    pdf_url: str
    matches: list[Match]


def normalize(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def normalized_with_map(s: str) -> tuple[str, list[int]]:
    """Normalize accents/case and keep a map back to original indices."""
    out: list[str] = []
    mapping: list[int] = []
    for orig_i, ch in enumerate(s):
        for c in unicodedata.normalize("NFKD", ch):
            if unicodedata.combining(c):
                continue
            out.append(c.lower())
            mapping.append(orig_i)
    return "".join(out), mapping


def find_matches(page_text: str, keyword: str) -> Iterable[str]:
    norm_text, mapping = normalized_with_map(page_text)
    norm_kw = normalize(keyword)
    if not norm_kw:
        return
    start = 0
    while True:
        idx = norm_text.find(norm_kw, start)
        if idx == -1:
            return
        end_norm = idx + len(norm_kw)
        orig_start = mapping[idx]
        orig_end = (
            mapping[end_norm - 1] + 1 if end_norm - 1 < len(mapping) else len(page_text)
        )
        s = max(0, orig_start - SNIPPET_PADDING)
        e = min(len(page_text), orig_end + SNIPPET_PADDING)
        snippet = re.sub(r"\s+", " ", page_text[s:e]).strip()
        if s > 0:
            snippet = "…" + snippet
        if e < len(page_text):
            snippet = snippet + "…"
        yield snippet
        start = end_norm


def load_keywords(path: Path) -> list[str]:
    keywords: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        keywords.append(line)
    return keywords


def fetch_bulletin_page(target: date, session: requests.Session) -> str | None:
    url = BULLETIN_URL_TEMPLATE.format(date=target.strftime("%d-%m-%Y"))
    r = session.get(url, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.text


def extract_pdf_url(page_html: str) -> str:
    soup = BeautifulSoup(page_html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if PDF_HREF_MARKER in href and href.lower().endswith(".pdf"):
            if href.startswith("/"):
                return BOP_BASE + href
            return href
    raise RuntimeError(
        f"Could not find a full-bulletin PDF link (looked for '{PDF_HREF_MARKER}' .pdf)."
    )


def download_pdf(pdf_url: str, session: requests.Session) -> Path:
    r = session.get(pdf_url, timeout=120, stream=True)
    r.raise_for_status()
    fd, name = tempfile.mkstemp(suffix=".pdf", prefix="bop-")
    os.close(fd)
    p = Path(name)
    with p.open("wb") as f:
        for chunk in r.iter_content(chunk_size=64 * 1024):
            if chunk:
                f.write(chunk)
    return p


def scan_pdf(pdf_path: Path, keywords: list[str]) -> list[Match]:
    reader = PdfReader(str(pdf_path))
    matches: list[Match] = []
    for page_num, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as e:
            print(f"  [warn] page {page_num} text extraction failed: {e}", file=sys.stderr)
            continue
        if not text.strip():
            continue
        for kw in keywords:
            for snippet in find_matches(text, kw):
                matches.append(Match(keyword=kw, page=page_num, snippet=snippet))
    return matches


def render_html(report: BulletinReport) -> str:
    rows = []
    for m in report.matches:
        rows.append(
            "<li><strong>{kw}</strong> — página {p}<br>"
            "<span style='color:#444'>{snip}</span></li>".format(
                kw=html.escape(m.keyword),
                p=m.page,
                snip=html.escape(m.snippet),
            )
        )
    items = "\n".join(rows)
    date_es = report.bop_date.strftime("%d/%m/%Y")
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, sans-serif; line-height:1.45; max-width:720px;">
<h2>BOP León — coincidencias del {date_es}</h2>
<p>Se han encontrado <strong>{len(report.matches)}</strong> coincidencia(s) en el boletín del {date_es}.</p>
<p>
  <a href="{html.escape(report.bulletin_url)}">Ver página del boletín</a> ·
  <a href="{html.escape(report.pdf_url)}">Descargar PDF</a>
</p>
<ul>
{items}
</ul>
<hr>
<p style="color:#888;font-size:12px">
Generado automáticamente por buscabop. Edita la lista de palabras clave en
<code>keywords.txt</code> del repositorio.
</p>
</body></html>
"""


def render_markdown(report: BulletinReport) -> str:
    lines = [
        f"# BOP León — {report.bop_date.strftime('%d/%m/%Y')}",
        f"- Página: {report.bulletin_url}",
        f"- PDF: {report.pdf_url}",
        f"- Coincidencias: {len(report.matches)}",
        "",
    ]
    for m in report.matches:
        lines.append(f"- **{m.keyword}** (pág. {m.page}): {m.snippet}")
    return "\n".join(lines)


def write_github_output(key: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with open(out, "a", encoding="utf-8") as f:
        f.write(f"{key}={value}\n")


def parse_cli_date(s: str) -> date:
    return datetime.strptime(s, "%d-%m-%Y").date()


def parse_inline_keywords(s: str) -> list[str]:
    out: list[str] = []
    for chunk in re.split(r"[\n,;]+", s):
        c = chunk.strip()
        if c and not c.startswith("#"):
            out.append(c)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        help="Override target date in DD-MM-YYYY format (for testing). "
             "Falls back to env var BOP_DATE.",
    )
    parser.add_argument(
        "--keywords",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "keywords.txt",
        help="Path to the keywords file (used when no inline override is given).",
    )
    parser.add_argument(
        "--keywords-inline",
        help="Override keywords inline. Comma-, semicolon- or newline-separated. "
             "Falls back to env var BOP_KEYWORDS_INLINE.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "report.html",
        help="Where to write the HTML report (only created when there are matches).",
    )
    args = parser.parse_args()

    inline_src = args.keywords_inline or os.environ.get("BOP_KEYWORDS_INLINE", "")
    if inline_src.strip():
        keywords = parse_inline_keywords(inline_src)
        print(f"Using inline keywords ({len(keywords)} item(s)): {keywords}")
    else:
        keywords = load_keywords(args.keywords)
    if not keywords:
        print("No keywords configured. Nothing to do.", file=sys.stderr)
        write_github_output("matches_found", "false")
        return 0

    date_src = args.date or os.environ.get("BOP_DATE", "").strip()
    if date_src:
        target = parse_cli_date(date_src)
    else:
        target = datetime.now(ZoneInfo("Europe/Madrid")).date()
    print(f"Checking BOP León for {target.strftime('%d-%m-%Y')} with {len(keywords)} keyword(s).")

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    page_html = fetch_bulletin_page(target, session)
    if page_html is None:
        print(f"No bulletin published on {target.strftime('%d-%m-%Y')} (404). Exiting.")
        write_github_output("matches_found", "false")
        return 0

    bulletin_url = BULLETIN_URL_TEMPLATE.format(date=target.strftime("%d-%m-%Y"))
    pdf_url = extract_pdf_url(page_html)
    print(f"Bulletin page: {bulletin_url}")
    print(f"PDF: {pdf_url}")

    pdf_path = download_pdf(pdf_url, session)
    try:
        matches = scan_pdf(pdf_path, keywords)
    finally:
        try:
            pdf_path.unlink()
        except OSError:
            pass

    report = BulletinReport(bop_date=target, bulletin_url=bulletin_url, pdf_url=pdf_url, matches=matches)
    print()
    print(render_markdown(report))

    if matches:
        args.report.write_text(render_html(report), encoding="utf-8")
        print(f"\nWrote {args.report} ({len(matches)} match(es)).")
        write_github_output("matches_found", "true")
        write_github_output("bop_date", target.strftime("%d/%m/%Y"))
    else:
        write_github_output("matches_found", "false")

    return 0


if __name__ == "__main__":
    sys.exit(main())
