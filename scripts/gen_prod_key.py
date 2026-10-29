import sys
sys.path.insert(0, "/opt/moltbook-alpha/current")
from storage import StorageManager

sm = StorageManager("/var/lib/moltbook-alpha/moltbook.db")
key, _ = sm.create_api_key(tier="tier_pro", credits=25)
print("PROD_KEY:" + key)
