#!/usr/bin/env python3
"""arXiv Morning Digest — reads full paper text via arXiv HTML, powered by Gemini."""

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests
from google import genai
from google.genai import types

# ── Config ─────────────────────────────────────────────────────────────────────
QUANT_CATEGORIES  = ["q-fin.CP", "q-fin.PM", "q-fin.ST", "q-fin.RM", "q-fin.TR"]
AI_CATEGORIES     = ["cs.AI", "cs.LG"]
HOURS_BACK        = 96
MAX_QUANT         = 40
MAX_AI            = 15
MAX_LONGEVITY     = 10

LONGEVITY_KEYWORDS = [
    "aging", "ageing", "longevity", "lifespan", "healthspan", "life span",
    "senescence", "senolytic", "senolytics", "senomorphic",
    "rejuvenation", "rejuvenate", "epigenetic clock", "biological age",
    "NAD+", "NMN", "NR ", "sirtuins", "sirtuin", "SIRT1", "SIRT3",
    "rapamycin", "mTOR", "autophagy", "mitophagy",
    "telomere", "telomerase", "telomere length",
    "caloric restriction", "calorie restriction", "fasting", "intermittent fasting",
    "metformin", "acarbose", "spermidine",
    "inflammation aging", "inflammaging", "neurodegeneration",
    "mitochondria aging", "mitochondrial dysfunction",
    "gut microbiome aging", "microbiome longevity",
    "exercise longevity", "sleep aging", "sleep health",
    "protein aggregation aging", "proteostasis",
    "IGF-1", "growth hormone aging", "insulin signaling aging",
    "DNA damage aging", "oxidative stress aging",
    "stem cell aging", "tissue rejuvenation",
    "geroprotector", "geroprotective",
]
GEMINI_MODEL      = "gemini-2.5-flash-lite"
OUTPUT_FILE       = "docs/index.html"
FULL_TEXT_TIMEOUT = 10    # seconds per paper HTML fetch
FULL_TEXT_CHARS   = 3000  # chars extracted per paper

TRADER_PROFILE = """
Sa kirjutad EESTI KEELES hommikuse kokkuvõtte kvantitatiivse kaupleja jaoks.
Sul on iga artikli TÄISTEKST (sissejuhatus + tulemused + järeldused), mitte ainult abstrakt.
Kasuta TEGELIKKE NUMBREID ja TÄPSEID MEETODEID tekstist — mitte üldisi kokkuvõtteid.

KAUPLEJA PROFIIL:
- Kaupleb ainult USA aktsiatega. Ei tegele krüpto, forex, optsioonid, futuurid, HFT, välisturud.
- Kasutab RealTest (Marsten Parker) + Norgate päevalõpu andmed (hind, maht, fundamentaalid)
- Eesmärgid: mitmekesine strateegiate portfell, robustne backtesting, signaalide genereerimine
- Python: kesktase. Suudab kodeerida mõõdukalt keerulisi strateegiaid.
- Huvid: momentum, mean reversion, faktormudelid, portfelli optimeerimine, drawdown kontroll

KIRJUTAMISREEGLID — ole ÜLITÄPNE, kasuta numbreid tekstist:

  avastus: 2-3 lauset. Mis täpselt tehti ja mis tulemus saadi.
    HEA NÄIDE: "Testiti momentum strateegiat S&P 500 aktsiadel aastatel 1990-2020.
    Entry: aktsia sulgemine 52-nädala kõrgeima taseme 5% piires. Hold: 6 kuud.
    Tulemus: Sharpe 0.87 vs buy-and-hold 0.43. Max drawdown -23% vs -51%."
    HALB NÄIDE: "Leiti et momentum töötab hästi." — KEELATUD.

  selgitus: 1-2 lauset. Mida see konkreetselt selle kaupleja jaoks tähendab.

  toiming: Üks täpne tegevus. Kui artiklis on backtest, anna TÄPSED reeglid:
    • "Testi RealTest-is: Entry kui [täpne tingimus], Filter [täpne filter],
      Stop loss [täpne reegel], Hold [aeg]. Tulemus paberis: Sharpe X, CAGR Y%."
    • "Proovi tööriista: [nimi] — [mida teeb] — [link kui olemas]"
    • "Õpi: [konkreetne tehnika] — [miks kasulik, mis kasu]"
    • "Jäta vahele — [üks konkreetne põhjus]"

SKOOR (1-10, summa):
  Implementeeritavus (0-3): kas saab testida RealTest-is Norgate hind/maht/fundamentaalidega?
  Leiuse kvaliteet   (0-3): kas on konkreetsed mõõdetavad tulemused?
  Robustsus          (0-2): kas testiti mitut perioodi või out-of-sample?
  Uudsus             (0-2): kas on uus idee selle kaupleja jaoks?

Tagasta AINULT kehtiv JSON — ilma markdown-ita, ilma lisatekstita.
{"papers":[{"id":"...","title":"...","url":"...","category":"quant or ai","score":7,
"avastus":"...","selgitus":"...","toiming":"...","can_implement":true,"tags":["momentum"]}]}

Sorteeri skoori järgi kahanevalt.
Analüüsi AINULT minu antud artikleid. ÄRA lisa artikleid oma teadmistest.
""".strip()


