import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")
from moltbook_client import MoltbookClient

client = MoltbookClient()

def inspect_post(post_id, label=""):
    print(f"\n==========================================")
    print(f"POST: {post_id} ({label})")
    print(f"==========================================")
    res = client._request(f"/posts/{post_id}/comments?sort=old&limit=50")
    comments = res.get("comments") or res.get("data") or []
    print(f"Total comments: {len(comments)}")
    for c in comments:
        c_id = c.get("id")
        author = c.get("author", {})
        author_name = author.get("name") if isinstance(author, dict) else str(author)
        parent = c.get("parent_id") or c.get("parentId")
        content = c.get("content", "")
        print(f"\n--- [{c_id}] by @{author_name} (parent: {parent}) ---")
        print(content)

if __name__ == "__main__":
    inspect_post("e2ae1289-a20b-4bd4-ba46-1af0fd1fc6cc", "agentfinance")
    inspect_post("65053feb-4217-4818-b1b7-b4509553db59", "builds")
    inspect_post("186309a4-fc7b-46b7-8977-9102ed1b4c6b", "x402-billing")
