"""Läser apexbantrackers RSS-flöde och postar nya/ändrade poster till en Discord-webhook."""
import hashlib, html, json, os, re, sys, time
from pathlib import Path

import feedparser
import requests

FEED_URL = os.environ.get("FEED_URL", "https://apexbantracker.com/api/leaderboard/cutoff/feed.xml?platform=PC")
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
STATE_FILE = Path("state.json")


def rensa(text, maxlen):
    text = html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()
    return text[: maxlen - 1] + "…" if len(text) > maxlen else text


def fingeravtryck(e):
    raw = "|".join([e.get("title", ""), e.get("summary", ""), e.get("updated", "") or e.get("published", "")])
    return hashlib.sha256(raw.encode()).hexdigest()


def posta(e):
    embed = {
        "title": rensa(e.get("title", "Pred cutoff"), 256) or "Pred cutoff",
        "description": rensa(e.get("summary", ""), 4000),
        "color": 0xDA292A,
    }
    if e.get("link"):
        embed["url"] = e["link"]
    t = e.get("updated_parsed") or e.get("published_parsed")
    if t:
        embed["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", t)
    r = requests.post(
        WEBHOOK_URL + "?wait=true",
        json={"embeds": [embed], "allowed_mentions": {"parse": []}},  # pinga aldrig någon
        timeout=20,
    )
    r.raise_for_status()
    time.sleep(1)  # undvik Discords rate limit


def main():
    resp = requests.get(FEED_URL, headers={"User-Agent": "pred-cutoff-discord/1.0"}, timeout=30)
    resp.raise_for_status()
    entries = feedparser.parse(resp.content).entries
    if not entries:
        print("Flödet var tomt, inget att göra.")
        return

    forsta_gangen = not STATE_FILE.exists()
    sedda = {} if forsta_gangen else json.loads(STATE_FILE.read_text()).get("seen", {})

    nya = []
    for e in entries:
        pid = e.get("id") or e.get("link") or e.get("title", "")
        fp = fingeravtryck(e)
        if sedda.get(pid) != fp:
            nya.append(e)
        sedda[pid] = fp

    if forsta_gangen:
        print("Första körningen: postar bara senaste posten.")
        posta(entries[0])
    else:
        for e in reversed(nya):  # äldst först
            posta(e)
        print(f"Postade {len(nya)} ny(a) uppdatering(ar).")

    aktuella = {e.get("id") or e.get("link") or e.get("title", "") for e in entries}
    STATE_FILE.write_text(json.dumps({"seen": {k: v for k, v in sedda.items() if k in aktuella}}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(f"Fel: {err}", file=sys.stderr)
        sys.exit(1)