LONGEVITY_PROFILE = """
Sa kirjutad EESTI KEELES hommikuse longevity/tervise kokkuvõtte inimesele kelle eesmärk
on elada võimalikult kaua ja tervena (Bryan Johnson stiil — superhuman biohacking).
Sul on iga artikli TÄISTEKST. Kasuta TEGELIKKE NUMBREID ja TÄPSEID LEIDE.

LUGEJA PROFIIL:
- Eesmärk: maksimaalne eluiga, optimaalne tervis, bioloogilise vanuse vähendamine
- Huvid: senolytics, NAD+/NMN/NR, rapamycin, epigeneetilised kellad, autophagy,
  põletik, mitokondrid, soolestiku mikrobioom, uni, treening, toitumine
- Küsib alati: "Kas see töötab inimestel? Mida ma saan TÄNA teha?"

KIRJUTAMISREEGLID:
  avastus: 2-3 lauset. TÄPSED leiud numbritega.
    - Mis organism (hiired? inimesed? rakud?), mis vanusevahemik
    - Mis interventsioon (annus, kestus, meetod)
    - Mis tulemus (% eluea pikendus, biomarkeri muutus, haiguse risk jne)
    HEA: "Hiirtel (18 kuu vanused) vähendas rapamycin 4mg/kg/päevas 12 nädalat
    põletikunäitajaid (IL-6) 43% ja pikendas ülejäänud eluiga 9% (p<0.01)."
    HALB: "Leiti et rapamycin võib pikendada eluiga." — KEELATUD.

  selgitus: 1-2 lauset. Kas see on inimestele rakendatav? Mis piirangud?

  toiming: Üks konkreetne tegevus:
    • "Testi enda peal: [täpne protokoll — annus, aeg, mida mõõta]"
    • "Jälgi uuringut: [mida oodata, millal tulemused]"
    • "Proovi tööriista/testi: [mis test/tööriist + link]"
    • "Õpi: [konkreetne mehhanism miks see oluline]"
    • "Jäta vahele — [põhjus miks ei rakendu]"

SKOOR (1-10):
  Inimestele rakendatavus (0-3): kas töötab inimestel (mitte ainult hiirtel/rakkudel)?
  Leiu kvaliteet       (0-3): konkreetsed numbrid ja mehhanismid?
  Robustsus            (0-2): RCT või suur kohort? Replikeeritud?
  Uudsus               (0-2): uus tipu/protokoll/mehhanism?

Tagasta AINULT kehtiv JSON, ilma markdown-ita.
{"papers":[{"id":"...","title":"...","url":"...","category":"longevity","score":8,
"avastus":"...","selgitus":"...","toiming":"...","can_implement":true,"tags":["NAD+"]}]}

Sorteeri skoori järgi kahanevalt.
ANALÜÜSI AINULT minu antud artikleid.
""".strip()


