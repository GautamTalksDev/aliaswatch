"""Tamper-evident record.

The value of AliasWatch is entirely that people believe the history. A public
JSON file in a git repo is trustworthy only as far as the repo owner is
trusted - and the repo owner is exactly the party with an incentive to
retroactively adjust a day.

So each day's results are hashed, chained to the previous day (Merkle-style
`prev_hash`), and the resulting head is signed with an Ed25519 key whose public
half is published in the repository. Anyone can verify offline that:

  * the archived responses produce the stated per-day digest,
  * each day points at the previous day's digest,
  * and the head was signed by the holder of the published key.

Rewriting any past day breaks every subsequent link. That does not make
tampering impossible - the key holder could re-sign a rewritten chain - but it
makes it *loud*: anyone holding an older signed head can prove the chain forked.
Publishing heads to a third party (a git tag, a social post, archive.org) turns
that into a practical guarantee.

Signing uses `cryptography` if available and falls back to a pure-Python
Ed25519 implementation, so verification never depends on an install succeeding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
LOG = ROOT / "results" / "log.jsonl"
PUBKEY = ROOT / "signing-key.pub"


def canonical(obj) -> str:
    """RFC 8785-style canonical JSON. Identical routine to the battery seal, so
    a reader only has to trust one serialisation rule."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_day(date_str: str) -> tuple[str, list[str]]:
    """Hash every result file for a date, in filename order."""
    d = RESULTS / date_str
    files = sorted(p for p in d.glob("*.json") if not p.name.endswith(".summary.json"))
    h = hashlib.sha256()
    names = []
    for p in files:
        # Hash raw bytes, not parsed JSON: what is verified is exactly the
        # bytes a reader downloads.
        h.update(p.name.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        names.append(p.name)
    return h.hexdigest(), names


# ---------------------------------------------------------------------------
# Ed25519 - pure-Python fallback (RFC 8032). Used only if `cryptography` is
# unavailable, so that verification works in any environment.
# ---------------------------------------------------------------------------

_q = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_d = -121665 * pow(121666, _q - 2, _q) % _q
_I = pow(2, (_q - 1) // 4, _q)


def _inv(x):
    return pow(x, _q - 2, _q)


def _xrecover(y):
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = pow(xx, (_q + 3) // 8, _q)
    if (x * x - xx) % _q != 0:
        x = (x * _I) % _q
    if x % 2 != 0:
        x = _q - x
    return x


_By = 4 * _inv(5) % _q
_B = (_xrecover(_By) % _q, _By)


def _edwards(P, Q):
    x1, y1 = P
    x2, y2 = Q
    k = _d * x1 * x2 * y1 * y2
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + k)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - k)
    return (x3 % _q, y3 % _q)


def _scalarmult(P, e):
    if e == 0:
        return (0, 1)
    Q = _scalarmult(P, e // 2)
    Q = _edwards(Q, Q)
    if e & 1:
        Q = _edwards(Q, P)
    return Q


def _encodeint(y):
    return y.to_bytes(32, "little")


def _encodepoint(P):
    x, y = P
    b = bytearray(_encodeint(y))
    b[31] |= (x & 1) << 7
    return bytes(b)


def _hint(m):
    return int.from_bytes(hashlib.sha512(m).digest(), "little")


def _pure_keypair(seed: bytes):
    h = hashlib.sha512(seed).digest()
    a = 2 ** 254 + (int.from_bytes(h[:32], "little") & ~(7 + (1 << 254) - (1 << 254)))
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    A = _scalarmult(_B, a)
    return a, h[32:64], _encodepoint(A)


def _pure_sign(seed: bytes, msg: bytes) -> bytes:
    a, prefix, pub = _pure_keypair(seed)
    r = _hint(prefix + msg) % _L
    R = _scalarmult(_B, r)
    Rs = _encodepoint(R)
    k = _hint(Rs + pub + msg) % _L
    S = (r + k * a) % _L
    return Rs + _encodeint(S)


def _pure_pub(seed: bytes) -> bytes:
    return _pure_keypair(seed)[2]


def _have_crypto():
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def sign(seed_hex: str, msg: bytes) -> str:
    seed = bytes.fromhex(seed_hex)
    if len(seed) != 32:
        raise SystemExit("signing seed must be 32 bytes of hex (64 hex chars)")
    if _have_crypto():
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        k = Ed25519PrivateKey.from_private_bytes(seed)
        return k.sign(msg).hex()
    return _pure_sign(seed, msg).hex()


def public_key(seed_hex: str) -> str:
    seed = bytes.fromhex(seed_hex)
    if _have_crypto():
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        k = Ed25519PrivateKey.from_private_bytes(seed)
        return k.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw).hex()
    return _pure_pub(seed).hex()


def verify(pub_hex: str, msg: bytes, sig_hex: str) -> bool:
    pub = bytes.fromhex(pub_hex)
    sig = bytes.fromhex(sig_hex)
    if _have_crypto():
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
        try:
            Ed25519PublicKey.from_public_bytes(pub).verify(sig, msg)
            return True
        except (InvalidSignature, ValueError):
            return False
    # Pure-Python verification.
    try:
        if len(sig) != 64 or len(pub) != 32:
            return False
        Rs, S = sig[:32], int.from_bytes(sig[32:], "little")
        if S >= _L:
            return False

        def decodepoint(s):
            y = int.from_bytes(s, "little") & ((1 << 255) - 1)
            x = _xrecover(y)
            if x & 1 != (s[31] >> 7) & 1:
                x = _q - x
            P = (x, y)
            if (-P[0] * P[0] + P[1] * P[1] - 1 - _d * P[0] * P[0] * P[1] * P[1]) % _q != 0:
                raise ValueError
            return P

        A = decodepoint(pub)
        R = decodepoint(Rs)
        k = _hint(Rs + pub + msg) % _L
        return _scalarmult(_B, S) == _edwards(R, _scalarmult(A, k))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------

def _refuse_local(date_str: str) -> None:
    """Signing is what turns a file into part of the public record, so this is
    the right chokepoint: mock and locally-run results must never be signed,
    however they got into results/."""
    d = RESULTS / date_str
    if not d.exists():
        raise SystemExit(f"no results for {date_str}")
    for p in d.glob("*.summary.json"):
        try:
            prov = json.loads(p.read_text()).get("provenance", "hosted")
        except (json.JSONDecodeError, OSError):
            continue
        if prov == "local":
            raise SystemExit(
                f"refusing to sign {date_str}: {p.name} has provenance "
                f"'local'. Mock and locally-run results are never part of the "
                f"published record. They belong in results-local/."
            )


def read_log() -> list[dict]:
    if not LOG.exists():
        return []
    return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]


