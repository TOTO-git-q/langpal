"""Install a world book and its event rules into a running LangPal backend, through its API.

    python authoring/lore/install.py http://127.0.0.1:8787 ame-ngo --persona 糖糖

Idempotent: a book or rule with the same name is updated, not duplicated. The book is attached to the persona whose name
starts with --persona; rules whose "persona" is not null are limited to that persona.
"""
import argparse
import json
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base")
    parser.add_argument("name")
    parser.add_argument("--persona", required=True)
    args = parser.parse_args()
    client = httpx.Client(base_url=args.base.rstrip("/") + "/api", timeout=30, headers={"Origin": args.base.rstrip("/")})

    def call(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise SystemExit(f"{method} {path} -> {response.status_code} {response.text[:300]}")
        return response.json()

    personas = call("GET", "/personas")["items"]
    persona = next((p for p in personas if p["name"].startswith(args.persona)), None)
    if persona is None:
        raise SystemExit("no persona whose name starts with " + args.persona)

    spec = json.loads((HERE / f"{args.name}.book.json").read_text(encoding="utf-8"))
    books = call("GET", "/lore/books")["items"]
    existing = next((b for b in books if b["name"] == spec["name"]), None)
    if existing:
        book = call("PUT", f"/lore/books/{existing['id']}", json=spec)
    else:
        book = call("POST", "/lore/books", json=spec)
    profile = dict(persona.get("profile") or {})
    attached = list(profile.get("world_book_ids") or [])
    if book["id"] not in attached:
        profile["world_book_ids"] = attached + [book["id"]]
        call("PUT", f"/personas/{persona['id']}", json={"name": persona["name"], "language": persona["language"], "profile": profile})

    rules = json.loads((HERE / f"{args.name}.rules.json").read_text(encoding="utf-8"))
    current = {r["name"]: r for r in call("GET", "/hooks/rules")["items"]}
    for rule in rules:
        body = {k: v for k, v in rule.items() if k != "persona"}
        body["persona_ids"] = [persona["id"]] if rule.get("persona") else None
        if rule["name"] in current:
            call("PUT", f"/hooks/rules/{current[rule['name']]['id']}", json=body)
        else:
            call("POST", "/hooks/rules", json=body)
    print(json.dumps({"book_id": book["id"], "entries": len(spec["book"]["entries"]), "rules": len(rules), "persona_id": persona["id"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
