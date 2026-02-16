# arXiv Morning Digest — Project Notes

## Mis see on
Automaatne süsteem mis iga öö kell 04:00 Eesti aja järgi:
1. Tõmbab arXiv'ist viimase 96h paperid (quant finance + AI/ML)
2. Loeb iga paperi **täisteksti** (arXiv HTML versioon, mitte ainult abstract)
3. Saadab Gemini AI-le analüüsimiseks isikliku profiiliga
4. Genereerib HTML lehe GitHub Pages'ile
5. Hommikul ärkad ja vaatad: https://connortrader.github.io/wok2/

## Repo
- GitHub: https://github.com/connortrader/wok2 (public)
- Pages: https://connortrader.github.io/wok2/
- Kohalik: D:/Algorithims/del/arxiv-digest/

## Tehnilised detailid
- **AI mudel:** Gemini 2.5 Flash Lite (tasuta tier)
- **API võti:** GitHub Secrets > GEMINI_API_KEY (Gemini API key)
- **Cron:** `0 2 * * *` = 04:00 EET (02:00 UTC)
- **Paperid:** q-fin.CP, q-fin.PM, q-fin.ST, q-fin.RM, q-fin.TR + cs.AI, cs.LG
- **Max papereid:** 40 quant + 40 AI per päev

## Kauplemisprofiil (mis on AI promptis)
- US aktsiad ainult, end-of-day
- RealTest (Marsten Parker) + Norgate data
- Huvitab: momentum, mean reversion, factor models, portfolio optimeerimine, drawdown
- Ei huvita: crypto, forex, options, futures, HFT, Jaapan
- AI paperid: praktilised tööriistad, agendid, longevity/health, superhuman productivity

## Iga paperi kokkuvõtte struktuur
- **Skoor 1-10** (implementeeritavus + leid + robustsus + uudsus)
- **Avastati** — konkreetne leid arvudega (nt "Leidsid et X ületas Y 23% võrra")
- **Mida see tähendab** — mida see tähendab sinule spetsiifiliselt
- **Mida teha** — täpne samm: "Testi RealTestis: ..." VÕI "Skip — põhjus"

## Käivitamine käsitsi (test)
```bash
cd D:/Algorithims/del/arxiv-digest
set GEMINI_API_KEY=AIzaSyDVOI6Wu_7DIffLooPEVLhfxD-kvWCERSk
python scripts/generate_digest.py
# avatab docs/index.html brauseris
```

## GitHub Actions käsitsi käivitamine
https://github.com/connortrader/wok2/actions > "Daily arXiv Digest" > "Run workflow"

## Olekus / TODO
- [x] arXiv API fetch (quant + AI)
- [x] Täisteksti lugemine arXiv HTML kaudu
- [x] Gemini analüüs isikliku profiiliga
- [x] HTML leht (clean design, skoorid, 3-osaline kokkuvõte)
- [x] GitHub Actions cron (04:00 EET)
- [x] GitHub Pages deploy
- [ ] Testimine esmaspäeval kui arXiv avaldab uued paperid
- [ ] Vaadata kas Gemini kokkuvõtted on piisavalt konkreetsed täistekstiga
- [ ] Võimalik: Telegram bot saadab hommikul notification

## Failid
```
arxiv-digest/
├── scripts/generate_digest.py   ← peamine skript
├── .github/workflows/daily-digest.yml ← cron job
├── docs/index.html              ← genereeritud leht
├── requirements.txt
└── PROJECT.md                   ← see fail
```

## Tokenid / Võtmed
- GitHub PAT: hoia eraldi, ära commiti (repo + workflow scope vajalik)
- Gemini API: GitHub Secrets'is GEMINI_API_KEY nimega
