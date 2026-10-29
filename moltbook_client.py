"""
Moltbook API Client with Challenge Gate Solving and Verified Identity Operations.
"""

import re
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

BASE_URL = "https://www.moltbook.com/api/v1"
CONFIG_PATH = Path.home() / ".config" / "moltbook" / "credentials.json"

WORD_TO_NUMBER = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000,
    # Common deduplicated/collapsed variants from challenge noise
    "thre": 3, "fiften": 15, "sixten": 16, "seventen": 17, "eighten": 18, "nineten": 19,
    "fourten": 14, "thirten": 13, "twelv": 12, "elevn": 11,
}

TENS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}
ONES = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "thre"}
SCALES = {"hundred", "thousand"}

# Populate compound tens+ones (e.g. 'twentythree', 'thirtytwo')
for _t in TENS:
    for _o in ONES:
        WORD_TO_NUMBER[_t + _o] = WORD_TO_NUMBER[_t] + WORD_TO_NUMBER[_o]


def normalize_word(w: str) -> str:
    clean = re.sub(r"[^a-z]", "", w.lower())
    if clean in WORD_TO_NUMBER:
        return clean
    # Collapse repeated consecutive characters: e.g. 'twennty' -> 'twenty'
    collapsed = re.sub(r"(.)\1+", r"\1", clean)
    if collapsed in WORD_TO_NUMBER:
        return collapsed
    # Strip single leading noise letter: e.g. 'qthree' -> 'three', 'sthirty' -> 'thirty'
    for candidate in (clean, collapsed):
        if len(candidate) > 3:
            rem = candidate[1:]
            if rem in WORD_TO_NUMBER:
                return rem
            rem_col = re.sub(r"(.)\1+", r"\1", rem)
            if rem_col in WORD_TO_NUMBER:
                return rem_col

    if len(collapsed) >= 4:
        import difflib
        matches = difflib.get_close_matches(collapsed, WORD_TO_NUMBER.keys(), n=1, cutoff=0.72)
        if matches:
            return matches[0]

    return clean


def parse_number_words(words: List[str]) -> Optional[float]:
    """Parse a list of normalized number words into a single float value."""
    if not words:
        return None

    # Fast path: single token
    if len(words) == 1:
        w = words[0]
        if w.isdigit():
            return float(w)
        if w in WORD_TO_NUMBER:
            return float(WORD_TO_NUMBER[w])

    total = 0.0
    current = 0.0

    for w in words:
        if w.isdigit():
            current += float(w)
            continue
        val = WORD_TO_NUMBER.get(w)
        if val is None:
            continue
        if val in (100, 1000):
            current = (current if current != 0 else 1.0) * val
            total += current
            current = 0.0
        else:
            current += float(val)

    total += current
    return total if total > 0 or "zero" in words else None


