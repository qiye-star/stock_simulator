"""seed 派生与承诺（03 §1.4）：金值向量由 hashlib/hmac 独立计算写死。"""

from stocksim.domain.challenge.commit import (
    commitment_input,
    derive_seed,
    make_commitment,
    sha256_hex,
    verify_commitment,
)

KEY = b"test-challenge-key"
SALT = "00112233445566778899aabbccddeeff"
# HMAC-SHA256(KEY, "stocksim-challenge-seed|v1|2026-11-01|0") 前 8 字节大端 >> 1
GOLD_SEED = 1076295361587894204
GOLD_INPUT = "stocksim-challenge|v1|2026-11-01|ruleset=1|clock=2|seed=123456789|salt=" + SALT
GOLD_DIGEST = "2e7b733407a7e24f2d825b4ddf6b2a8b0b4beedc3d3ebcd25bc9c23a3fd5e269"


def test_derive_seed_golden_and_range():
    assert derive_seed(KEY, "2026-11-01", 0) == GOLD_SEED
    for attempt in range(64):
        s = derive_seed(KEY, "2026-11-01", attempt)
        assert 0 <= s < 2**63


def test_derive_seed_deterministic_and_sensitive():
    base = derive_seed(KEY, "2026-11-01", 0)
    assert derive_seed(KEY, "2026-11-01", 0) == base
    assert derive_seed(KEY, "2026-11-01", 1) != base
    assert derive_seed(KEY, "2026-11-02", 0) != base
    assert derive_seed(b"other-key", "2026-11-01", 0) != base


def test_derive_seed_rejects_negative_attempt():
    import pytest

    with pytest.raises(ValueError):
        derive_seed(KEY, "2026-11-01", -1)


def test_commitment_input_format_and_golden():
    text = commitment_input(
        date_iso="2026-11-01", events_ruleset=1, clock_rules=2, seed=123456789, salt_hex=SALT
    )
    assert text == GOLD_INPUT


def test_make_commitment_golden():
    digest = make_commitment(
        date_iso="2026-11-01", events_ruleset=1, clock_rules=2, seed=123456789, salt_hex=SALT
    )
    assert digest == GOLD_DIGEST
    assert digest == sha256_hex(GOLD_INPUT)


def test_verify_commitment_positive_and_negative():
    assert verify_commitment(GOLD_INPUT, GOLD_DIGEST)
    tampered = GOLD_INPUT.replace("seed=123456789", "seed=123456788")
    assert not verify_commitment(tampered, GOLD_DIGEST)
    assert not verify_commitment(GOLD_INPUT, GOLD_DIGEST[:-1] + "0")
