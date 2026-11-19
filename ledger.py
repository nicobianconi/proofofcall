"""
ledger.py
---------
A minimal blockchain-style ledger, saved in a JSON file.

Each block contains:
    index       position in the chain (0, 1, 2, ...)
    timestamp   when the block was added (UTC)
    type        what happened: GENESIS, REGISTER, COMMIT, REVEAL, EXPIRE, VERIFY
    data        the details of the event
    prev_hash   the hash of the previous block
    hash        the hash of this block (computed from all the fields above)

Because every block includes the hash of the previous one, changing ANY old
block breaks all the links after it. verify_chain() detects this immediately.
That is what makes the track record tamper-evident.

Note: this is a simulated ledger on a single server. In the roadmap, the
block hashes would be anchored on a public blockchain (e.g. Ethereum/Polygon)
so that not even the ProofOfCall team could rewrite the history.
"""

import copy
import hashlib
import json
import threading
from datetime import datetime, timezone

import config


# Streamlit serves all users from the same Python process.
# This lock makes sure two users never write to the file at the same moment.
_write_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Hashing a block
# ---------------------------------------------------------------------------

def compute_block_hash(block: dict) -> str:
    """SHA-256 of the block content (every field except 'hash' itself)."""
    content = {key: value for key, value in block.items() if key != "hash"}
    # sort_keys=True: the same block always produces the same text, so the same hash
    text = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_to_text(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Creating, loading and saving the chain
# ---------------------------------------------------------------------------

def create_genesis_block(moment: datetime = None) -> dict:
    """The first block of every chain. It has no previous block."""
    moment = moment or now_utc()
    block = {
        "index": 0,
        "timestamp": timestamp_to_text(moment),
        "type": "GENESIS",
        "data": {"message": "ProofOfCall ledger created"},
        "prev_hash": "0" * 64,
    }
    block["hash"] = compute_block_hash(block)
    return block


def load_chain(path=None) -> list:
    """Read the chain from disk. If the file doesn't exist yet, start a new one."""
    path = path or config.LEDGER_FILE

    if not path.exists():
        # First launch: copy the demo data if available, otherwise start empty
        if config.SEED_LEDGER_FILE.exists() and path == config.LEDGER_FILE:
            chain = json.loads(config.SEED_LEDGER_FILE.read_text(encoding="utf-8"))
        else:
            chain = [create_genesis_block()]
        save_chain(chain, path)
        return chain

    return json.loads(path.read_text(encoding="utf-8"))


def save_chain(chain: list, path=None) -> None:
    """Write the chain to disk (first to a temporary file, then swap: safer)."""
    path = path or config.LEDGER_FILE
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(chain, indent=2), encoding="utf-8")
    temporary_path.replace(path)


def append_block(block_type: str, data: dict, moment: datetime = None, path=None) -> dict:
    """
    Add a new block at the end of the chain and save it.
    This is the ONLY way to write to the ledger: old blocks are never edited.
    """
    moment = moment or now_utc()

    with _write_lock:
        chain = load_chain(path)
        previous_block = chain[-1]

        new_block = {
            "index": previous_block["index"] + 1,
            "timestamp": timestamp_to_text(moment),
            "type": block_type,
            "data": data,
            "prev_hash": previous_block["hash"],
        }
        new_block["hash"] = compute_block_hash(new_block)

        chain.append(new_block)
        save_chain(chain, path)

    return new_block


def reset_to_seed() -> None:
    """Replace the current ledger with the demo data (used by the sidebar button)."""
    with _write_lock:
        if config.SEED_LEDGER_FILE.exists():
            chain = json.loads(config.SEED_LEDGER_FILE.read_text(encoding="utf-8"))
        else:
            chain = [create_genesis_block()]
        save_chain(chain)


# ---------------------------------------------------------------------------
# Integrity check
# ---------------------------------------------------------------------------

def verify_chain(chain: list) -> tuple:
    """
    Check every block of the chain.

    Returns (True, "message") if everything is intact,
    or (False, "explanation") pointing to the first broken block.
    """
    for position, block in enumerate(chain):
        # 1) The stored hash must match the block content
        if compute_block_hash(block) != block["hash"]:
            return False, f"Block #{position} was modified: its content no longer matches its hash."

        # 2) Each block must point to the previous block's hash
        if position > 0 and block["prev_hash"] != chain[position - 1]["hash"]:
            return False, f"Block #{position} is not linked to block #{position - 1}: the chain is broken."

    return True, f"All {len(chain)} blocks are intact and correctly linked."


def simulate_tampering(chain: list) -> tuple:
    """
    Demo helper: on a COPY of the chain, try to turn a wrong call into a correct one,
    like a dishonest influencer (or a dishonest platform) would.
    Returns (tampered_block_index, verification_result). The real file is untouched.
    """
    fake_chain = copy.deepcopy(chain)

    for block in fake_chain:
        if block["type"] == "REVEAL" and block["data"].get("correct") is False:
            block["data"]["correct"] = True  # the "cheat"
            return block["index"], verify_chain(fake_chain)

    return None, (True, "No wrong call found to tamper with.")