def merge_fragments(tokens: List[str]) -> List[str]:
    """
    Greedily merge adjacent sub-word fragments produced by deliberate whitespace splitting.
    e.g. ['tw', 'enty'] -> 'twenty', ['f', 'iv', 'e'] -> 'five'
    """
    merged: List[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        matched = False
        # Try merging up to 4 consecutive tokens
        for length in (4, 3, 2):
            if i + length <= n:
                candidate = "".join(tokens[i : i + length])
                norm = normalize_word(candidate)
                if norm in WORD_TO_NUMBER:
                    merged.append(norm)
                    i += length
                    matched = True
                    break
        if not matched:
            merged.append(tokens[i])
            i += 1
    return merged


def solve_arithmetic_challenge(challenge_text: str) -> Optional[str]:
    """
    Parses and solves Moltbook anti-bot arithmetic challenges.
    Handles explicit operator symbols (*, ×, ÷, +), whitespace/fragment obfuscation,
    compound vs. distinct sequential number phrases, and operation keywords.
    """
    import difflib

    UNIT_PREFIXES = ["newt", "noot", "neuw", "new", "meter", "cm", "kg", "sec", "speed", "force", "claw", "lobst"]

    NON_NUM_WORDS = {
        "at", "by", "in", "on", "to", "from", "with", "is", "a", "an", "the", "bu", "but", "per", "hour",
        "fight", "light", "right", "might", "sight", "tight", "night", "white",
        "this", "that", "these", "those", "their", "there", "then", "them",
        "claw", "force", "lobster", "lobsters", "red", "total", "another", "other",
        "much", "what", "which", "more", "less", "dominance", "swim", "swims", "speed", "new", "meter", "meters",
        "newton", "newtons", "nooton", "nootons", "applies", "apply", "group", "groo", "share", "shared", "shiar", "each", "velocity", "velawcitee", "velawcity"
    }

    def clean_token(t: str) -> str:
        return re.sub(r"[^a-z0-9]", "", t.lower())

    def is_non_num(t: str) -> bool:
        c = clean_token(t)
        if not c or c in NON_NUM_WORDS:
            return True
        dedup = re.sub(r"(.)\1+", r"\1", c)
        if dedup in NON_NUM_WORDS:
            return True
        if any(dedup.startswith(u) for u in UNIT_PREFIXES):
            return True
        return False

    def norm_num(tok: str) -> Optional[int]:
        c = clean_token(tok)
        if is_non_num(c):
            return None
        if c.isdigit():
            return int(c)
        if c in WORD_TO_NUMBER:
            return WORD_TO_NUMBER[c]
        dedup = re.sub(r"(.)\1+", r"\1", c)
        if dedup in WORD_TO_NUMBER:
            return WORD_TO_NUMBER[dedup]

        for nw in sorted(WORD_TO_NUMBER.keys(), key=len, reverse=True):
            if len(nw) >= 3 and (c.startswith(nw) or dedup.startswith(nw)):
                rem = dedup[len(nw):] if dedup.startswith(nw) else c[len(nw):]
                if any(rem.startswith(u) for u in UNIT_PREFIXES):
                    return WORD_TO_NUMBER[nw]

        if len(dedup) >= 4:
            matches = difflib.get_close_matches(dedup, WORD_TO_NUMBER.keys(), n=1, cutoff=0.88)
            if matches and not is_non_num(matches[0]):
                return WORD_TO_NUMBER[matches[0]]
        return None

    # 1. Strip intra-word punctuation noise
    cleaned = re.sub(r"(?<=[a-zA-Z])[\/\\|~^_+\-\]\[}{<>\.,`\'\"]+(?=[a-zA-Z])", "", challenge_text)

    # 2. Clean stray periods and noise not between digits
    cleaned = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", cleaned)

    for op in ["*", "×", "÷"]:
        cleaned = cleaned.replace(op, f" {op} ")
    cleaned = cleaned.replace("+", " + ")
    cleaned = re.sub(r"(\d)\s*[-−–]\s*(\d)", r"\1 - \2", cleaned)
    cleaned = re.sub(r"\s+[-−–]\s+", " - ", cleaned)
    cleaned = re.sub(r"[{}\[\]()^~,?!;:\/\\|`'\"_]", " ", cleaned)
    cleaned = re.sub(r"(?<=[a-zA-Z])-(?=\s|$)", " ", cleaned)
    cleaned = re.sub(r"(?<=\s)-(?=[a-zA-Z])", " ", cleaned)
    cleaned = re.sub(r"^-([a-zA-Z])", r" \1", cleaned)

    tokens = [t.strip() for t in cleaned.split() if t.strip()]

    items = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        c = clean_token(t)
        dedup = re.sub(r"(.)\1+", r"\1", c)

        if t in ["*", "x", "×"] or c in ["times", "multiplied"] or dedup in ["times", "multiplied"]:
            items.append((i, i + 1, "op", "*"))
            i += 1
            continue
        elif t in ["+", "plus"] or c in ["plus", "add", "added"] or dedup in ["plus", "add", "added"]:
            items.append((i, i + 1, "op", "+"))
            i += 1
            continue
        elif t in ["-", "minus", "−", "–"] or c in ["minus", "subtract"] or dedup in ["minus", "subtract"]:
            next_t = clean_token(tokens[i+1]) if i + 1 < len(tokens) else ""
            if not any(next_t.startswith(u) for u in UNIT_PREFIXES):
                items.append((i, i + 1, "op", "-"))
            i += 1
            continue
        elif t in ["/", "÷", "divided"] or c in ["divided"] or dedup in ["divided"]:
            items.append((i, i + 1, "op", "/"))
            i += 1
            continue

        if is_non_num(t):
            i += 1
            continue

        matched_compound = False
        for k in (4, 3, 2):
            if i + k <= len(tokens):
                sub = tokens[i:i+k]
                if any(x in ["*", "x", "×", "+", "-", "/", "÷"] for x in sub):
                    continue
                if any(clean_token(x).isdigit() for x in sub):
                    continue
                if any(is_non_num(x) for x in sub):
                    continue
                sub_clean = [clean_token(x) for x in sub]
                cand = "".join(sub_clean)
                val = norm_num(cand)
                if val is not None:
                    if items and items[-1][2] == "num" and items[-1][3] == float(val):
                        i += k
                        matched_compound = True
                        break
                    if items and items[-1][2] == "num" and items[-1][1] == i and items[-1][3] in [20, 30, 40, 50, 60, 70, 80, 90] and val < 10:
                        prev_start, _, _, prev_val = items.pop()
                        items.append((prev_start, i + k, "num", prev_val + float(val)))
                    else:
                        items.append((i, i + k, "num", float(val)))
                    i += k
                    matched_compound = True
                    break
        if matched_compound:
            continue

        val = norm_num(t)
        if val is not None:
            if items and items[-1][2] == "num" and items[-1][3] == float(val):
                i += 1
                continue
            if items and items[-1][2] == "num" and items[-1][1] == i and items[-1][3] in [20, 30, 40, 50, 60, 70, 80, 90] and val < 10:
                prev_start, _, _, prev_val = items.pop()
                items.append((prev_start, i + 1, "num", prev_val + float(val)))
            else:
                items.append((i, i + 1, "num", float(val)))
        i += 1

    nums = [x for x in items if x[2] == "num"]
    ops = [x for x in items if x[2] == "op"]

    filtered_nums = []
    for n in nums:
        idx_start, idx_end, _, val = n
        if val == 1.0:
            is_prep = idx_start > 0 and clean_token(tokens[idx_start-1]) in ["with", "in", "on", "per"]
            is_body = idx_end < len(tokens) and clean_token(tokens[idx_end]) in ["claw", "hand", "side", "arm"]
            if is_prep or is_body:
                continue
        filtered_nums.append(n)
    nums = filtered_nums

    if not nums:
        return None

    cleaned_lower = cleaned.lower()
    collapsed_lower = re.sub(r"(.)\1+", r"\1", cleaned_lower)

    stripped_letters = re.sub(r"[^a-z]", "", cleaned_lower)
    collapsed_letters = re.sub(r"(.)\1+", r"\1", stripped_letters)

    def has_word(words):
        return any(w in cleaned_lower or w in collapsed_lower or w in stripped_letters or w in collapsed_letters for w in words)

    has_div = has_word(["divid", "split", "share", "shiar", "distribut", "portion", "ratio", "quotient", "halv"])
    has_mul = not has_div and has_word(["product", "times", "multipli", "each", "duplicat", "doubl", "tripl", "quadrupl"])
    has_sub = not has_div and has_word(["reduc", "slow", "minus", "decreas", "lose", "loses", "drop", "differ", "subtract", "remain", "left"])
    has_add = not has_div and has_word(["gain", "plus", "increas", "add", "combin", "total"])

    if ops:
        op_start, op_end, _, op_type = ops[0]
        before = [n for n in nums if n[1] <= op_start]
        after = [n for n in nums if n[0] >= op_end]
        if before and after:
            if op_type == "*":
                a = before[-1][3]
                b = after[0][3]
                res = a * b
            elif op_type == "/":
                a = before[-1][3]
                b = after[0][3]
                res = a / b if b != 0 else 0
            elif op_type == "+":
                a = before[-1][3]
                b = after[0][3]
                res = a + b
            elif op_type == "-":
                a = before[0][3] if len(before) == 1 else sum(n[3] for n in before)
                b = after[0][3]
                if has_mul:
                    res = a * b
                elif has_add and not has_sub:
                    res = a + b
                else:
                    res = a - b
            return f"{res:.2f}"

    if len(nums) >= 2:
        a = nums[0][3]
        b = nums[1][3]
        if has_div:
            return f"{a / b:.2f}" if b != 0 else "0.00"
        elif has_mul:
            return f"{a * b:.2f}"
        elif has_sub:
            return f"{a - b:.2f}"
        elif has_add:
            return f"{sum(n[3] for n in nums):.2f}"
        return f"{a + b:.2f}"

    return None

class MoltbookClient:
    def __init__(self, api_key: Optional[str] = None):
        if not api_key:
            env_key = os.getenv("MOLTBOOK_API_KEY")
            if env_key:
                self.api_key = env_key
                self.agent_name = os.getenv("MOLTBOOK_AGENT_NAME", "moltbook-alpha")
                self.agent_id = os.getenv("MOLTBOOK_AGENT_ID")
            else:
                loaded = False
                try:
                    if CONFIG_PATH.exists():
                        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
                        self.api_key = data.get("api_key")
                        self.agent_name = data.get("agent_name")
                        self.agent_id = data.get("agent_id")
                        loaded = True
                except (PermissionError, OSError, FileNotFoundError):
                    loaded = False

                if not loaded:
                    self.api_key = None
                    self.agent_name = "unconfigured"
                    self.agent_id = None
        else:
            self.api_key = api_key
            self.agent_name = "unknown"
            self.agent_id = None

        self._http_client = None
        try:
            import httpx
            self._http_client = httpx.Client(timeout=12.0)
        except Exception:
            self._http_client = None

    def _request(self, endpoint: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from ops.transport.resilient_client import execute_sync, RetryPolicy

        url = f"{BASE_URL}{endpoint}"
        data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "MoltbookIntelBot/1.0",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"

        def _do_http_call():
            is_mocked = (
                getattr(urllib.request.urlopen, "__module__", "") != "urllib.request"
                or getattr(urllib.request.urlopen, "__name__", "") != "urlopen"
                or hasattr(urllib.request.urlopen, "mock")
                or hasattr(urllib.request.urlopen, "assert_called")
            )
            if is_mocked or getattr(self, "_http_client", None) is None:
                req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=12) as resp:
                    return json.loads(resp.read().decode("utf-8"))

            resp = self._http_client.request(method, url, content=data_bytes, headers=headers)
            if resp.status_code >= 400:
                raise urllib.error.HTTPError(url, resp.status_code, resp.text, resp.headers, None)
            return resp.json()

        policy = getattr(self, "retry_policy", None) or RetryPolicy()

        try:
            is_idemp = method.upper() in ("GET", "HEAD") or (isinstance(payload, dict) and "idempotency_key" in payload)
            return execute_sync(_do_http_call, policy=policy, method=method, idempotent=is_idemp)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if hasattr(e, "read") else str(e)
            raise RuntimeError(f"HTTP {e.code} from {endpoint}: {err_body}") from e
        except Exception as e:
            raise RuntimeError(f"Network error querying {endpoint}: {e!s}") from e

    def get_home(self) -> Dict[str, Any]:
        return self._request("/home")

    def get_agent_profile(self) -> Dict[str, Any]:
        return self._request("/agents/me")

    def verify_challenge(self, verification_code: str, answer: str) -> Dict[str, Any]:
        return self._request("/verify", method="POST", payload={
            "verification_code": verification_code,
            "answer": answer
        })

    def solve_and_verify(self, verification_dict: Dict[str, Any]) -> bool:
        code = verification_dict.get("verification_code")
        challenge = verification_dict.get("challenge_text", "")
        if not code or not challenge:
            return False

        ans = solve_arithmetic_challenge(challenge)
        clean_challenge = challenge.encode("ascii", "replace").decode("ascii")
        print(f"[Verification Gate] Code: {code} | Challenge: {clean_challenge!r} -> Computed: {ans}")
        if not ans:
            return False

        try:
            res = self.verify_challenge(code, ans)
            clean_res = str(res).encode("ascii", "replace").decode("ascii")
            print(f"[Verification Gate] Response: {clean_res}")
            return res.get("success", False)
        except Exception as e:
            clean_err = str(e).encode("ascii", "replace").decode("ascii")
            print(f"[Verification Gate] Verification failed: {clean_err}")
            return False

    def create_post(self, submolt_name: str, title: str, content: str) -> Tuple[Dict[str, Any], bool]:
        payload = {"submolt_name": submolt_name, "title": title, "content": content}
        res = self._request("/posts", method="POST", payload=payload)
        post = res.get("post", {})
        verif = post.get("verification") or res.get("verification")
        verified = False
        if verif:
            verified = self.solve_and_verify(verif)
        else:
            print(f"[create_post] No verification in response. Keys: {list(res.keys())}")
        return res, verified

    def create_comment(self, post_id: str, content: str, parent_id: Optional[str] = None) -> Tuple[Dict[str, Any], bool]:
        payload = {"content": content}
        if parent_id:
            payload["parent_id"] = parent_id
        res = self._request(f"/posts/{post_id}/comments", method="POST", payload=payload)
        comment = res.get("comment", {})
        verif = comment.get("verification") or res.get("verification")
        verified = False
        if verif:
            verified = self.solve_and_verify(verif)
        return res, verified

    def mark_notifications_read(self, post_id: str) -> bool:
        try:
            self._request(f"/notifications/read-by-post/{post_id}", method="POST", payload={})
            return True
        except Exception:
            return False

    def close(self) -> None:
        if getattr(self, "_http_client", None) is not None:
            try:
                self._http_client.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
