"""
ledger.py
---------
A minimal blockchain-style ledger, stored in a SQLite database (ledger.db).

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

The code only ever INSERTS new rows: there is no function that updates or
deletes a block (append-only).

Note: this is a simulated ledger on a single server. In the roadmap, the
block hashes would be anchored on a public blockchain (e.g. Ethereum/Polygon)
so that not even the ProofOfCall team could rewrite the history.
"""

import copy
import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone

import config


# Streamlit serves all users from the same Python process.
# This lock makes sure two users never add a block at the same moment.
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


# ---------------------------------------------------------------------------
# The database
# ---------------------------------------------------------------------------

def _connect():
    """Open the database and create the 'blocks' table if it doesn't exist yet."""
    connection = sqlite3.connect(config.LEDGER_DB)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS blocks (
            block_index INTEGER PRIMARY KEY,
            timestamp   TEXT NOT NULL,
            type        TEXT NOT NULL,
            data        TEXT NOT NULL,
            prev_hash   TEXT NOT NULL,
            hash        TEXT NOT NULL UNIQUE
        )
    """)
    return connection


def _insert_blocks(connection, blocks: list) -> None:
    connection.executemany(
        "INSERT INTO blocks (block_index, timestamp, type, data, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?)",
        [(block["index"], block["timestamp"], block["type"],
          json.dumps(block["data"], sort_keys=True), block["prev_hash"], block["hash"])
         for block in blocks],
    )


def _starting_chain() -> list:
    """The demo history if available, otherwise just a genesis block."""
    if config.SEED_LEDGER_FILE.exists():
        return json.loads(config.SEED_LEDGER_FILE.read_text(encoding="utf-8"))
    return [create_genesis_block()]


def load_chain() -> list:
    """Read every block, in order. On the very first launch, fill the database with the demo data."""
    with _write_lock:
        connection = _connect()
        try:
            rows = connection.execute(
                "SELECT block_index, timestamp, type, data, prev_hash, hash FROM blocks ORDER BY block_index"
            ).fetchall()

            if not rows:
                chain = _starting_chain()
                _insert_blocks(connection, chain)
                connection.commit()
                return chain
        finally:
            connection.close()

    return [
        {"index": row[0], "timestamp": row[1], "type": row[2],
         "data": json.loads(row[3]), "prev_hash": row[4], "hash": row[5]}
        for row in rows
    ]


def append_block(block_type: str, data: dict, moment: datetime = None) -> dict:
    """
    Add a new block at the end of the chain.
    This is the ONLY way to write to the ledger: old blocks are never edited.
    """
    moment = moment or now_utc()
    chain = load_chain()  # also creates the database on the first launch

    with _write_lock:
        connection = _connect()
        try:
            last_row = connection.execute(
                "SELECT block_index, hash FROM blocks ORDER BY block_index DESC LIMIT 1"
            ).fetchone()
            previous_index, previous_hash = last_row if last_row else (chain[-1]["index"], chain[-1]["hash"])

            new_block = {
                "index": previous_index + 1,
                "timestamp": timestamp_to_text(moment),
                "type": block_type,
                "data": data,
                "prev_hash": previous_hash,
            }
            new_block["hash"] = compute_block_hash(new_block)

            _insert_blocks(connection, [new_block])
            connection.commit()
        finally:
            connection.close()

    return new_block


def replace_all_blocks(chain: list) -> None:
    """
    Admin only: replace the whole database with the given chain.
    Used by the password-protected "Reset demo data" button and by seed_data.py.
    """
    with _write_lock:
        connection = _connect()
        try:
            connection.execute("DELETE FROM blocks")
            _insert_blocks(connection, chain)
            connection.commit()
        finally:
            connection.close()


def reset_to_seed() -> None:
    """Restore the demo history (password-protected button in the sidebar)."""
    replace_all_blocks(_starting_chain())


def export_chain_to_json(path) -> None:
    """Save the whole chain as readable JSON (used to create seed_ledger.json)."""
    path.write_text(json.dumps(load_chain(), indent=2), encoding="utf-8")


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


def simulate_tampering_step_by_step(chain: list):
    """
    Demo helper for the visual "Try to cheat" section. Works on COPIES only.

    Finds the most recent REVEAL block of a WRONG call and simulates two attacks:

    Attack 1 - edit the result only:
        "correct": false -> true. The block's content no longer matches its hash.

    Attack 2 - edit the result AND recompute that block's hash (a smarter cheater):
        the block looks fine on its own, but the NEXT block still stores the old
        hash as "prev_hash", so the link between the two is broken.

    Returns a dict with everything the app needs to draw it, or None if there is
    no wrong call to tamper with.
    """
    target_position = None
    for position in range(len(chain) - 2, 0, -1):
        block = chain[position]
        if block["type"] == "REVEAL" and block["data"].get("correct") is False:
            target_position = position
            break

    # We need a block AFTER the target to show the broken link
    if target_position is None or target_position == len(chain) - 1:
        return None

    original_block = chain[target_position]

    # Attack 1: change the result, keep the old hash
    attack_1_block = copy.deepcopy(original_block)
    attack_1_block["data"]["correct"] = True
    attack_1_recomputed_hash = compute_block_hash(attack_1_block)

    # Attack 2: change the result AND recompute the hash
    attack_2_block = copy.deepcopy(attack_1_block)
    attack_2_block["hash"] = attack_1_recomputed_hash
    next_block = chain[target_position + 1]

    attack_1_chain = copy.deepcopy(chain)
    attack_1_chain[target_position] = attack_1_block
    attack_2_chain = copy.deepcopy(chain)
    attack_2_chain[target_position] = attack_2_block

    return {
        "position": target_position,
        "original_block": original_block,
        "tampered_block": attack_1_block,
        "stored_hash": original_block["hash"],
        "recomputed_hash": attack_1_recomputed_hash,
        "next_block": next_block,
        "attack_1_result": verify_chain(attack_1_chain),
        "attack_2_result": verify_chain(attack_2_chain),
    }


def simulate_tampering(chain: list) -> tuple:
    """
    Demo helper: on a COPY of the chain, try to turn a wrong call into a correct one,
    like a dishonest influencer (or a dishonest platform) would.
    Returns (tampered_block_index, verification_result). The real database is untouched.
    """
    fake_chain = copy.deepcopy(chain)

    for block in fake_chain:
        if block["type"] == "REVEAL" and block["data"].get("correct") is False:
            block["data"]["correct"] = True  # the "cheat"
            return block["index"], verify_chain(fake_chain)

    return None, (True, "No wrong call found to tamper with.")