# ── arXiv fetch ────────────────────────────────────────────────────────────────
def fetch_arxiv(categories: list, max_results: int = 80) -> list:
    cat_query = "+OR+".join(f"cat:{c}" for c in categories)
    url = (f"https://export.arxiv.org/api/query"
           f"?search_query={cat_query}"
           f"&sortBy=submittedDate&sortOrder=descending"
           f"&max_results={max_results}")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(resp.content)
    papers = []
    for entry in root.findall("a:entry", ns):
        raw_id = (entry.find("a:id", ns).text or "").strip()
        papers.append({
            "id":        raw_id.split("/abs/")[-1],
            "url":       raw_id,
            "title":     (entry.find("a:title", ns).text or "").strip().replace("\n", " "),
            "abstract":  (entry.find("a:summary", ns).text or "").strip().replace("\n", " "),
            "published": (entry.find("a:published", ns).text or ""),
        })
    return papers


def filter_recent(papers: list, hours: int) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = []
    for p in papers:
        try:
            pub = datetime.fromisoformat(p["published"].replace("Z", "+00:00"))
            if pub >= cutoff:
                result.append(p)
        except Exception:
            pass
    return result


# ── bioRxiv fetch ──────────────────────────────────────────────────────────────
def fetch_biorxiv_longevity(days_back: int = 4, max_results: int = 10) -> list:
    """Fetch recent bioRxiv papers filtered by longevity keywords."""
    end_date   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    papers = []
    cursor = 0
    kw_lower = [k.lower() for k in LONGEVITY_KEYWORDS]

    while len(papers) < max_results:
        url = f"https://api.biorxiv.org/details/biorxiv/{start_date}/{end_date}/{cursor}/json"
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break
        collection = data.get("collection", [])
        if not collection:
            break
        for item in collection:
            text = (item.get("title", "") + " " + item.get("abstract", "")).lower()
            if any(kw in text for kw in kw_lower):
                doi = item.get("doi", "")
                papers.append({
                    "id":        doi,
                    "url":       f"https://www.biorxiv.org/content/{doi}",
                    "title":     item.get("title", "").strip(),
                    "abstract":  item.get("abstract", "").strip().replace("\n", " "),
                    "published": item.get("date", ""),
                    "content":   item.get("abstract", "").strip()[:2000],
                    "is_full":   False,
                })
                if len(papers) >= max_results:
                    break
        total = data.get("messages", [{}])[0].get("total", 0)
        cursor += 100
        if cursor >= int(total):
            break
    return papers


# ── Full text extraction ───────────────────────────────────────────────────────
def extract_text(html: str) -> str:
    """Strip HTML and extract intro + results/conclusion from arXiv paper."""
    # Remove noise
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>',  '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<math[^>]*>.*?</math>',    '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<figure[^>]*>.*?</figure>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()

    if len(text) < 300:
        return text

    t_lower = text.lower()

    # Find the best conclusion/results section (must be in second half)
    midpoint = len(text) // 2
    markers = [
        'conclusion', 'conclusions', 'in summary', 'we conclude',
        'experimental results', 'our results', 'findings', 'we show that',
        'we find that', 'we demonstrate', 'results show',
    ]
    best_idx = -1
    for m in markers:
        idx = t_lower.find(m, midpoint)
        if idx > 0 and (best_idx == -1 or idx < best_idx):
            best_idx = idx

    intro       = text[:1800]
    conclusion  = text[best_idx: best_idx + 3000] if best_idx > 0 else text[-3000:]
    combined    = intro + "\n\n[...]\n\n" + conclusion
    return combined[:FULL_TEXT_CHARS]


def fetch_full_text(paper: dict) -> tuple:
    """Try to get full paper text from arXiv HTML. Returns (content, is_full_text)."""
    base_id = re.sub(r'v\d+$', '', paper['id'])
    url = f"https://arxiv.org/html/{base_id}"
    try:
        resp = requests.get(url, timeout=FULL_TEXT_TIMEOUT,
                            headers={"User-Agent": "arxiv-digest-bot/1.0 (research tool)"})
        if resp.status_code == 200 and len(resp.text) > 3000:
            extracted = extract_text(resp.text)
            if len(extracted) > 400:
                return (extracted, True)
    except Exception:
        pass
    return (paper['abstract'][:800], False)


