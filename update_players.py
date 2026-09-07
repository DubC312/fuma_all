#!/usr/bin/env python3
from __future__ import annotations

import json, re, time, unicodedata
from pathlib import Path
from urllib.parse import quote_plus, unquote, urlparse, parse_qs
import re
from difflib import SequenceMatcher
import requests
from bs4 import BeautifulSoup

PLAYERS_FILE = Path("players.json")
CONFIG_FILE = Path("competitions.json")
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
})

EA_HOST = "https://www.ea.com"
EA_RATINGS = f"{EA_HOST}/games/ea-sports-fc/ratings"
SPORTSDB = "https://www.thesportsdb.com/api/v1/json/123/searchplayers.php?p="

# V5: bekannte Schreibvarianten / verifizierte SportsDB-IDs.
# Die Keys laufen durch norm(), daher können Akzente/Leerzeichen robust behandelt werden.
SPORTSDB_NAME_ALIASES = {
    # Verifizierte abweichende Namen zwischen EA FC und TheSportsDB
    "serhou guirassy": "Sehrou Guirassy",
    "serhou gurassi": "Sehrou Guirassy",
    "sehrou gurassi": "Sehrou Guirassy",
    "kim min jae": "Min-jae Kim",
    "lee jae sung": "Jae-sung Lee",
    "gabriel": "Gabriel Magalhães",
    "zubimendi": "Martín Zubimendi",
    "kouadio manu kone": "Manu Koné",
    "emiliano buendia": "Emi Buendía",
    "grimaldo": "Álex Grimaldo",
    "odin luraas bjortuft": "Odin Bjørtuft",
    "carlos forbs": "Carlos Forbs Borges",
    "morata": "Álvaro Morata",
    "alisson": "Alisson Becker",
    "abde": "Abde Ezzalzouli",
    "fornals": "Pablo Fornals",
    "bartra": "Marc Bartra",
    "vini jr": "Vinícius Júnior",
    "cucurella": "Marc Cucurella",
    "luis javier suarez": "Luis Suárez",
    "andre franck zambo anguissa": "Andre-Frank Zambo Anguissa",
    "moleiro": "Alberto Moleiro",
    "juan foyth": "Juan Marcos Foyth",
    "oyarzabal": "Mikel Oyarzabal",
    "guedes": "Gonçalo Guedes",
    "rafa": "Rafa Silva",
    "reinildo": "Reinildo Mandava",
    "samu": "Samu Omorodion",
    "nick d'agostino": "Nicholas D'Agostino",
    "neymar jr": "Neymar",
}
SPORTSDB_ID_OVERRIDES = {
    # Verifizierte TheSportsDB-Spieler-IDs
    "serhou guirassy": "34168124",
    "sehrou guirassy": "34168124",
    "serhou gurassi": "34168124",
    "sehrou gurassi": "34168124",
    "kim min jae": "34194499",
    "min jae kim": "34194499",
    "lee jae sung": "34174700",
    "jae sung lee": "34174700",
    "gabriel": "34172252",
    "zubimendi": "34172850",
    "kouadio manu kone": "34174783",
    "manu kone": "34174783",
    "wesley": "34292040",
    "emiliano buendia": "34149475",
    "emi buendia": "34149475",
    "grimaldo": "34160527",
    "odin luraas bjortuft": "34217499",
    "odin bjortuft": "34217499",
    "carlos forbs": "34220699",
    "morata": "34160535",
    "fermin": "34219811",
    "william gomes": "34245214",
    "alisson": "34163551",
    "abde": "34194984",
    "antony": "34172989",
    "fornals": "34164519",
    "bartra": "34146357",
    "vini jr": "34161324",
    "vinicius junior": "34161324",
    "cucurella": "34170224",
    "luis javier suarez": "34172603",
    "andre franck zambo anguissa": "34163809",
    "moleiro": "34216897",
    "juan foyth": "34161381",
    # IDs, die in einer früheren funktionierenden players.json bereits vorhanden waren
    "afonso moreira": "34222507",
    "raphael obermair": "34215613",
    "rodri": "34163415",
    "pedri": "34172243",
    "oyarzabal": "34161387",
    "alex scott": "34192695",
    "guedes": "34146537",
    "rafa": "34168935",
    "reinildo": "34173328",
    "samu": "34220051",
    "ewandro": "34164442",
    "nick d'agostino": "34164598",
    "neymar jr": "34146371",
}

