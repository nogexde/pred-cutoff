"""Läser apexbantrackers RSS-flöde och håller ett Discord-meddelande per dag som uppdateras live."""
import hashlib, html, json, os, re, sys, time
from pathlib import Path

import feedparser
import requests

FEED_URL = os.environ.get("FEED_URL", "https://apexbantracker.com/api/leaderboard/cutoff/feed.xml?platform=PC")
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].split("?")[0].rstrip("/")
STATE_FILE = Path("state.json")
DATUM = re.compile(r"\d{4}-\d{2}-\d{2}")


def rensa(text, maxlen):
    text = html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()
    return text[: maxlen - 1] + "…" if len(text) > maxlen else text


def dag(e):
    """Vilken dag posten gäller: första datumet i texten, annars postens egen tidsstämpel."""
    m = DATUM.search(e.get("summary", "")) or DATUM.search(e.get("title", ""))
    if m:
        return m.group(0)
    t = e.get("published_parsed") or e.get("updated_parsed")
    return time.strftime("%Y-%m-%d", t) if t else (e.get("id") or e.get("link") or e.get("title", ""))


def fingeravtryck(e):
    return hashlib.sha256((e.get("title", "") + "|" + e.get("summary", "")).encode()).hexdigest()


def embed(e):
    em = {
        "title": rensa(e.get("title", "Pred cutoff"), 256) or "Pred cutoff",
        "description": rensa(e.get("summary", ""), 4000),
        "color": 0xDA292A,
    }
    if e.get("link"):
        em["url"] = e["link"]
    t = e.get("updated_parsed") or e.get("published_parsed")
    em["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", t or time.gmtime())
    return {"embeds": [em], "allowed_mentions": {"parse": []}}  # pinga aldrig någon


def posta(e):
    r = requests.post(WEBHOOK_URL + "?wait=true", json=embed(e), timeout=20)
    r.raise_for_status()
    time.sleep(1)
    return r.json()["id"]


def redigera(msg_id, e):
    """Uppdaterar ett befintligt meddelande. Returnerar False om det har tagits bort."""
    r = requests.patch(f"{WEBHOOK_URL}/messages/{msg_id}", json=embed(e), timeout=20)
    if r.status_code == 404:
        return False
    r.raise_for_status()
    time.sleep(1)
    return True


def main():
    resp = requests.get(FEED_URL, headers={"User-Agent": "pred-cutoff-discord/1.0"}, timeout=30)
    resp.raise_for_status()
    entries = feedparser.parse(resp.content).entries
    if not entries:
        print("Flödet var tomt, inget att göra.")
        return

    # En post per dag: den först listade (nyaste) vinner om flera gäller samma dag.
    per_dag = {}
    for e in entries:
        per_dag.setdefault(dag(e), e)

    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    dagar = state.get("days")
    forsta_gangen = dagar is None
    dagar = dagar or {}
    senaste = max(per_dag)

    for d in sorted(per_dag):
        e, fp = per_dag[d], fingeravtryck(per_dag[d])
        info = dagar.get(d, {})
        if info.get("fp") == fp:
            continue
        if forsta_gangen and d != senaste:
            dagar[d] = {"fp": fp}  # posta inte gammal historik vid start
            continue
        if info.get("msg") and redigera(info["msg"], e):
            print(f"{d}: uppdaterade meddelandet.")
            dagar[d] = {"fp": fp, "msg": info["msg"]}
        elif d not in dagar or d == senaste:
            dagar[d] = {"fp": fp, "msg": posta(e)}
            print(f"{d}: postade nytt meddelande.")
        else:
            dagar[d] = {"fp": fp}  # gammal dag utan meddelande: posta inte igen

    # Spara bara dagar som fortfarande finns i flödet.
    STATE_FILE.write_text(json.dumps({"days": {d: v for d, v in dagar.items() if d in per_dag}}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(f"Fel: {err}", file=sys.stderr)
        sys.exit(1)
