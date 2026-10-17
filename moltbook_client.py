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


def normalize_word(w: str) -> str:
    clean = re.sub(r"[^a-z]", "", w.lower())
    if clean in WORD_TO_NUMBER:
        return clean
    # Collapse repeated consecutive characters: e.g. 'twennty' -> 'twenty'
    collapsed = re.sub(r"(.)\1+", r"\1", clean)
    if collapsed in WORD_TO_NUMBER:
        return collapsed
    return clean


def parse_number_words(words: List[str]) -> Optional[float]:
    """Converts sequential English number words into a numeric value."""
    total = 0
    current = 0
    found_any = False

    for w in words:
        clean = normalize_word(w)
        if clean in WORD_TO_NUMBER:
            val = WORD_TO_NUMBER[clean]
            found_any = True
            if val == 100:
                current = (current if current else 1) * 100
            elif val == 1000:
                total += (current if current else 1) * 1000
                current = 0
            else:
                current += val
        elif clean.isdigit():
            found_any = True
            current += int(clean)

    if found_any:
        return float(total + current)
    return None


def merge_fragments(toks: List[str]) -> List[str]:
    """Merges adjacent hyphenated or broken token fragments (e.g. 'twenn' + 'ty' -> 'twenty')."""
    merged: List[str] = []
    i = 0
    while i < len(toks):
        if i + 1 < len(toks):
            pair = re.sub(r"(.)\1+", r"\1", toks[i] + toks[i + 1])
            if pair in WORD_TO_NUMBER:
                merged.append(pair)
                i += 2
                continue
        merged.append(toks[i])
        i += 1
    return merged


def solve_arithmetic_challenge(challenge_text: str) -> Optional[str]:
    """
    Parses and solves Moltbook anti-bot arithmetic challenges.
    Normalizes punctuation, identifies numbers and operations, and formats to 2 decimal places.
    """
    cleaned_text = re.sub(r"[^a-zA-Z0-9\s]", " ", challenge_text).lower()
    cleaned_text = re.sub(r"\s+", " ", cleaned_text)
    raw_tokens = [t.strip() for t in cleaned_text.split() if t.strip()]
    tokens = merge_fragments(raw_tokens)

    # Extract number phrases
    nums: List[float] = []
    current_num_words: List[str] = []

    for t in tokens:
        word_norm = normalize_word(t)
        if word_norm in WORD_TO_NUMBER or word_norm.isdigit():
            current_num_words.append(word_norm)
        else:
            if current_num_words:
                val = parse_number_words(current_num_words)
                if val is not None:
                    nums.append(val)
                current_num_words = []

    if current_num_words:
        val = parse_number_words(current_num_words)
        if val is not None:
            nums.append(val)

    if len(nums) < 2:
        return None

    a, b = nums[0], nums[1]

    # Operation detection: check space-separated text, collapsed text, and collapsed-deduplicated text
    collapsed_text = re.sub(r"\s+", "", cleaned_text)
    collapsed_dedup = re.sub(r"(.)\1+", r"\1", collapsed_text)

    def has_op(keywords: List[str]) -> bool:
        return any(k in cleaned_text or k in collapsed_text or k in collapsed_dedup for k in keywords)

    if has_op(["slow", "minus", "decreas", "lose", "drop", "differ", "subtract"]):
        result = a - b
    elif has_op(["gain", "plus", "increas", "add", "combin", "total"]):
        result = a + b
    elif has_op(["product", "time", "multipli"]):
        result = a * b
    elif has_op(["divid", "split", "quotient"]):
        result = a / b if b != 0 else 0
    else:
        result = a + b

    return f"{result:.2f}"


class MoltbookClient:
    def __init__(self, api_key: Optional[str] = None):
        if not api_key:
            if not CONFIG_PATH.exists():
                raise FileNotFoundError(f"Credentials not found at {CONFIG_PATH}")
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
            self.api_key = data.get("api_key")
            self.agent_name = data.get("agent_name")
            self.agent_id = data.get("agent_id")
        else:
            self.api_key = api_key
            self.agent_name = "unknown"
            self.agent_id = None

    def _request(self, endpoint: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{BASE_URL}{endpoint}"
        data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "MoltbookIntelBot/1.0",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"

        try:
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=12) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
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
        print(f"[Verification Gate] Code: {code} | Challenge: {challenge!r} -> Computed: {ans}")
        if not ans:
            return False

        res = self.verify_challenge(code, ans)
        print(f"[Verification Gate] Response: {res}")
        return res.get("success", False)

    def create_post(self, submolt_name: str, title: str, content: str) -> Tuple[Dict[str, Any], bool]:
        payload = {"submolt_name": submolt_name, "title": title, "content": content}
        res = self._request("/posts", method="POST", payload=payload)
        post = res.get("post", {})
        verif = post.get("verification")
        verified = False
        if verif:
            verified = self.solve_and_verify(verif)
        return res, verified

    def create_comment(self, post_id: str, content: str, parent_id: Optional[str] = None) -> Tuple[Dict[str, Any], bool]:
        payload = {"content": content}
        if parent_id:
            payload["parent_id"] = parent_id
        res = self._request(f"/posts/{post_id}/comments", method="POST", payload=payload)
        comment = res.get("comment", {})
        verif = comment.get("verification")
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