def sportsdb_search_name(name):
    return SPORTSDB_NAME_ALIASES.get(norm(name), name)

def best_sportsdb_candidate(candidates, wanted_name):
    """Exakt -> Alias-exakt -> sehr ähnlicher Name; sonst None."""
    if not candidates:
        return None, False
    wanted_norm = norm(wanted_name)
    alias_norm = norm(sportsdb_search_name(wanted_name))

    exact = [x for x in candidates if norm(x.get("strPlayer")) in {wanted_norm, alias_norm}]
    if exact:
        return exact[0], True

    scored = []
    for x in candidates:
        n = norm(x.get("strPlayer"))
        if not n:
            continue
        score = max(
            SequenceMatcher(None, wanted_norm, n).ratio(),
            SequenceMatcher(None, alias_norm, n).ratio()
        )
        scored.append((score, x))
    scored.sort(key=lambda t: t[0], reverse=True)
    if scored and scored[0][0] >= 0.88:
        return scored[0][1], True
    return None, False

def cartoon_from_player_archive(sid):
    """
    V5: Cartoon direkt aus dem Cartoon-Archiv des konkreten SportsDB-Spielers.
    Gibt nur URLs aus /images/media/player/cartoon/ zurück.
    """
    if not sid:
        return ""
    url=f"https://www.thesportsdb.com/player_art.php?art=cartoon&p={sid}"
    html=get(url, timeout=30).text
    soup=BeautifulSoup(html, "html.parser")

    # Zuerst reguläre <img>-Quellen.
    for img in soup.find_all("img"):
        src=img.get("src") or img.get("data-src") or img.get("data-original") or ""
        if "/images/media/player/cartoon/" in src:
            if src.startswith("//"):
                src="https:"+src
            elif src.startswith("/"):
                src="https://www.thesportsdb.com"+src
            return src

    # Fallback: manche Archive setzen die URL in HTML/JS/CSS.
    m=re.search(r'((?:https?:)?//[^"\'\s<>]+/images/media/player/cartoon/[^"\'\s<>]+)', html)
    if m:
        src=m.group(1)
        if src.startswith("//"):
            src="https:"+src
        return src
    m=re.search(r'(/images/media/player/cartoon/[^"\'\s<>]+)', html)
    if m:
        return "https://www.thesportsdb.com"+m.group(1)
    return ""
POSITION_SET = {"GK","CB","LB","RB","LWB","RWB","CDM","CM","CAM","LM","RM","LW","RW","CF","ST"}

TEAM_ALIASES = {
    "FC Bayern München":["Bayern Munich","Bayern München","FC Bayern Munich"],
    "Bayer 04 Leverkusen":["Leverkusen","Bayer Leverkusen"],
    "Borussia Mönchengladbach":["M'gladbach","Borussia Monchengladbach"],
    "Eintracht Frankfurt":["Frankfurt"],
    "SV Werder Bremen":["Werder Bremen"],
    "1. FC Union Berlin":["Union Berlin"],
    "FC Schalke 04":["Schalke 04"],
    "Inter":["Inter Milan","Inter Milano","Inter Mailand"],
    "AC Milan":["AC Mailand","Milan"],
    "SSC Napoli":["Napoli","SSC Neapel"],
    "AS Roma":["Roma","AS Rom"],
    "Atlético de Madrid":["Atletico Madrid","Atlético Madrid"],
    "FC Barcelona":["Barcelona"],
    "Paris Saint-Germain":["Paris","PSG"],
    "FC Porto":["Porto"],
    "PSV":["PSV Eindhoven"],
    "RC Lens":["Lens","Racing Club De Lens"],
    "LOSC Lille":["Lille","Lille OSC"],
    "Villarreal CF":["Villarreal"],
    "Sporting CP":["Sporting"],
    "Slavia Praha":["Slavia Prague"],
    "Viking FK":["Viking"],
    "Bodø/Glimt":["Bodoe/Glimt","Bodo/Glimt"],
    "RSC Anderlecht":["Anderlecht"],
    "SL Benfica":["Benfica"],
    "AFC Bournemouth":["Bournemouth"],
    "RC Celta":["Celta","Celta Vigo"],
    "GNK Dinamo Zagreb":["GNK Dinamo","Dinamo Zagreb"],
    "Hapoel Be'er Sheva":["H. Beer-Sheva","Hapoel Beer Sheva"],
    "Olympique Lyonnais":["Lyon"],
    "Olympique de Marseille":["Marseille"],
    "Omonia Nicosia":["Omonia"],
    "Stade Rennais":["Rennes"],
    "FC Red Bull Salzburg":["Salzburg","RB Salzburg"],
    "Union Saint-Gilloise":["Union SG"],
    "Viktoria Plzeň":["Viktoria Plzen"],
    "Lillestrøm SK":["Lillestrøm","Lillestrom"],
    "N.E.C.":["NEC Nijmegen","N.E.C. Nijmegen"],
    "Vancouver Whitecaps FC":["Vancouver Whitecaps"],
    "Inter Miami CF":["Inter Miami"],
    "Al Nassr":["Al-Nassr","Al Nassr FC"],
    "Santos":["Santos FC"],
}

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold().replace("&","and")
    return re.sub(r"[^a-z0-9]+","",s)