def append_day(date_str: str, seed_hex: str) -> dict:
    _refuse_local(date_str)
    entries = read_log()
    if any(e["date"] == date_str for e in entries):
        raise SystemExit(
            f"{date_str} is already in the log. The log is append-only; a day "
            "is never rewritten. Publish a correction entry instead."
        )
    day_digest, files = digest_day(date_str)
    prev = entries[-1]["head"] if entries else "0" * 64

    body = {
        "date": date_str,
        "files": files,
        "day_digest": day_digest,
        "prev_head": prev,
        "index": len(entries),
    }
    head = hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()
    body["head"] = head
    body["signature"] = sign(seed_hex, bytes.fromhex(head))
    body["algorithm"] = "ed25519"

    with LOG.open("a") as f:
        f.write(canonical(body) + "\n")
    return body


def verify_chain(pub_hex: str | None = None) -> tuple[bool, list[str]]:
    entries = read_log()
    problems = []
    if pub_hex is None and PUBKEY.exists():
        pub_hex = PUBKEY.read_text().strip()

    prev = "0" * 64
    for i, e in enumerate(entries):
        if e["index"] != i:
            problems.append(f"{e['date']}: index {e['index']} out of order")
        if e["prev_head"] != prev:
            problems.append(f"{e['date']}: chain break - prev_head does not match {prev[:12]}…")

        body = {k: e[k] for k in ("date", "files", "day_digest", "prev_head", "index")}
        head = hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()
        if head != e["head"]:
            problems.append(f"{e['date']}: head does not match its own contents")

        if (RESULTS / e["date"]).exists():
            actual, _ = digest_day(e["date"])
            if actual != e["day_digest"]:
                problems.append(f"{e['date']}: archived files no longer hash to the logged digest")

        if pub_hex:
            if not verify(pub_hex, bytes.fromhex(e["head"]), e["signature"]):
                problems.append(f"{e['date']}: signature does not verify against the published key")

        prev = e["head"]

    return (not problems), problems


def main():
    ap = argparse.ArgumentParser(description="AliasWatch tamper-evident log")
    sub = ap.add_subparsers(dest="cmd", required=True)

    kg = sub.add_parser("keygen", help="print a fresh signing seed and its public key")
    kg.add_argument("--write-pub", action="store_true")

    ap_a = sub.add_parser("append", help="append and sign a day")
    ap_a.add_argument("date")

    sub.add_parser("verify", help="verify the whole chain offline")

    a = ap.parse_args()

    if a.cmd == "keygen":
        seed = os.urandom(32).hex()
        pub = public_key(seed)
        print("SEED (secret - put in a GitHub Actions secret, never commit):")
        print(f"  ALIASWATCH_SIGNING_SEED={seed}")
        print("PUBLIC KEY (commit this):")
        print(f"  {pub}")
        if a.write_pub:
            PUBKEY.write_text(pub + "\n")
            print(f"wrote {PUBKEY.name}")
        return

    if a.cmd == "append":
        seed = os.environ.get("ALIASWATCH_SIGNING_SEED", "")
        if not seed:
            raise SystemExit("ALIASWATCH_SIGNING_SEED is not set")
        e = append_day(a.date, seed)
        print(f"appended {e['date']} head={e['head'][:16]}… index={e['index']}")
        return

    ok, problems = verify_chain()
    n = len(read_log())
    if ok:
        print(f"chain OK - {n} days, unbroken and signed")
    else:
        print(f"CHAIN PROBLEMS ({n} days):")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
