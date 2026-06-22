"""Quick live smoke test for POST /recommend and GET /health."""

import json
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "http://127.0.0.1:8000"


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status, json.load(resp)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as resp:
        return resp.status, json.load(resp)


print("== GET /health ==")
status, body = get("/health")
print(status, body)

print("\n== POST /recommend ==")
status, body = post(
    "/recommend",
    {
        "query": "cozy vegetarian place for a date in Indiranagar",
        "filters": {"min_rating": 4.0, "max_cost_for_two": 1500},
        "top_n": 3,
    },
)
print("status:", status)
print("query_understood:", json.dumps(body["query_understood"], ensure_ascii=False))
print("notes:", body.get("notes"))
print("meta:", body["meta"])
for x in body["recommendations"]:
    print(f"\n#{x['rank']} {x['name']} [{x['restaurant_id']}]")
    print(f"   {x['rating']}/5 | Rs.{x['average_cost_for_two']} | score={x['match_score']}")
    print(f"   {x['reason']}")