# V7.3: Die Lookup-Tabellen müssen dieselbe Normalisierung verwenden wie
# Spielernamen. norm("Serhou Guirassy") ergibt z.B. "serhouguirassy".
# Frühere Versionen speicherten dagegen Schlüssel mit Leerzeichen, wodurch
# Alias- und ID-Overrides trotz korrekter Einträge nicht gefunden wurden.
SPORTSDB_NAME_ALIASES = {norm(k): v for k, v in SPORTSDB_NAME_ALIASES.items()}
SPORTSDB_ID_OVERRIDES = {norm(k): str(v) for k, v in SPORTSDB_ID_OVERRIDES.items()}

def get(url, timeout=30):
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r

def discover_ea_url(team: str) -> str | None:
    # 1) DuckDuckGo HTML: searches only official EA team-rating pages.
    query = f'site:ea.com/games/ea-sports-fc/ratings/teams-ratings "{team}"'
    urls = []
    try:
        html = get("https://html.duckduckgo.com/html/?q="+quote_plus(query)).text
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href]"):
            href = a.get("href","")
            if "uddg=" in href:
                try:
                    href = unquote(parse_qs(urlparse(href).query).get("uddg",[""])[0])
                except Exception:
                    pass
            if "/games/ea-sports-fc/ratings/teams-ratings/" in href and "ea.com" in href:
                urls.append(href.split("?")[0])
    except Exception as e:
        print(f"  DDG-Suche fehlgeschlagen: {e}")

    # 2) Bing HTML fallback.
    if not urls:
        try:
            html = get("https://www.bing.com/search?q="+quote_plus(query)).text
            for m in re.findall(r'https?://(?:www\.)?ea\.com/[^"\'<>\s]+/ratings/teams-ratings/[^"\'<>\s]+', html):
                urls.append(m.split("&")[0].split("?")[0])
        except Exception as e:
            print(f"  Bing-Suche fehlgeschlagen: {e}")

    # Prefer a URL whose slug/title resembles the requested team.
    nt = norm(team)
    aliases = [team] + TEAM_ALIASES.get(team,[])
    alias_norms = [norm(x) for x in aliases]
    candidates = []
    for u in dict.fromkeys(urls):
        score = 0
        nu = norm(u)
        if any(a and a in nu for a in alias_norms): score += 5
        candidates.append((score,u))
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]
    return None

def row_player(row, canonical_team):
    a = row.select_one('a[href*="/ratings/player-ratings/"]')
    if not a:
        return None
    href = a.get("href","")
    if href.startswith("/"):
        href = EA_HOST + href
    name = re.sub(r"^#?\d+\s*", "", " ".join(a.stripped_strings)).strip()
    if not name:
        return None
    text = " ".join(row.stripped_strings)
    patterns = {
        "rating": r"(?:OVR|GES)\s*(\d{1,2})",
        "tempo": r"(?:PAC|TEM)\s*(\d{1,2})",
        "schuss": r"(?:SHO|SCH)\s*(\d{1,2})",
        "passen": r"(?:PAS)\s*(\d{1,2})",
        "dribbling": r"(?:DRI)\s*(\d{1,2})",
        "defensive": r"(?:DEF)\s*(\d{1,2})",
        "physis": r"(?:PHY)\s*(\d{1,2})",
    }
    vals={}
    for k,p in patterns.items():
        m=re.search(p,text,re.I)
        if m: vals[k]=int(m.group(1))
    if "rating" not in vals:
        return None
    pos=""
    for token in re.findall(r"\b[A-Z]{2,3}\b", text):
        if token in POSITION_SET:
            pos=token; break
    m = re.search(r"/player-ratings/[^/]+/(\d+)", href)
    ea_id = m.group(1) if m else ""
    return {
        "name":name,
        "search":name,
        "club":canonical_team,
        "eaId":ea_id,
        "eaUrl":href,
        "pos":pos,
        **vals
    }

