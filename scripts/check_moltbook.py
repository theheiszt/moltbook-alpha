import sys
sys.path.insert(0, ".")
from moltbook_client import MoltbookClient

client = MoltbookClient()
home = client.get_home()

print("--- Activity on Your Posts ---")
act = home.get("activity_on_your_posts", [])
for a in act[:5]:
    print(a)

print("\n--- Explore ---")
exp = home.get("explore", {})
if isinstance(exp, dict):
    for k, v in exp.items():
        print(f"Explore key '{k}': {type(v)} (len {len(v) if hasattr(v, '__len__') else 0})")
        if isinstance(v, list) and v:
            for item in v[:3]:
                if isinstance(item, dict):
                    print(f"  [{item.get('id')}] {item.get('title')} by @{item.get('author', {}).get('username') if isinstance(item.get('author'), dict) else item.get('author')}")
                else:
                    print("  ", item)
elif isinstance(exp, list):
    for item in exp[:5]:
        print(item)
