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
MAX_AI            = 40
GEMINI_MODEL      = "gemini-2.5-flash-lite"
OUTPUT_FILE       = "docs/index.html"
FULL_TEXT_TIMEOUT = 10    # seconds per paper HTML fetch
FULL_TEXT_CHARS   = 3000  # chars extracted per paper

TRADER_PROFILE = """
You write a sharp, no-bullshit morning briefing for a retail quantitative trader.
You have the FULL TEXT of each paper (intro + results + conclusion), not just the abstract.
Use the ACTUAL numbers, findings, and methods from the paper — not vague summaries.

TRADER PROFILE:
- Trades US stocks only. No crypto, forex, options, futures, HFT, non-US markets.
- Uses RealTest (Marsten Parker) + Norgate end-of-day data (price, volume, fundamentals)
- Goals: portfolio of diversified strategies, robust backtesting, signal generation
- Python: intermediate. Can code moderately complex strategies.
- Interests: momentum, mean reversion, factor models, portfolio optimization, drawdown control
- AI interest: practical productivity tools, AI agents that work today, longevity/health findings

WRITING RULES — be concrete, use numbers from the paper:
  discovery:  One sentence. "They found X outperformed Y by Z% over N years."
              Use real numbers from the paper. If no numbers, describe the method concisely.
  insight:    1-2 sentences. What this means for this trader specifically.
              Connect to their actual workflow (RealTest, US stocks, portfolio).
  action:     Pick exactly one:
              • "Test in RealTest: [specific step — what signal, what filter, what data]"
              • "Try this tool: [tool name + what it does + link if mentioned]"
              • "Learn this: [specific concept or method worth studying]"
              • "Skip — [one concrete reason why not applicable]"

SCORING (1-10, sum of):
  Implementability (0-3): testable in RealTest with Norgate price/vol/fundamentals?
  Finding quality  (0-3): specific, measurable result with evidence?
  Robustness       (0-2): multiple periods or out-of-sample tested?
  Novelty          (0-2): new idea for this trader?

Return ONLY valid JSON — no markdown, no extra text.
{"papers":[{"id":"...","title":"...","url":"...","category":"quant or ai","score":7,
"discovery":"They found...","insight":"This means...","action":"Test in RealTest: ...",
"can_implement":true,"tags":["momentum"]}]}

Sort by score descending.
ONLY analyze papers I provided. Do NOT add papers from your own knowledge.
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
def build_prompt(papers: list) -> str:
    lines = [TRADER_PROFILE, ""]
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
    impl_text  = "Implementable in RealTest" if can else "Not directly implementable"
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
    <div style="display:grid;grid-template-columns:110px 1fr;gap:0;margin-bottom:2px;">
      <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#bbb;padding:10px 0;">Avastati</span>
      <span style="font-size:14px;color:#111;line-height:1.65;padding:10px 0;border-bottom:1px solid #f5f5f5;">{p.get('discovery','')}</span>
    </div>
    <div style="display:grid;grid-template-columns:110px 1fr;gap:0;margin-bottom:2px;">
      <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#bbb;padding:10px 0;">Mida see tahendab</span>
      <span style="font-size:13px;color:#444;line-height:1.65;padding:10px 0;border-bottom:1px solid #f5f5f5;">{p.get('insight','')}</span>
    </div>
    <div style="display:grid;grid-template-columns:110px 1fr;gap:0;">
      <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#bbb;padding:10px 0;">Mida teha</span>
      <span style="font-size:13px;color:#1b5e20;line-height:1.65;padding:10px 0;font-weight:500;">{p.get('action','')}</span>
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
    action = p.get("action", "")[:130]
    return f"""<div style="display:flex;gap:12px;padding:10px 4px;border-bottom:1px solid #f5f5f5;align-items:flex-start;">
  <span style="background:{bg};color:{fg};font-weight:700;padding:1px 8px;border-radius:3px;font-size:11px;white-space:nowrap;flex-shrink:0;">{score}/10</span>
  <div>
    <a href="{p.get('url','#')}" target="_blank" rel="noopener"
       style="color:#444;font-size:13px;text-decoration:none;font-weight:500;">{title}{'…' if len(p.get('title',''))>105 else ''}</a>
    <div style="font-size:11px;color:#999;margin-top:3px;">{action}{'…' if len(p.get('action',''))>130 else ''}</div>
  </div>
