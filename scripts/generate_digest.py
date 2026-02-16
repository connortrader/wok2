#!/usr/bin/env python3
"""arXiv Morning Digest — daily paper briefing powered by Gemini."""

import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests
from google import genai
from google.genai import types

# ── Config ─────────────────────────────────────────────────────────────────────
QUANT_CATEGORIES = ["q-fin.CP", "q-fin.PM", "q-fin.ST", "q-fin.RM", "q-fin.TR"]
AI_CATEGORIES    = ["cs.AI", "cs.LG"]
HOURS_BACK       = 96
MAX_QUANT        = 40
MAX_AI           = 40
GEMINI_MODEL     = "gemini-2.5-flash-lite"
OUTPUT_FILE      = "docs/index.html"

TRADER_PROFILE = """
You write a daily morning briefing for a retail quantitative trader. Be direct and concrete.

TRADER PROFILE:
- Trades US stocks only (no crypto, forex, options, futures, HFT, Japanese stocks)
- Uses RealTest (Marsten Parker) + Norgate end-of-day data (price, volume, fundamentals)
- Goals: portfolio of diversified strategies, robust backtesting, signal generation
- Python: intermediate level
- Core interests: momentum, mean reversion, factor models, portfolio optimization, drawdown control
- For AI papers: wants practical tools/agents for productivity, learning faster, longevity health findings

WRITING RULES:
- discovery: ONE sentence. What was actually found. Use numbers if the paper has them. Start with "They found..." or "Researchers built..." or "This paper shows..."
- insight: ONE or TWO sentences. What this means in plain language. Why it matters to this specific trader. No academic jargon.
- action: Be specific. Either:
    - "Test this in RealTest: [exact concrete step]" — if implementable
    - "Try this tool: [what to do]" — for AI papers with practical tools
    - "Read the method: [what specific concept to learn]" — if too complex but worth knowing
    - "Skip — [one reason why not relevant]" — if truly irrelevant

SCORING (1-10):
  Implementability (0-3): Can test with price/volume/fundamentals in RealTest?
  Insight clarity (0-3): Clear measurable finding with evidence?
  Robustness (0-2): Tested across multiple periods or conditions?
  Novelty (0-2): Something this trader likely hasn't tried?

Return ONLY valid JSON. No markdown. No text outside the JSON.
Structure:
{"papers":[{"id":"...","title":"...","url":"...","category":"quant or ai","score":7,"discovery":"They found...","insight":"This means...","action":"Test this in RealTest: ...","can_implement":true,"tags":["momentum"]}]}

Sort by score descending.
IMPORTANT: Only analyze papers I provided. Do not add papers from your own knowledge.
""".strip()


# ── arXiv fetch ────────────────────────────────────────────────────────────────
def fetch_arxiv(categories: list, max_results: int = 80) -> list:
    cat_query = "+OR+".join(f"cat:{c}" for c in categories)
    url = (
        f"https://export.arxiv.org/api/query"
        f"?search_query={cat_query}"
        f"&sortBy=submittedDate&sortOrder=descending"
        f"&max_results={max_results}"
    )
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


# ── Gemini ─────────────────────────────────────────────────────────────────────
def build_prompt(quant: list, ai: list) -> str:
    lines = [TRADER_PROFILE, "", "=" * 60, "QUANTITATIVE FINANCE PAPERS", "=" * 60]
    for p in quant:
        lines += [f"\nID: {p['id']}", f"Title: {p['title']}",
                  f"URL: {p['url']}", f"Abstract: {p['abstract'][:700]}"]
    lines += ["", "=" * 60, "AI / MACHINE LEARNING PAPERS", "=" * 60]
    for p in ai:
        lines += [f"\nID: {p['id']}", f"Title: {p['title']}",
                  f"URL: {p['url']}", f"Abstract: {p['abstract'][:500]}"]
    return "\n".join(lines)


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
        ),
    )
    text = resp.text.strip()
    if not text.startswith("{"):
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group()
    return json.loads(text)