# ── Gemini ─────────────────────────────────────────────────────────────────────
def build_prompt(papers: list, profile: str = None) -> str:
    lines = [profile or TRADER_PROFILE, ""]
    for p in papers:
        source_label = "[FULL TEXT]" if p.get("is_full") else "[ABSTRACT ONLY]"
        lines += [
            "=" * 55,
            f"{source_label} {p.get('category','').upper()} | ID: {p['id']}",
            f"Title: {p['title']}",
            f"URL: {p['url']}",
            f"Content:\n{p['content']}",
            "",
        ]
    return "\n".join(lines)


def extract_json(text: str) -> dict:
    """Robustly extract JSON from Gemini response, handling extra text."""
    text = text.strip()
    # Strategy 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strategy 2: find { and match closing brace by counting
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start: i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"No valid JSON found in response. First 300 chars: {text[:300]}")


def normalize_result(raw) -> dict:
    """Ensure result is always {"papers": [list of dicts]}."""
    if isinstance(raw, list):
        result = {"papers": raw}
    elif isinstance(raw, dict):
        # Gemini sometimes returns {"paper": [...]} or {"results": [...]}
        if "papers" not in raw:
            for key in raw:
                if isinstance(raw[key], list):
                    result = {"papers": raw[key]}
                    break
            else:
                result = raw
        else:
            result = raw
    else:
        result = {"papers": []}
    # Filter out any non-dict items Gemini may have mixed in (e.g. "...remaining omitted")
    result["papers"] = [p for p in result.get("papers", []) if isinstance(p, dict)]
    return result


def call_gemini(prompt: str) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set.")
    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
            max_output_tokens=16000,
        ),
    )
    if not resp.text:
        finish = (resp.candidates[0].finish_reason if resp.candidates else "unknown")
        raise ValueError(f"Gemini returned empty response. finish_reason={finish}")
    return normalize_result(extract_json(resp.text))


# ── HTML rendering ─────────────────────────────────────────────────────────────
def score_style(score: int) -> tuple:
    if score >= 8: return ("#e8f5e9", "#2e7d32")
    if score >= 6: return ("#fff8e1", "#e65100")
    if score >= 4: return ("#f5f5f5", "#757575")
    return ("#fafafa", "#bdbdbd")


def render_card(p: dict) -> str:
    score = p.get("score", 0)
    bg, fg = score_style(score)
    cat = p.get("category", "")
    cat_label = "QUANT" if cat == "quant" else "AI"
    cat_color = "#1565c0" if cat == "quant" else "#6a1b9a"
    can = p.get("can_implement", False)
    impl_color = "#2e7d32" if can else "#9e9e9e"
    impl_text  = "Implementeeritav RealTest-is" if can else "Ei ole otseselt implementeeritav"
    tags = " ".join(
        f'<span style="background:#f0f0f0;color:#777;padding:1px 7px;border-radius:3px;font-size:11px;">{t}</span>'
        for t in p.get("tags", [])
    )
    return f"""<div style="background:#fff;border:1px solid #e8e8e8;border-left:3px solid {fg};border-radius:6px;padding:20px 22px;margin-bottom:12px;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;flex-wrap:wrap;">
    <span style="background:{bg};color:{fg};font-weight:700;padding:2px 10px;border-radius:4px;font-size:13px;">{score}/10</span>
    <span style="color:{cat_color};font-size:11px;font-weight:700;letter-spacing:1px;border:1px solid {cat_color};padding:1px 7px;border-radius:3px;">{cat_label}</span>
    <a href="{p.get('url','#')}" target="_blank" rel="noopener"
       style="color:#111;font-weight:600;font-size:15px;text-decoration:none;line-height:1.4;">{p.get('title','')}</a>
  </div>
  <div style="border-top:1px solid #f2f2f2;padding-top:12px;">
    <div style="display:grid;grid-template-columns:100px 1fr;gap:0;margin-bottom:2px;">
      <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#bbb;padding:10px 0;">Avastus</span>
      <span style="font-size:14px;color:#111;line-height:1.7;padding:10px 0;border-bottom:1px solid #f5f5f5;">{p.get('avastus','')}</span>
    </div>
    <div style="display:grid;grid-template-columns:100px 1fr;gap:0;margin-bottom:2px;">
      <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#bbb;padding:10px 0;">Tähendus</span>
      <span style="font-size:13px;color:#444;line-height:1.65;padding:10px 0;border-bottom:1px solid #f5f5f5;">{p.get('selgitus','')}</span>
    </div>
    <div style="display:grid;grid-template-columns:100px 1fr;gap:0;">
      <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#bbb;padding:10px 0;">Toiming</span>
      <span style="font-size:13px;color:#1b5e20;line-height:1.7;padding:10px 0;font-weight:500;">{p.get('toiming','')}</span>
    </div>
  </div>
  <div style="margin-top:10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
    <span style="font-size:11px;color:{impl_color};">● {impl_text}</span>
    <span style="color:#e0e0e0;">|</span>
    {tags}
  </div>
</div>"""


