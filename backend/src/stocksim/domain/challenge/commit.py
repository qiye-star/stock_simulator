"""seed 派生与承诺（03 §1.4）。纯函数：HMAC/SHA-256 只经 hashlib/hmac。

seed 与盐由服务层生成并传入（domain 不取随机数）。承诺原文格式对外是契约，改动须升版本前缀。
"""

from __future__ import annotations

import hashlib
import hmac

from .constants import COMMITMENT_PREFIX, SEED_DOMAIN_PREFIX


def derive_seed(key: bytes, date_iso: str, attempt: int) -> int:
    """seed = HMAC-SHA256(key, "stocksim-challenge-seed|v1|{date}|{attempt}") 前 8 字节大端，
    右移 1 位，取值 ∈ [0, 2^63)。"""
    if attempt < 0:
        raise ValueError("attempt must be >= 0")
    msg = f"{SEED_DOMAIN_PREFIX}|{date_iso}|{attempt}".encode()
    digest = hmac.new(key, msg, hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big") >> 1


def commitment_input(
    *, date_iso: str, events_ruleset: int, clock_rules: int, seed: int, salt_hex: str
) -> str:
    return (
        f"{COMMITMENT_PREFIX}|{date_iso}|ruleset={events_ruleset}|clock={clock_rules}"
        f"|seed={seed}|salt={salt_hex}"
    )


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_commitment(
    *, date_iso: str, events_ruleset: int, clock_rules: int, seed: int, salt_hex: str
) -> str:
    """seed_commitment = sha256(commitment_input) 的小写 hex。"""
    return sha256_hex(
        commitment_input(
            date_iso=date_iso,
            events_ruleset=events_ruleset,
            clock_rules=clock_rules,
            seed=seed,
            salt_hex=salt_hex,
        )
    )


def verify_commitment(input_text: str, digest: str) -> bool:
    return hmac.compare_digest(sha256_hex(input_text), digest)