# ── HTML ───────────────────────────────────────────────────────────────────────
def score_label(score: int) -> tuple:
    """Returns (bg_color, text_color, label)"""
    if score >= 8: return ("#e8f5e9", "#2e7d32", f"{score}/10")
    if score >= 6: return ("#fff8e1", "#e65100", f"{score}/10")
    if score >= 4: return ("#f5f5f5", "#757575", f"{score}/10")
    return ("#f5f5f5", "#bdbdbd", f"{score}/10")


def render_card(p: dict) -> str:
    score = p.get("score", 0)
    bg, fg, lbl = score_label(score)
    cat = p.get("category", "")
    cat_badge = "QUANT" if cat == "quant" else "AI"
    cat_color = "#1565c0" if cat == "quant" else "#6a1b9a"
    can = p.get("can_implement", False)
    impl_text = "Implementable in RealTest" if can else "Not directly implementable"
    impl_color = "#2e7d32" if can else "#757575"
    tags = " ".join(
        f'<span style="display:inline-block;background:#f0f0f0;color:#666;'
        f'padding:1px 7px;border-radius:3px;font-size:11px;">{t}</span>'
        for t in p.get("tags", [])
    )

    discovery = p.get("discovery", "")
    insight = p.get("insight", "")
    action = p.get("action", "")

    return f"""
<div style="border:1px solid #e0e0e0;border-radius:6px;padding:20px 22px;margin-bottom:14px;background:#fff;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap;">
    <span style="background:{bg};color:{fg};font-weight:700;padding:2px 10px;border-radius:4px;font-size:13px;">{lbl}</span>
    <span style="background:none;color:{cat_color};font-size:11px;font-weight:600;letter-spacing:1px;border:1px solid {cat_color};padding:1px 7px;border-radius:3px;">{cat_badge}</span>
    <a href="{p.get('url','#')}" target="_blank" rel="noopener"
       style="color:#1a1a1a;font-weight:600;font-size:15px;text-decoration:none;line-height:1.4;flex:1;min-width:200px;">{p.get('title','')}</a>
  </div>

  <table style="width:100%;border-collapse:collapse;">
    <tr>
      <td style="width:72px;padding:8px 12px 8px 0;vertical-align:top;">
        <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#999;">Leiti</span>
      </td>
      <td style="padding:8px 0;vertical-align:top;border-bottom:1px solid #f0f0f0;">
        <span style="font-size:14px;color:#1a1a1a;line-height:1.6;">{discovery}</span>
      </td>
    </tr>
    <tr>
      <td style="padding:8px 12px 8px 0;vertical-align:top;">
        <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#999;">Mida see tahendab</span>
      </td>
      <td style="padding:8px 0;vertical-align:top;border-bottom:1px solid #f0f0f0;">
        <span style="font-size:13px;color:#444;line-height:1.6;">{insight}</span>
      </td>
    </tr>
    <tr>
      <td style="padding:8px 12px 8px 0;vertical-align:top;">
        <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#999;">Mida teha</span>
      </td>
      <td style="padding:8px 0;vertical-align:top;">
        <span style="font-size:13px;color:#1b5e20;line-height:1.6;font-weight:500;">{action}</span>
      </td>
    </tr>
  </table>

  <div style="margin-top:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
    <span style="font-size:11px;color:{impl_color};">● {impl_text}</span>
    <span style="color:#ddd;">|</span>
    {tags}
  </div>
</div>"""


def render_row(p: dict) -> str:
    score = p.get("score", 0)
    bg, fg, lbl = score_label(score)
    title = p.get("title", "")
    if len(title) > 100:
        title = title[:100] + "…"
    action = p.get("action", "")
    if len(action) > 120:
        action = action[:120] + "…"
    return f"""
<div style="display:flex;gap:12px;padding:10px 0;border-bottom:1px solid #f5f5f5;align-items:flex-start;">
  <span style="background:{bg};color:{fg};font-weight:700;padding:1px 8px;border-radius:3px;font-size:12px;white-space:nowrap;flex-shrink:0;">{lbl}</span>
  <div>
    <a href="{p.get('url','#')}" target="_blank" rel="noopener"
       style="color:#333;font-size:13px;text-decoration:none;font-weight:500;">{title}</a>
    <div style="font-size:11px;color:#888;margin-top:2px;">{action}</div>
  </div>
</div>"""