def render_row(p: dict) -> str:
    score = p.get("score", 0)
    bg, fg = score_style(score)
    title = p.get("title", "")[:105]
    toiming = p.get("toiming", "")[:150]
    return f"""<div style="display:flex;gap:12px;padding:10px 4px;border-bottom:1px solid #f5f5f5;align-items:flex-start;">
  <span style="background:{bg};color:{fg};font-weight:700;padding:1px 8px;border-radius:3px;font-size:11px;white-space:nowrap;flex-shrink:0;">{score}/10</span>
  <div>
    <a href="{p.get('url','#')}" target="_blank" rel="noopener"
       style="color:#444;font-size:13px;text-decoration:none;font-weight:500;">{title}{'…' if len(p.get('title',''))>105 else ''}</a>
    <div style="font-size:11px;color:#999;margin-top:3px;">{toiming}{'…' if len(p.get('toiming',''))>150 else ''}</div>
  </div>
</div>"""


def render_ai_link(p: dict) -> str:
    return (f'<div style="padding:7px 0;border-bottom:1px solid #f5f5f5;">'
            f'<a href="{p.get("url","#")}" target="_blank" rel="noopener" '
            f'style="color:#444;font-size:13px;text-decoration:none;">{p.get("title","")}</a>'
            f'</div>')