def fetch_team_players(team, top_n, ea_url):
    if not ea_url:
        raise RuntimeError(f"Keine direkte EA-Männerteam-URL hinterlegt: {team}")
    print(f"EA direkt: {team} -> {ea_url}")
    html=get(ea_url).text
    soup=BeautifulSoup(html,"html.parser")

    # Safety: reject women's team pages explicitly.
    page_text=" ".join(soup.stripped_strings).casefold()
    women_markers=("women’s super league","women's super league","frauen-bundesliga","liga f moeve",
                   "arkema première ligue","national women's soccer league","nwsl")
    if any(x in page_text for x in women_markers):
        raise RuntimeError(f"EA-URL zeigt auf ein Frauenteam: {ea_url}")

    rows=[]; seen=set()
    for tr in soup.select("tr"):
        p=row_player(tr,team)
        if p and p.get("eaId") not in seen:
            rows.append(p); seen.add(p.get("eaId"))
    if len(rows)<top_n:
        raise RuntimeError(f"EA-Seite gelesen, aber nur {len(rows)} auswertbare Spieler gefunden (benötigt {top_n})")
    return rows[:top_n]

def discover_player_url(name, club=""):
    # Bewusst keine Suchmaschine mehr im GitHub-Workflow.
    # Bei manuellen Spielern bleiben vorhandene FC-Werte erhalten.
    return None

def parse_player_page(url, fallback):
    html=get(url).text
    text=" ".join(BeautifulSoup(html,"html.parser").stripped_strings)
    out=dict(fallback)
    out["eaUrl"]=url
    m=re.search(r"/player-ratings/[^/]+/(\d+)",url); 
    if m: out["eaId"]=m.group(1)
    pats={
      "rating":r"(?:overall rating.*?is|Gesamtwertung.*?ist)\s*(\d{1,2})",
      "tempo":r"(?:Pace|Tempo)\s+(\d{1,2})",
      "schuss":r"(?:Shooting|Schüsse)\s+(\d{1,2})",
      "passen":r"(?:Passing|Passen)\s+(\d{1,2})",
      "dribbling":r"Dribbling\s+(\d{1,2})",
      "defensive":r"(?:Defending|Defensive)\s+(\d{1,2})",
      "physis":r"(?:Physicality|Physis)\s+(\d{1,2})",
    }
    for k,p in pats.items():
        m=re.search(p,text,re.I)
        if m: out[k]=int(m.group(1))
    # position from the early "Position XX" area
    m=re.search(r"\bPosition\s+([A-Z]{2,3})\b",text)
    if m: out["pos"]=m.group(1)
    return out

def rarity(rating):
    if rating>=90: return "Legende"
    if rating>=85: return "Gold"
    if rating>=80: return "Silber"
    return "Bronze"

