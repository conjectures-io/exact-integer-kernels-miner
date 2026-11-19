"""The signed upload message: the five lines conjectures-validator verifies for every competition
(`conjectures-competition-submit-v1`), with this competition's slug. The slug is part of what is
signed, so a signature for one competition is refused by every other."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eik.config import COMPETITION_SLUG  # noqa: E402 - the one place the slug is defined

COMPETITION: Final = COMPETITION_SLUG
COMPETITION_SUBMIT_PREFIX: Final = "conjectures-competition-submit-v1"
SR25519: Final = 1  # bittensor_wallet's numbering, named so a default change cannot switch curves


def digest_of(source: bytes) -> str:
    """sha256 of entry.c, hex: what a submission is, and part of what is signed."""
    return hashlib.sha256(source).hexdigest()


def submit_message(*, competition: str, digest: str, hotkey: str, timestamp: int) -> str:
    """The exact text a hotkey signs to authorise one submission to one competition."""
    return "\n".join((
        COMPETITION_SUBMIT_PREFIX,
        f"competition: {competition}",
        f"digest: {digest}",
        f"hotkey: {hotkey}",
        f"timestamp: {timestamp}",
    ))


def sign(kp, message: str) -> str:
    """Hex sr25519 signature over the UTF-8 bytes of `message`."""
    return kp.sign(message.encode("utf-8")).hex()


def load_keypair(hotkey_file: str):
    """A Bittensor hotkey JSON file (its `secretSeed`), or a `//Name` dev URI for tests."""
    from bittensor_wallet import Keypair
    if hotkey_file.startswith("//"):
        return Keypair.create_from_uri(hotkey_file, crypto_type=SR25519)
    data = json.loads(Path(hotkey_file).read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{hotkey_file} is not a JSON object")
    seed = data.get("secretSeed") or data.get("privateKey")
    if not isinstance(seed, str) or not seed:
        raise ValueError(f"{hotkey_file} has no secretSeed")
    return Keypair.create_from_seed(seed, crypto_type=SR25519)
