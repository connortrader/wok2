# arXiv Daily Digest

Runs every night via GitHub Actions, fetches recent papers from arXiv
(quantitative finance + AI/ML), analyzes them with Gemini, and publishes
a scored digest to GitHub Pages.

---

## Setup (one time)

### 1. Get a free Gemini API key
Go to https://aistudio.google.com/app/apikey → create a key (free tier is enough).

### 2. Create a GitHub repo
- New repo, public, name it e.g. `arxiv-digest`
- Push this code to it (see below)

### 3. Add the API key as a GitHub secret
Repo → Settings → Secrets and variables → Actions → New repository secret:
- Name: `GEMINI_API_KEY`
- Value: your key from step 1

### 4. Enable GitHub Pages
Repo → Settings → Pages:
- Source: `Deploy from a branch`
- Branch: `main` / folder: `/docs`
- Save → your digest will be at `https://yourusername.github.io/arxiv-digest/`

### 5. Run the first digest manually
Repo → Actions → Daily arXiv Digest → Run workflow

---

## Push code to GitHub

```bash
cd arxiv-digest
git init
git add .
git commit -m "init"
git remote add origin https://github.com/YOURUSERNAME/arxiv-digest.git
git push -u origin main
```

---

## Test locally

```bash
pip install -r requirements.txt
set GEMINI_API_KEY=your_key_here       # Windows CMD
# or
export GEMINI_API_KEY=your_key_here   # bash / PowerShell

python scripts/generate_digest.py
# then open docs/index.html in your browser
```

---

## Schedule

Runs at **04:00 UTC** = **06:00–07:00 Estonian time** every day.
Change the cron in `.github/workflows/daily-digest.yml` if needed.

## Categories fetched

| Source | Categories |
|--------|-----------|
| Quant Finance | q-fin.CP, q-fin.PM, q-fin.ST, q-fin.RM, q-fin.TR |
| AI / ML | cs.AI, cs.LG |

Papers from the last 48 hours are fetched (catches weekend papers on Monday).