def sportsdb_enrich(rows):
    id_override_hits=0
    alias_hits=0
    """
    V5 Cartoon-Logik:
    1) Vorhandene Cartoons bleiben erhalten.
    2) Bei fehlendem Cartoon wird die SportsDB-Spielerzuordnung neu geprüft.
       Schreibvarianten (z.B. Serhou -> Sehrou Guirassy) werden berücksichtigt.
    3) Danach wird zuerst das Cartoon-Archiv des konkreten Spielers über seine
       SportsDB-ID geprüft.
    4) Erst danach werden wie bisher die Teamseiten als zweite Cartoon-Quelle geprüft.
    5) Es werden ausschließlich /player/cartoon/-Bilder als Cartoon gespeichert.
    """
    before=sum(1 for p in rows if p.get("cartoon"))
    team_candidates={}
    archive_added=0

    # 1) Fehlende Spieler-IDs/Schreibvarianten frisch auflösen und Player-Archive prüfen.
    for idx,p in enumerate(rows, 1):
        if p.get("cartoon"):
            sid=str(p.get("sportsdbId") or "")
            tid=str(p.get("sportsdbTeamId") or "")
            if sid and tid:
                team_candidates.setdefault(sid,set()).add(tid)
            continue

        wanted=p.get("search") or p.get("name") or ""
        wanted_norm=norm(p.get("name") or wanted)
        sid=str(p.get("sportsdbId") or "")
        old_tid=str(p.get("sportsdbTeamId") or "")
        tids=set([old_tid]) if old_tid else set()

        # Verifizierte IDs haben Vorrang.
        override_sid = (
            SPORTSDB_ID_OVERRIDES.get(norm(p.get("name") or ""))
            or SPORTSDB_ID_OVERRIDES.get(norm(p.get("search") or ""))
            or SPORTSDB_ID_OVERRIDES.get(wanted_norm)
        )
        if override_sid:
            if str(p.get("sportsdbId") or "") != str(override_sid):
                id_override_hits += 1
            sid=str(override_sid)
            p["sportsdbId"]=sid

        try:
            query=sportsdb_search_name(wanted)
            data=get(SPORTSDB+quote_plus(query)).json()
            candidates=data.get("player") or []
            x, trusted = best_sportsdb_candidate(candidates, p.get("name") or wanted)

            if x:
                fresh_sid=str(x.get("idPlayer") or "")
                fresh_tid=str(x.get("idTeam") or "")
                if fresh_sid and (trusted or not sid):
                    # Ein verifizierter Override wird nicht durch einen abweichenden
                    # unsicheren Suchtreffer überschrieben.
                    if not override_sid or fresh_sid == override_sid:
                        p["sportsdbId"]=fresh_sid
                        sid=fresh_sid
                if fresh_tid:
                    tids.add(fresh_tid)
                    p["sportsdbTeamId"]=fresh_tid

            time.sleep(2.1)
        except Exception as e:
            print(f"SportsDB Suche {p.get('name','?')}: {e}")

        # V5-Kern: direktes Player-Cartoon-Archiv.
        if sid and not p.get("cartoon"):
            try:
                src=cartoon_from_player_archive(sid)
                if src and "/images/media/player/cartoon/" in src:
                    p["cartoon"]=src
                    archive_added+=1
                    print(f"Cartoon-Archiv: {p.get('name')} -> {sid}")
                time.sleep(.8)
            except Exception as e:
                print(f"Cartoon-Archiv {p.get('name','?')} ({sid}): {e}")

        if sid and tids:
            team_candidates.setdefault(sid,set()).update(tids)

    # 2) Teamseiten als zusätzliche Quelle für weiterhin fehlende Cartoons.
    all_team_ids=sorted({tid for tids in team_candidates.values() for tid in tids if tid})
    cartoon_by_id={}
    for tid in all_team_ids:
        try:
            html=get(f"https://www.thesportsdb.com/team/{tid}?view=7#playerImages").text
            soup=BeautifulSoup(html,"html.parser")
            for a in soup.select('a[href*="/player/"]'):
                m=re.search(r"/player/(\d+)",a.get("href",""))
                img=a.find("img")
                if not m or not img:
                    continue
                src=img.get("src") or img.get("data-src") or img.get("data-original") or ""
                if "/images/media/player/cartoon/" in src:
                    if src.startswith("//"):
                        src="https:"+src
                    elif src.startswith("/"):
                        src="https://www.thesportsdb.com"+src
                    cartoon_by_id[m.group(1)]=src
            time.sleep(.8)
        except Exception as e:
            print(f"Cartoon-Team {tid}: {e}")

    team_added=0
    for p in rows:
        if p.get("cartoon"):
            continue
        sid=str(p.get("sportsdbId") or "")
        if sid in cartoon_by_id:
            p["cartoon"]=cartoon_by_id[sid]
            team_added+=1

    after=sum(1 for p in rows if p.get("cartoon"))
    missing_rows=[p for p in rows if not p.get("cartoon")]
    missing_with_id=[p for p in missing_rows if p.get("sportsdbId")]
    missing_without_id=[p for p in missing_rows if not p.get("sportsdbId")]

    print("\n" + "="*62)
    print("THESPORTSDB / CARTOON-AUSWERTUNG")
    print("="*62)
    print(f"Spieler insgesamt:                         {len(rows)}")
    print(f"Cartoons vorhanden:                       {after}")
    print(f"Ohne Cartoon:                             {len(missing_rows)}")
    print(f"  SportsDB-ID vorhanden, aber kein Bild:  {len(missing_with_id)}")
    print(f"  Kein SportsDB-Treffer / keine ID:       {len(missing_without_id)}")
    print(f"Neu über Cartoon-Archiv gefunden:         {archive_added}")
    print(f"Neu über Team-Seiten gefunden:            {team_added}")
    print(f"Verwendete Namensvarianten:               {alias_hits}")
    print(f"Verwendete feste SportsDB-ID-Zuordnungen: {id_override_hits}")

    if missing_without_id:
        print("\nKEIN SPORTSDb-TREFFER – Namensvarianten prüfen:")
        for p in sorted(missing_without_id, key=lambda x: (-(int(x.get("rating") or 0)), norm(x.get("name")))):
            print(f" - {p.get('name','?')} | {p.get('club','?')} | OVR {p.get('rating','?')}")

    if missing_with_id:
        print("\nSPORTSDB-ID VORHANDEN, ABER KEIN CARTOON (erste 40):")
        for p in sorted(missing_with_id, key=lambda x: (-(int(x.get("rating") or 0)), norm(x.get("name"))))[:40]:
            print(f" - {p.get('name','?')} | {p.get('club','?')} | ID {p.get('sportsdbId')} | OVR {p.get('rating','?')}")
    print("="*62)


