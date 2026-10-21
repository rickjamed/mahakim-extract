# mahakim-extract

**One-command extraction of court session schedules & parties from [mahakim.ma](https://mahakim.ma/suivi/horaire-seances)** (the official Moroccan judiciary portal) — no browser, no clicking, no Arabic on the command line.

Give it a session-type code, an appeal court, a first-instance court and a date (or a date range), and it walks the portal's own API chain and dumps every file + every party to **JSON** and **CSV**.

```
[*] plan: 1 type(s), 1 appeal court(s), 2 day(s)  ->  2 court-dates
[*] 2026-10-26 | جلسة جنحية — المحكمة الابتدائية بالعيون (id 145)
    audience 09:30 قاعة الجلسات الجنحية 1 (هيئة الجنحي العادي): 226 files
    audience 13:00 قاعة الجلسات الجنحية 1 (هيئة تلبسي اعتقال): 9 files
[✓] total files: 378
[✓] 378 files -> result.json
[✓] party rows -> result.csv
```

---

## Features

- **No Arabic input needed** — session types by code (`DP`, `DC`, `DA`, `DCO`) or English words (`penal`, `civil`, `admin`, `commercial`); courts by numeric id
- **One day or an inclusive date range** (`--date`, `--date-from` / `--date-to`)
- **Scope control**: all session types × all appeal courts × all their first-instance courts, or any subset — including `all`
- **Discovery mode**: `--list-types`, `--list-appeals`, `--list-firsts` to look up ids/codes
- **Dual output**: full detail in JSON, flat one-row-per-party CSV
- **No browser**: replays the portal's own encrypted API (static AES-256-CBC key embedded in its JS bundle)
- **Politeness built in**: configurable delay between requests (`--delay`, default `0.08s`)

## Install

```bash
git clone https://github.com/YOUR-USER/mahakim-extract.git
cd mahakim-extract
pip install -r requirements.txt
python mahakim_extract.py --help
```

## Quick start

```bash
# 1. discover the codes and ids
python mahakim_extract.py --list-types            # DP / DC / DA / DCO
python mahakim_extract.py --list-appeals          # all 23 appeal courts + ids
python mahakim_extract.py --list-firsts --appeal 144   # first-instance courts under it

# 2. extract
python mahakim_extract.py --type DP --appeal 144 --first 145 --date 26/10/2026

# whole country, one day
python mahakim_extract.py --type DP --date 2026-10-26

# everything, a whole week
python mahakim_extract.py --date-from 2026-10-26 --date-to 2026-10-30
```

## CLI reference

| Flag | Meaning | Default |
|---|---|---|
| `--type` | session type code(s): `DP` `DC` `DA` `DCO`, comma-list, `all`, or English words | `all` |
| `--appeal` | appeal-court id(s) (from `--list-appeals`), comma-list, or `all` | `all` |
| `--first` | first-instance court id(s) (from `--list-firsts`), comma-list, or `all` | the appeal court itself |
| `--date` | one day: `2026-10-26` or `26/10/2026` | — |
| `--date-from` / `--date-to` | inclusive day range (either alone = that single day) | — |
| `--out` | output JSON path (`-o`); a `.csv` with the same base name is written next to it | `mahakim-extract.json` |
| `--delay` | seconds between API calls | `0.08` |
| `--list-types` / `--list-appeals` / `--list-firsts` | discovery modes, print and exit | — |

Semantics note: `--first` picks the hearings schedule of the courts **under** an appeal court. Without it, only the appeal court's own schedule is queried.

## Output format

**JSON** — one record per court file:

```json
{
  "count": 378,
  "rows": [
    {
      "file": "1830/2102/2025",
      "registered": "2025-02-19",
      "audience": "09:30",
      "room": "قاعة الجلسات الجنحية 1",
      "division": "هيئة الجنحي العادي -الاثنين- 2026",
      "type": "جلسة جنحية",
      "court": "المحكمة الابتدائية بالعيون",
      "date": "2026-10-26",
      "parties": [
        {
          "role": "المتهم",
          "name": "ا.ر",
          "lawyers": ["الحبوسي سعيد"],
          "charges": ["السب والقذف"]
        }
      ]
    }
  ]
}
```

**CSV** — flat, one row per party: `file,registered,audience,room,division,role,name,lawyers,charges`

> Party names are anonymized **by the portal itself** (initials like «ا.ر») — this is server-side privacy, not a limitation of the tool.

## How it works

The portal's Angular SPA encrypts every API parameter with a **hardcoded AES-256-CBC key + IV** (extracted from its JS bundle) and wraps responses as `{"code":0,"data":"<base64>"}`. This tool reproduces that protocol — no browser, no headless automation:

```
ListeJuridictions2Instance   → appeal courts
Juridictions1Instance        → first-instance courts under an appeal court
ListeAudience                → sessions for (court, date, type)
ListeDossiersAudience        → files in a session
DossierAudience              → parties, lawyers and charges for one file
```

Crypto: `pycryptodome` when installed, automatic fallback to the system `openssl` binary. The one non-encrypted input is a `csrt` session fingerprint, scraped automatically from the landing page.

## Performance & etiquette

- Every court file costs ~2 API calls; a big day at one court ≈ 250 files ≈ ~2–3 minutes at the default delay.
- `--appeal all --first all` is **heavy** (100+ courts × per-day). The script prints a `plan: N court-dates` line first — split large runs by month or region.
- Keep `--delay` at or above `0.08` — be kind to a public service used by real litigants.

## Troubleshooting

| Symptom | Meaning / fix |
|---|---|
| `[!] F5 bot-wall cookie challenge seen` | Informational. The run normally proceeds anyway (the session cookie jar passes it). |
| `HTTP 403` everywhere | The site rate-limited your IP. Pause 10–20 min, raise `--delay`, or run from a different IP. |
| Court not found | Run `--list-appeals` / `--list-firsts` — court ids and names (including family-court sections) vary per session type. |
| Empty `[!!!]` errors mid-run | Transient server hiccup; re-run — the sweep is idempotent. |

## Disclaimer

This tool reads **publicly published** hearing schedules. It sends no credentials, modifies nothing, and the portal already anonymizes personal names. Use it at a respectful rate, for research/personal use. The authors are not affiliated with the Moroccan Ministry of Justice. No warranty.