def generate_html(quant_result: dict, ai_result: dict, bio_result: dict,
                  quant_count: int, ai_count: int, bio_count: int,
                  full_text_count: int, total_papers: int) -> str:
    all_papers = (quant_result.get("papers", []) +
                  ai_result.get("papers", []) +
                  bio_result.get("papers", []))
    top   = [p for p in all_papers if p.get("score", 0) >= 7]
    quant = [p for p in quant_result.get("papers", []) if p.get("score", 0) < 7]
    ai    = [p for p in ai_result.get("papers", []) if p.get("score", 0) < 7]
    bio   = [p for p in bio_result.get("papers", []) if p.get("score", 0) < 7]

    def section(items):
        if not items:
            return '<p style="color:#ccc;font-size:13px;padding:12px 0;">Täna artikleid pole.</p>'
        return "\n".join(render_card(p) if p.get("score", 0) >= 5 else render_row(p) for p in items)

    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    weekday  = datetime.now(timezone.utc).strftime("%A")
    time_str = datetime.now(timezone.utc).strftime("%H:%M UTC")

    bio_section = f"""
<h2>Longevity &amp; Tervis — bioRxiv</h2>
{section(bio)}
""" if bio_count > 0 else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Morning Digest · {date_str}</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#f6f6f4;color:#111;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;padding:40px 24px;max-width:760px;margin:0 auto;line-height:1.5}}
  h2{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:2.5px;color:#aaa;margin:44px 0 16px;padding-bottom:10px;border-bottom:1px solid #e4e4e4}}
  @media(max-width:600px){{body{{padding:20px 14px}}}}
</style>
</head>
<body>

<div style="border-bottom:2px solid #111;padding-bottom:20px;margin-bottom:4px;">
  <div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:2px;margin-bottom:6px;">{weekday} · arXiv Morning Digest</div>
  <div style="font-size:28px;font-weight:700;letter-spacing:-0.5px;margin-bottom:14px;">{date_str}</div>
  <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:#666;">
    <span>📊 {quant_count} quant</span>
    <span>🤖 {ai_count} AI</span>
    <span>🧬 {bio_count} longevity</span>
    <span>📄 {full_text_count}/{total_papers} full text</span>
    <span>⭐ {len(top)} top picks</span>
    <span style="color:#bbb;">Generated {time_str}</span>
  </div>
</div>

<h2>Top Picks — Worth your time</h2>
{section(top) if top else '<p style="color:#ccc;font-size:13px;padding:12px 0;">Täna kõrgeid skoore pole.</p>'}

<h2>Kvantitatiivne rahandus — Remaining</h2>
{section(quant)}

<h2>AI &amp; Automatiseerimine — Remaining</h2>
{section(ai)}
{bio_section}
<div style="margin-top:56px;padding-top:16px;border-top:1px solid #e8e8e8;font-size:10px;color:#ccc;text-align:center;">
  Auto-generated · Gemini {GEMINI_MODEL} · arXiv API · Last {HOURS_BACK}h
</div>
</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────
def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def fetch_and_analyze(papers_raw: list, category: str, label: str) -> tuple:
    """Fetch full text for papers and run Gemini analysis. Returns (result_dict, full_count)."""
    papers = [dict(p, category=category) for p in papers_raw]
    full_count = 0
    print(f"[{ts()}] Fetching full text for {len(papers)} {label} papers...")
    for i, p in enumerate(papers):
        content, is_full = fetch_full_text(p)
        p["content"] = content
        p["is_full"] = is_full
        if is_full:
            full_count += 1
        status = "full" if is_full else "abstract"
        print(f"         [{i+1:2d}/{len(papers)}] {status} — {p['title'][:55]}...")
        time.sleep(0.3)
    print(f"[{ts()}] Full text: {full_count}/{len(papers)}")
    if not papers:
        return {"papers": []}, 0
    print(f"[{ts()}] Sending to Gemini — {len(papers)} {label} papers...")
    result = call_gemini(build_prompt(papers))
    print(f"         -> {len(result.get('papers', []))} analyzed")
    time.sleep(10)  # polite pause between Gemini calls
    return result, full_count


def analyze_longevity(papers: list) -> dict:
    """Run Gemini analysis on bioRxiv longevity papers using LONGEVITY_PROFILE."""
    if not papers:
        return {"papers": []}
    print(f"[{ts()}] Sending to Gemini — {len(papers)} longevity papers...")
    result = call_gemini(build_prompt(papers, profile=LONGEVITY_PROFILE))
    print(f"         -> {len(result.get('papers', []))} analyzed")
    time.sleep(10)
    return result


def main() -> None:
    # 1. Fetch abstracts
    print(f"[{ts()}] Fetching quant papers...")
    quant_new = filter_recent(fetch_arxiv(QUANT_CATEGORIES, max_results=80), HOURS_BACK)[:MAX_QUANT]
    print(f"         -> {len(quant_new)} papers")
    time.sleep(2)

    print(f"[{ts()}] Fetching AI papers...")
    ai_new = filter_recent(fetch_arxiv(AI_CATEGORIES, max_results=60), HOURS_BACK)[:MAX_AI]
    print(f"         -> {len(ai_new)} papers")
    time.sleep(2)

    print(f"[{ts()}] Fetching longevity papers from bioRxiv...")
    longevity_new = fetch_biorxiv_longevity(days_back=4, max_results=MAX_LONGEVITY)
    print(f"         -> {len(longevity_new)} papers")

    if not quant_new and not ai_new and not longevity_new:
        print("No recent papers. Generating empty page.")
        html = generate_html({"papers": []}, {"papers": []}, {"papers": []}, 0, 0, 0, 0, 0)
        os.makedirs("docs", exist_ok=True)
        open(OUTPUT_FILE, "w", encoding="utf-8").write(html)
        return

    # 2. Fetch full text + Gemini analysis per category
    quant_result, quant_full = fetch_and_analyze(quant_new,    "quant", "quant")
    ai_result,    ai_full    = fetch_and_analyze(ai_new,       "ai",    "AI")
    longevity_result         = analyze_longevity(longevity_new)

    total_full  = quant_full + ai_full
    total_count = len(quant_new) + len(ai_new)

    # 3. Generate HTML
    html = generate_html(
        quant_result, ai_result, longevity_result,
        len(quant_new), len(ai_new), len(longevity_new),
        total_full, total_count,
    )
    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"[{ts()}] Done -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
