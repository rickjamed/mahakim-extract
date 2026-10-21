#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mahakim_extract.py — bulk extract session schedule + parties from mahakim.ma
No browser, no Arabic on the command line — you use codes and ids only.

 QUICK START
   python3 mahakim_extract.py --list-types
   python3 mahakim_extract.py --list-appeals
   python3 mahakim_extract.py --list-firsts --appeal 144
   python3 mahakim_extract.py --type DP --appeal 144 --first 145 --date 26/10/2026
   python3 mahakim_extract.py --type DP --appeal all --first all --date-from 2026-10-26 --date-to 2026-10-30

 OPTIONS
   --type       session-type code(s), comma-list, or 'all' [default: all 4 types]
                codes:  DP=penal(criminal)  DC=civil  DA=administrative  DCO=commercial
                English words also accepted:  penal / civil / admin / commercial
   --appeal     appeal-court id(s), comma-list, or 'all' [default: all]   (ids: --list-appeals)
   --first      first-instance court id(s), comma-list, or 'all'          (ids: --list-firsts)
                [default: only the appeal court itself]
   --date       one day: 2026-10-26 or 26/10/2026
   --date-from  INCLUSIVE range start (either flag alone = that single day)
   --date-to    INCLUSIVE range end
   --out        output JSON path [default: mahakim-extract.json] in the folder
                you run the command from; a .csv with the same base name is
                written next to it
   --delay      seconds between API calls [default: 0.08]

 OUTPUT
   JSON: {"count": n, "rows": [{
       "file", "registered", "audience", "room", "division",
       "type", "court", "date",
       "parties": [{"role", "name", "lawyers", "charges"}]}]}
   CSV : file,registered,audience,room,division,role,name,lawyers,charges
         (one row per party; files with no parties get one blank row)
