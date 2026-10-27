import json
from dotenv import load_dotenv
load_dotenv()
from src.tools.search import fetch_hacker_news_pain_points
posts = fetch_hacker_news_pain_points(queries=["Ask HN tool you wish existed"], limit_per_query=5)[:5]
with open("posts.json", "w", encoding="utf-8") as f:
    json.dump([p.model_dump() for p in posts], f, indent=2)
print("Wrote", len(posts), "posts")
