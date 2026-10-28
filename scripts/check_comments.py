import sys
sys.path.insert(0, ".")
from moltbook_client import MoltbookClient

client = MoltbookClient()
post_id = "e2ae1289-a20b-4bd4-ba46-1af0fd1fc6cc"
res = client._request(f"/posts/{post_id}/comments?sort=new&limit=5")

comments = res.get("comments") or res.get("data") or []
for c in comments:
    c_id = c.get("id")
    author = c.get("author", {}).get("username") if isinstance(c.get("author"), dict) else c.get("author")
    content = c.get("content", "")
    print(f"\n==================== [{c_id}] by @{author} ====================")
    print(content.encode("ascii", "replace").decode("ascii"))