"""
import argparse, base64, json, re, subprocess, sys, time
from datetime import date as _date

BASE  = "https://mahakim.ma"
API   = BASE + "/middleware/api/TableAudience/"
SEANCE_LIST = BASE + "/assets/fake-server/listes/liste_seances_.json"

# ── crypto (matches site bundle 450.fdae915bcd696326.js) ─────────────────────
KEY_B64 = "q6KGnnv7VXVSA4pDotDyWNx8ca5mKxWkn0eL784GxKQ="
IV_B64  = "k3vi7ZFUB8/XSID2AXEwug=="
KEY = base64.b64decode(KEY_B64); IV = base64.b64decode(IV_B64)

def _openssl(args, stdin=b""):
    return subprocess.run(["openssl", *args], input=stdin, capture_output=True, check=True).stdout

def enc(plain: str) -> str:
    """plaintext -> base64 (same as the site's cryptoService.encrypt)"""
    try:                                   # pycryptodome path
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad
        c = AES.new(KEY, AES.MODE_CBC, IV).encrypt(pad(plain.encode(), 16))
        return base64.b64encode(c).decode()
    except ImportError:                    # openssl path
        return _openssl(["enc", "-aes-256-cbc", "-nosalt", "-base64", "-A",
                         "-K", KEY.hex(), "-iv", IV.hex()], plain.encode()).decode()

def dec(b64: str) -> str:
    """base64 blob -> utf8 plaintext (same as cryptoService.decrypt)"""
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
        p = AES.new(KEY, AES.MODE_CBC, IV).decrypt(base64.b64decode(b64))
        return unpad(p, 16).decode()
    except ImportError:
        return _openssl(["enc", "-d", "-aes-256-cbc", "-nosalt", "-A",
                         "-K", KEY.hex(), "-iv", IV.hex()],
                        base64.b64decode(b64)).decode()

# ── transport ────────────────────────────────────────────────────────────────
sess = None
def init_session():
    """get cookies + csrt fingerprint from the landing page"""
    global sess
    import requests
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"})
    r = sess.get(BASE + "/suivi/horaire-seances", timeout=30)
    m = re.search(r"csrt=(\d+)", r.text)
    csrt = m.group(1) if m else "5877243535056404135"
    if "TSPD" in r.text[:4000] and r.status_code == 200:
        print("[!] F5 bot-wall cookie challenge seen; usually fine as long as the run proceeds.")
    return csrt

def api(path, csrt, **params):
    params["csrt"] = csrt
    r = sess.get(API + path, params=params, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"{path} -> HTTP {r.status_code}")
    j = r.json()
    cipher = j["data"]["value"] if isinstance(j.get("data"), dict) else j.get("data")
    if not cipher:
        return []
    return json.loads(dec(cipher))

# ── lookups ──────────────────────────────────────────────────────────────────
def load_seance_types():
    r = sess.get(SEANCE_LIST, timeout=30)
    return json.loads(r.text)

TYPE_ALIASES = {   # english words -> site codes (no Arabic needed)
    "penal": "DP", "criminal": "DP",
    "civil": "DC",
    "admin": "DA", "administrative": "DA",
    "commercial": "DCO",
}

def clean_name(s):
    return " ".join((s or "").split())      # collapse double spaces

def pick_types(argval, all_types):
    if argval.strip().lower() in ("all", "*"):
        return all_types
    picks = []
    for part in re.split(r"[,،]", argval):
        part = part.strip()
        if not part:
            continue
        code = TYPE_ALIASES.get(part.lower(), part).upper()
        hit = [t for t in all_types if code == t["typeaffaire"].upper()]
        if not hit:
            sys.exit(f"[x] unknown session type: {part!r}\n"
                     f"    valid codes: {[t['typeaffaire'] for t in all_types]}"
                     f"  (or english: penal/civil/admin/commercial, or 'all')")
        picks.append(hit[0])
    return picks

def pick_courts(argval, courts, label):
    """match by id (string/number) or name substring; 'all' returns everything"""
    if argval.strip().lower() in ("all", "*"):
        return list(courts)
    picks = []
    for part in re.split(r"[,،]", argval):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            hit = [c for c in courts if str(c["idJuridiction"]) == part]
        else:
            hit = [c for c in courts if part in (c["nomJuridiction"] or "")]
        if not hit:
            sys.exit(f"[x] unknown {label}: {part!r}\n"
                     f"    valid: {[str(c['idJuridiction']) + '=' + clean_name(c['nomJuridiction']) for c in courts]}")
        picks.append(hit[0])
    return picks

def load_first_instance(type_code, appeal_id, csrt):
    data = api("Juridictions1Instance", csrt,
               typeaffaire=enc(type_code),
               idJuridiction2Instance=enc(str(appeal_id)))
    return data if isinstance(data, list) else []

def norm_date(d):
    m = re.match(r"(\d{4}-\d{2}-\d{2})", d)
    if m:
        return m.group(1)
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    sys.exit("[x] date must be YYYY-MM-DD or DD/MM/YYYY")

def date_range(d1, d2):
    a, b = _date.fromisoformat(d1), _date.fromisoformat(d2)
    if b < a:
        a, b = b, a
    out = []
    while a <= b:
        out.append(a.isoformat())
        a = _date.fromordinal(a.toordinal() + 1)
    return out

# ── sweep ────────────────────────────────────────────────────────────────────
def sweep_jurisdiction(type_code, court_id, date, csrt, delay=0.08):
    """one (date, court): audiences -> dossiers -> parties per file"""
    rows = []
    auds = api("ListeAudience", csrt, idjuridiction=enc(str(court_id)),
               DateAudience=date, typeaffaire=enc(type_code))
    if not isinstance(auds, list):
        auds = auds.get("audiences", []) if isinstance(auds, dict) else []
    for a in auds:
        time.sleep(delay)
        try:
            files = api("ListeDossiersAudience", csrt,
                        idAudience=enc(str(a["id"])), typeaffaire=enc(type_code))
        except Exception as e:
            print(f"    [!] file-list failed for audience {a.get('id')}: {e}")
            continue
        if not isinstance(files, list):
            files = files.get("listeDossiers", []) if isinstance(files, dict) else []
        print(f"    audience {a.get('heure') or '?'} {a.get('salle') or ''} ({a.get('nomFormation') or '?'}): {len(files)} files")
        for i, d in enumerate(files, 1):
            time.sleep(delay)
            try:
                detail = api("DossierAudience", csrt,
                             numeroCompletDossier=enc(d["numeroDossierComplet"]),
                             idjuridiction=enc(str(court_id)))
                parties = (detail.get("parties", detail.get("liste_parties", []))
                           if isinstance(detail, dict) else detail)
            except Exception as e:
                print(f"      [!] {d['numeroDossierComplet']}: {e}")
                parties = []
            rows.append({
                "file": d["numeroDossierComplet"],
                "registered": d.get("dateEnregistrementString"),
                "audience": a.get("heure"),
                "room": a.get("salle"),
                "division": a.get("nomFormation"),
                "parties": [{
                    "role": p.get("role"),
                    "name": p.get("fullName"),
                    "lawyers": [av.get("nomAvocat") if isinstance(av, dict) else av
                                for av in (p.get("avocats") or [])],
                    "charges": [x.get("libelleAccusation") for x in (p.get("accusations") or [])]
                } for p in (parties or [])]
            })
            if i % 50 == 0:
                print(f"      {i}/{len(files)} files...")
    return rows

# ── output ───────────────────────────────────────────────────────────────────
def _q(x):
    s = "" if x is None else str(x)
    return '"' + s.replace('"', "'") + '"'

def dump(rows, out):
    doc = {"source": "mahakim.ma", "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
           "count": len(rows), "rows": rows}
    json.dump(doc, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    csv = out.rsplit(".", 1)[0] + ".csv"
    with open(csv, "w", encoding="utf-8-sig", newline="") as f:
        f.write("file,registered,audience,room,division,role,name,lawyers,charges\n")
        for r in rows:
            head = ",".join(_q(v) for v in (r["file"], r["registered"],
                                            r["audience"], r["room"], r["division"]))
            if not r["parties"]:
                f.write(head + ",,,,\n")
            for p in r["parties"]:
                f.write(",".join([head, _q(p.get("role")), _q(p.get("name")),
                                  _q("; ".join(p.get("lawyers") or [])),
                                  _q(" | ".join(p.get("charges") or []))]) + "\n")
    print(f"[✓] {len(rows)} files -> {out}")
    print(f"[✓] party rows -> {csv}")

# ── main ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(add_help=True, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--type",      help="codes DP/DC/DA/DCO (or penal/civil/admin/commercial), comma-list, or 'all' [default: all]")
    ap.add_argument("--appeal",    help="appeal-court id(s) or 'all' [default: all]; ids via --list-appeals")
    ap.add_argument("--first",     help="first-instance court id(s) or 'all' [default: just the appeal court]; ids via --list-firsts")
    ap.add_argument("--date",      help="one day: 2026-10-26 or 26/10/2026")
    ap.add_argument("--date-from", help="range start, inclusive")
    ap.add_argument("--date-to",   help="range end, inclusive")
    ap.add_argument("--out",       default="mahakim-extract.json")
    ap.add_argument("--delay",     type=float, default=0.08)
    ap.add_argument("--list-types",   action="store_true")
    ap.add_argument("--list-appeals", action="store_true")
    ap.add_argument("--list-firsts",  action="store_true")
    args = ap.parse_args()

    csrt = init_session()

    types = load_seance_types()
    if args.list_types:
        for t in types:
            print(f"{t['typeaffaire']} :: {t['seanceName']}")
        return
    types_sel = pick_types(args.type, types) if args.type else types
    if args.list_firsts:
        types_sel = types_sel[:1]      # court lists are near-identical per type; print once

    print("[*] fetching appeal courts ...")
    appeal_blob = api("ListeJuridictions2Instance", csrt,
                      typeaffaire=enc(types_sel[0]["typeaffaire"]))
    all_appeals = (appeal_blob if isinstance(appeal_blob, list)
                   else appeal_blob.get("listeJuridiction", []))
    if args.list_appeals:
        for c in all_appeals:
            print(f"{c['idJuridiction']} :: {clean_name(c['nomJuridiction'])}")
        return
    appeals_sel = pick_courts(args.appeal, all_appeals, "appeal court") if args.appeal else all_appeals

    dates = []
    if args.date_from or args.date_to:
        dates = date_range(norm_date(args.date_from or args.date_to),
                           norm_date(args.date_to or args.date_from))
    elif args.date:
        dates = [norm_date(args.date)]
    if not dates and not args.list_firsts:
        sys.exit("[x] give --date  or  --date-from [--date-to]")

    # resolve concrete courts ONCE (court lists don't change between days)
    plans = []   # (seance-type dict, [(court_id, court_name), ...])
    for t in types_sel:
        for apc in appeals_sel:
            firsts = load_first_instance(t["typeaffaire"], apc["idJuridiction"], csrt)
            if args.list_firsts:
                print(f"— appeal id {apc['idJuridiction']} :: {clean_name(apc['nomJuridiction'])}")
                for c in firsts:
                    print(f"   {c['idJuridiction']} :: {clean_name(c['nomJuridiction'])}")
                continue
            chosen = pick_courts(args.first, firsts, "first-instance court") if args.first else None
            targets = ([(c["idJuridiction"], clean_name(c["nomJuridiction"])) for c in chosen]
                       if chosen else
                       [(apc["idJuridiction"], clean_name(apc["nomJuridiction"]))])
            plans.append((t, targets))
    if args.list_firsts:
        return

    n_court_dates = sum(len(ts) for _, ts in plans) * len(dates)
    print(f"[*] plan: {len(types_sel)} type(s), {len(appeals_sel)} appeal court(s), "
          f"{len(dates)} day(s)  ->  {n_court_dates} court-dates"
          + ("   (big run — --out early, consider splitting)" if n_court_dates > 60 else ""))

    all_rows = []
    for date in dates:
        for t, targets in plans:
            for court_id, court_name in targets:
                print(f"[*] {date} | {t['seanceName']} — {clean_name(court_name)} (id {court_id})")
                rows = sweep_jurisdiction(t["typeaffaire"], court_id, date, csrt, args.delay)
                for r in rows:
                    r["type"] = t["seanceName"]
                    r["court"] = court_name
                    r["date"] = date
                all_rows += rows

    print(f"\n[✓] total files: {len(all_rows)}")
    dump(all_rows, args.out)

if __name__ == "__main__":
    main()