def generate_html(data: dict, quant_count: int, ai_count: int) -> str:
    papers  = data.get("papers", [])
    top     = [p for p in papers if p.get("score", 0) >= 7]
    quant   = [p for p in papers if p.get("category") == "quant" and p.get("score", 0) < 7]
    ai_list = [p for p in papers if p.get("category") == "ai"    and p.get("score", 0) < 7]

    def section(items, card_threshold=5):
        if not items:
            return '<p style="color:#bbb;font-size:13px;padding:12px 0;">No papers in this section.</p>'
        return "\n".join(
            render_card(p) if p.get("score", 0) >= card_threshold else render_row(p)
            for p in items
        )

    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    weekday  = datetime.now(timezone.utc).strftime("%A")
    time_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
    top_count = len(top)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Morning Digest · {date_str}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box }}
  body {{
    background: #f7f7f5;
    color: #1a1a1a;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    padding: 40px 24px;
    max-width: 740px;
    margin: 0 auto;
    line-height: 1.5;
  }}
  h2 {{
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: #999;
    margin: 40px 0 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid #e0e0e0;
  }}
  @media (max-width: 600px) {{
    body {{ padding: 20px 16px; }}
  }}
</style>
</head>
<body>

<!-- Header -->
<div style="border-bottom:2px solid #1a1a1a;padding-bottom:20px;margin-bottom:8px;">
  <div style="font-size:11px;color:#999;text-transform:uppercase;letter-spacing:2px;margin-bottom:6px;">
    {weekday} · arXiv Morning Digest
  </div>
  <div style="font-size:30px;font-weight:700;letter-spacing:-0.5px;">{date_str}</div>
  <div style="margin-top:12px;display:flex;gap:20px;flex-wrap:wrap;">
    <span style="font-size:13px;color:#555;">📊 {quant_count} quant papers</span>
    <span style="font-size:13px;color:#555;">🤖 {ai_count} AI papers</span>
    <span style="font-size:13px;color:#555;">⭐ {top_count} top picks</span>
    <span style="font-size:13px;color:#999;">Generated {time_str}</span>
  </div>
</div>

<h2>Top Picks — Worth your time</h2>
{section(top, card_threshold=0) if top else '<p style="color:#bbb;font-size:13px;padding:12px 0;">No high-scoring papers today.</p>'}

<h2>Quantitative Finance — All papers</h2>
{section(quant)}

<h2>AI & Automation — All papers</h2>
{section(ai_list)}

<div style="margin-top:56px;padding-top:16px;border-top:1px solid #e0e0e0;font-size:11px;color:#bbb;text-align:center;">
  Auto-generated · Gemini {GEMINI_MODEL} · arXiv API · Last 96 hours
</div>

</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────
def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def main() -> None:
    print(f"[{ts()}] Fetching quant papers...")
    quant_raw = fetch_arxiv(QUANT_CATEGORIES, max_results=80)
    quant_new = filter_recent(quant_raw, HOURS_BACK)[:MAX_QUANT]
    print(f"         -> {len(quant_new)} papers in last {HOURS_BACK}h")

    time.sleep(3)

    print(f"[{ts()}] Fetching AI/ML papers...")
    ai_raw = fetch_arxiv(AI_CATEGORIES, max_results=100)
    ai_new = filter_recent(ai_raw, HOURS_BACK)[:MAX_AI]
    print(f"         -> {len(ai_new)} papers in last {HOURS_BACK}h")

    if not quant_new and not ai_new:
        print("No recent papers found. Generating empty page.")
        html = generate_html({"papers": []}, 0, 0)
        os.makedirs("docs", exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
            fh.write(html)
        return

    total = len(quant_new) + len(ai_new)
    print(f"[{ts()}] Sending {total} papers to Gemini...")
    prompt = build_prompt(quant_new, ai_new)
    result = call_gemini(prompt)
    analyzed = len(result.get("papers", []))
    print(f"         -> {analyzed} papers analyzed")

    html = generate_html(result, len(quant_new), len(ai_new))
    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"[{ts()}] Done -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