</div>"""


def render_ai_link(p: dict) -> str:
    return (f'<div style="padding:7px 0;border-bottom:1px solid #f5f5f5;">'
            f'<a href="{p.get("url","#")}" target="_blank" rel="noopener" '
            f'style="color:#444;font-size:13px;text-decoration:none;">{p.get("title","")}</a>'
            f'</div>')


def generate_html(data: dict, quant_count: int, ai_raw: list,
                  full_text_count: int, total_papers: int) -> str:
    papers  = data.get("papers", [])
    top     = [p for p in papers if p.get("score", 0) >= 7]
    quant   = [p for p in papers if p.get("category") == "quant" and p.get("score", 0) < 7]
    ai_count = len(ai_raw)

    def section(items, card_min=5):
        if not items:
            return '<p style="color:#ccc;font-size:13px;padding:12px 0;">No papers in this section.</p>'
        return "\n".join(render_card(p) if p.get("score",0) >= card_min else render_row(p) for p in items)

    def ai_section():
        if not ai_raw:
            return '<p style="color:#ccc;font-size:13px;padding:12px 0;">No AI papers today.</p>'
        return "\n".join(render_ai_link(p) for p in ai_raw)

    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    weekday  = datetime.now(timezone.utc).strftime("%A")
    time_str = datetime.now(timezone.utc).strftime("%H:%M UTC")

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
    <span>📄 {full_text_count}/{total_papers} full papers read</span>
    <span>⭐ {len(top)} top picks</span>
    <span style="color:#bbb;">Generated {time_str}</span>
  </div>
</div>

<h2>Top Picks — Worth your time</h2>
{section(top, card_min=0) if top else '<p style="color:#ccc;font-size:13px;padding:12px 0;">No high-scoring papers today.</p>'}

<h2>Quantitative Finance — Remaining</h2>
{section(quant)}

<h2>AI & Automation — Reference links</h2>
{ai_section()}

<div style="margin-top:56px;padding-top:16px;border-top:1px solid #e8e8e8;font-size:10px;color:#ccc;text-align:center;">
  Auto-generated · Gemini {GEMINI_MODEL} · arXiv API · Last {HOURS_BACK}h
</div>
</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────
def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def main() -> None:
    # 1. Fetch abstracts
    print(f"[{ts()}] Fetching quant papers...")
    quant_raw = fetch_arxiv(QUANT_CATEGORIES, max_results=80)
    quant_new = filter_recent(quant_raw, HOURS_BACK)[:MAX_QUANT]
    print(f"         -> {len(quant_new)} papers")
    time.sleep(2)

    print(f"[{ts()}] Fetching AI papers...")
    ai_raw = fetch_arxiv(AI_CATEGORIES, max_results=100)
    ai_new = filter_recent(ai_raw, HOURS_BACK)[:MAX_AI]
    print(f"         -> {len(ai_new)} papers")

    if not quant_new and not ai_new:
        print("No recent papers. Generating empty page.")
        html = generate_html({"papers": []}, 0, [], 0, 0)
        os.makedirs("docs", exist_ok=True)
        open(OUTPUT_FILE, "w", encoding="utf-8").write(html)
        return

    # 2. Fetch full text — quant papers only (AI shown as links, no analysis needed)
    quant_papers = [dict(p, category="quant") for p in quant_new]
    total = len(quant_papers)
    full_count = 0

    print(f"[{ts()}] Fetching full text for {total} quant papers...")
    for i, p in enumerate(quant_papers):
        content, is_full = fetch_full_text(p)
        p["content"]  = content
        p["is_full"]  = is_full
        if is_full:
            full_count += 1
        status = "full" if is_full else "abstract"
        print(f"         [{i+1:2d}/{total}] {status} — {p['title'][:55]}...")
        time.sleep(0.3)  # polite to arXiv

    print(f"[{ts()}] Full text: {full_count}/{total} papers")

    # 3. Gemini analysis — quant papers only
    print(f"[{ts()}] Sending to Gemini ({GEMINI_MODEL}) — {len(quant_papers)} quant papers...")
    prompt = build_prompt(quant_papers)
    result = call_gemini(prompt)
    analyzed = len(result.get("papers", []))
    print(f"         -> {analyzed} papers analyzed")

    # 4. Generate HTML  (ai_new passed raw — rendered as a plain link list)
    html = generate_html(result, len(quant_new), ai_new, full_count, total)
    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"[{ts()}] Done -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