def load_existing():
    if not PLAYERS_FILE.exists(): return []
    return json.loads(PLAYERS_FILE.read_text(encoding="utf-8"))

def write_one_line(rows):
    lines=["["]
    for i,p in enumerate(rows):
        lines.append("  "+json.dumps(p,ensure_ascii=False,separators=(",",":"))+("," if i<len(rows)-1 else ""))
    lines.append("]")
    PLAYERS_FILE.write_text("\n".join(lines)+"\n",encoding="utf-8")

def main():
    cfg=json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    existing=load_existing()
    old_by_ea={str(p.get("eaId")):p for p in existing if p.get("eaId")}
    old_by_name={norm(p.get("name")):p for p in existing if p.get("name")}
    max_id=max([int(p.get("id",0)) for p in existing]+[0])
    next_id=max(max_id+1,281)

    # Preserve manual rows (easy future editing).
    manual=[dict(p) for p in existing if p.get("manual") is True]

    team_url_cache={}
    merged={}
    failures=[]

    for comp_id,comp in cfg["competitions"].items():
        n=int(comp["top_n"])
        for team_cfg in comp["teams"]:
            if isinstance(team_cfg,str):
                team=team_cfg; ea_url=None
            else:
                team=team_cfg["name"]; ea_url=team_cfg.get("ea_url")
            try:
                ps=fetch_team_players(team,n,ea_url)
            except Exception as e:
                failures.append(f"{comp_id}: {team}: {e}")
                print("FEHLER",failures[-1]); continue
            for p in ps:
                key=("ea",p.get("eaId")) if p.get("eaId") else ("name",norm(p["name"]),norm(p["club"]))
                old=old_by_ea.get(str(p.get("eaId"))) or old_by_name.get(norm(p["name"])) or {}
                if key not in merged:
                    rec=dict(old)
                    # EA-Werte dürfen aktualisiert werden; bereits erfolgreich
                    # gefundene TheSportsDB-Zuordnungen bleiben aber erhalten.
                    known_sportsdb={k:old.get(k) for k in ("sportsdbId","sportsdbTeamId","cartoon") if old.get(k)}
                    rec.update(p)
                    for k,v in known_sportsdb.items():
                        if not rec.get(k):
                            rec[k]=v
                    rec["competitions"]=[]
                    merged[key]=rec
                if comp_id not in merged[key]["competitions"]:
                    merged[key]["competitions"].append(comp_id)
            time.sleep(.5)

    # Manual rows: keep and update FC27 values when possible.
    for m in manual:
        name=m["name"]; club=m.get("club","")
        # If same player was already included by a competition, just add manual categories.
        same=None
        for k,r in merged.items():
            if norm(r.get("name"))==norm(name):
                same=r; break
        if same is not None:
            for c in m.get("competitions",[]):
                if c not in same["competitions"]: same["competitions"].append(c)
            same["manual"]=True
            continue
        url=m.get("eaUrl") or discover_player_url(name,club)
        rec=dict(m)
        if url:
            try: rec=parse_player_page(url,rec)
            except Exception as e: print(f"EA Einzelspieler {name}: {e}")
        key=("ea",rec.get("eaId")) if rec.get("eaId") else ("manual",norm(name),norm(club))
        merged[key]=rec

    # Sicherheitsnetz: Wenn eine EA-Seite vorübergehend ausfällt, vorhandene
    # automatische Spieler NICHT aus players.json löschen.
    present_names={norm(x.get("name")) for x in merged.values()}
    for old in existing:
        if old.get("manual") is True:
            continue
        if norm(old.get("name")) not in present_names:
            merged[("preserved",str(old.get("id") or norm(old.get("name"))))]=dict(old)

    rows=list(merged.values())

    # Stable app IDs: preserve old IDs, then assign new IDs.
    used=set()
    for p in rows:
        if p.get("id"):
            try: used.add(int(p["id"]))
            except: pass
    for p in rows:
        old=old_by_ea.get(str(p.get("eaId"))) or old_by_name.get(norm(p.get("name"))) or {}
        if old.get("id") and not p.get("id"):
            p["id"]=old["id"]; used.add(int(old["id"]))
        if not p.get("id"):
            while next_id in used: next_id+=1
            p["id"]=next_id; used.add(next_id); next_id+=1

        p["search"]=p.get("search") or p["name"]
        p["rarity"]=rarity(int(p.get("rating") or 0))
        p["theme"]="fussball"; p["emoji"]="⚽"; p["color"]="#1f6f50"
        # predictable category order
        order=["bundesliga","champions","europa","restderwelt"]
        p["competitions"]=sorted(set(p.get("competitions",[])),key=lambda x:order.index(x) if x in order else 99)

    # Reuse existing cartoon / SportsDB data wherever possible.
    for p in rows:
        old=old_by_ea.get(str(p.get("eaId"))) or old_by_name.get(norm(p.get("name"))) or {}
        for k in ("sportsdbId","sportsdbTeamId","cartoon"):
            if old.get(k) and not p.get(k): p[k]=old[k]

    # V7.2: Feste TheSportsDB-IDs nochmals unmittelbar vor dem Enrichment
    # anwenden. So bleiben bekannte Zuordnungen unabhängig von Alias-/Suchlogik
    # garantiert am Spieler hängen.
    for p in rows:
        fixed_sid = (
            SPORTSDB_ID_OVERRIDES.get(norm(p.get("name") or ""))
            or SPORTSDB_ID_OVERRIDES.get(norm(p.get("search") or ""))
        )
        if fixed_sid:
            p["sportsdbId"] = str(fixed_sid)

    sportsdb_enrich(rows)

    # Sicherheitsprüfung: Ein fester Override darf nach dem Enrichment niemals
    # fehlen oder durch einen anderen Treffer ersetzt worden sein.
    override_repairs=0
    for p in rows:
        fixed_sid = (
            SPORTSDB_ID_OVERRIDES.get(norm(p.get("name") or ""))
            or SPORTSDB_ID_OVERRIDES.get(norm(p.get("search") or ""))
        )
        if fixed_sid and str(p.get("sportsdbId") or "") != str(fixed_sid):
            p["sportsdbId"] = str(fixed_sid)
            override_repairs += 1
    if override_repairs:
        print(f"SportsDB-ID Sicherheitsreparaturen: {override_repairs}")

    comp_order={"bundesliga":0,"champions":1,"europa":2,"restderwelt":3}
    def sortkey(p):
        cs=p.get("competitions") or ["zzz"]
        first=min([comp_order.get(c,9) for c in cs] or [9])
        return (first, norm(p.get("club")), -(int(p.get("rating") or 0)), norm(p.get("name")))
    rows.sort(key=sortkey)

    # consistent field order
    field_order=["id","name","search","club","competitions","manual","eaId","eaUrl","pos","rating","rarity",
                 "tempo","schuss","passen","dribbling","defensive","physis","theme","emoji","color",
                 "sportsdbId","sportsdbTeamId","cartoon"]
    clean=[]
    for p in rows:
        clean.append({k:p[k] for k in field_order if k in p and p[k] not in (None,"")})
    write_one_line(clean)

    print(f"\nFERTIG: {len(clean)} Spieler in players.json")
    if failures:
        print("\nNicht automatisch geladene Teams:")
        for x in failures: print(" -",x)
        print("Die Action endet trotzdem erfolgreich, damit bereits gefundene Daten nicht verloren gehen.")

if __name__=="__main__":
    main()
