"""Preserve: an arriving file is copied into its customer's inbox, hashed and made read-only.

The copy lives at <data root>/customers/<customer>/inbox/<source_id>/<original name>, beside a
manifest. The source id is derived from the SHA-256 of the content, so the same bytes give one
id and one copy, and different bytes can never take an existing id. Every arrival, first or
repeated, is one line in the inbox ledger (JSON lines), which is only ever appended to.

Nothing in this package writes to an inbox file after it is preserved. The read-only bit is a
speed bump, not the guarantee; verify() re-hashes a copy against its manifest on demand.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

CHUNK = 1024 * 1024
COMPANY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
LEDGER = "ledger.jsonl"
MANIFEST = "manifest.json"


class IntakeError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Preserved:
    source_id: str
    sha256: str
    size: int
    original_name: str
    path: Path
    repeated: bool
    ledger_seq: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def customer_dir(root, company_id: str) -> Path:
    if not isinstance(company_id, str) or not COMPANY_ID.fullmatch(company_id):
        raise IntakeError("bad_company_id", f"company id {company_id!r} is not a plain identifier")
    return Path(root) / "customers" / company_id


def inbox_dir(root, company_id: str) -> Path:
    return customer_dir(root, company_id) / "inbox"


def source_id_for(sha256: str) -> str:
    return "src_" + sha256[:16]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_only(path: Path) -> bool:
    mode = os.stat(path).st_mode
    os.chmod(path, mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    return not os.access(path, os.W_OK)


def read_ledger(root, company_id: str) -> List[dict]:
    """Every arrival in order. A ledger whose lines are not 1..n in sequence is refused."""
    path = inbox_dir(root, company_id) / LEDGER
    if not path.exists():
        return []
    entries = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            entry = json.loads(line)
        except ValueError:
            raise IntakeError("ledger_corrupt", f"ledger line {number} is not JSON") from None
        if not isinstance(entry, dict) or entry.get("seq") != number:
            raise IntakeError("ledger_corrupt", f"ledger line {number} is out of sequence")
        entries.append(entry)
    return entries


def _append(root, company_id: str, entry: dict) -> int:
    seq = len(read_ledger(root, company_id)) + 1  # also checks nothing was rewritten
    line = json.dumps({"seq": seq, **entry}, ensure_ascii=False, sort_keys=True)
    with open(inbox_dir(root, company_id) / LEDGER, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    return seq


def manifest(root, company_id: str, source_id: str) -> dict:
    path = inbox_dir(root, company_id) / source_id / MANIFEST
    if not path.exists():
        raise IntakeError("unknown_source", f"{source_id} is not preserved for {company_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def inbox_file(root, company_id: str, source_id: str) -> Path:
    return inbox_dir(root, company_id) / source_id / manifest(root, company_id, source_id)["original_name"]


def verify(root, company_id: str, source_id: str) -> dict:
    """Re-hash a preserved copy and compare it with the hash recorded when it arrived."""
    recorded = manifest(root, company_id, source_id)
    path = inbox_dir(root, company_id) / source_id / recorded["original_name"]
    current = sha256_file(path) if path.exists() else None
    return {"source_id": source_id, "recorded": recorded["sha256"], "current": current,
            "matches": current == recorded["sha256"], "read_only": not os.access(path, os.W_OK)}


def preserve(root, company_id: str, path, *, now: Optional[str] = None) -> Preserved:
    """Copy one arriving file into the inbox, or link it to its first arrival if the bytes are known."""
    path = Path(path)
    if not path.is_file():
        raise IntakeError("not_a_file", f"{path} is not a file")
    if path.name == MANIFEST:
        raise IntakeError("reserved_name", f"a file named {MANIFEST} cannot be preserved")
    inbox = inbox_dir(root, company_id)
    if not customer_dir(root, company_id).is_dir():
        raise IntakeError("unknown_company", f"{company_id} has no customer folder; establish it first")
    inbox.mkdir(exist_ok=True)
    now = now or utc_now()

    # Hash while copying, so the hash is of exactly the bytes copied; then re-read the copy.
    temporary = inbox / f".incoming-{uuid.uuid4().hex}"
    digest, size = hashlib.sha256(), 0
    try:
        with open(path, "rb") as source, open(temporary, "xb") as target:
            for block in iter(lambda: source.read(CHUNK), b""):
                digest.update(block)
                size += len(block)
                target.write(block)
        sha256 = digest.hexdigest()
        if sha256_file(temporary) != sha256:
            raise IntakeError("copy_mismatch", f"the copy of {path.name} does not hash like its source")
        source_id = source_id_for(sha256)
        folder = inbox / source_id
        if (folder / MANIFEST).exists():
            return _repeat(root, company_id, folder, source_id, sha256, size, path.name, now)
        if folder.exists():
            raise IntakeError("incomplete_preservation",
                              f"{folder} exists without a manifest; a person must look at it")
        folder.mkdir()
        final = folder / path.name
        os.replace(temporary, final)
    finally:
        if temporary.exists():
            temporary.unlink()  # only ever our own unfinished copy, never a preserved file

    record = {"source_id": source_id, "sha256": sha256, "size": size, "company_id": company_id,
              "original_name": path.name, "preserved_at": now, "read_only": _read_only(final)}
    (folder / MANIFEST).write_text(json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True),
                                   encoding="utf-8", newline="\n")
    _read_only(folder / MANIFEST)
    seq = _append(root, company_id, {"event": "preserved", "source_id": source_id, "sha256": sha256,
                                     "size": size, "original_name": path.name, "at": now})
    return Preserved(source_id, sha256, size, path.name, final, False, seq)


def _repeat(root, company_id, folder, source_id, sha256, size, name, now) -> Preserved:
    recorded = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    if recorded["sha256"] != sha256:
        raise IntakeError("source_id_collision", f"{source_id} already holds other bytes")
    copy = folder / recorded["original_name"]
    if sha256_file(copy) != sha256:
        raise IntakeError("inbox_corrupt", f"the preserved copy of {source_id} no longer matches its hash")
    first = next((e["seq"] for e in read_ledger(root, company_id)
                  if e["event"] == "preserved" and e["source_id"] == source_id), None)
    if first is None:
        raise IntakeError("ledger_corrupt", f"the ledger has no first arrival for {source_id}")
    seq = _append(root, company_id, {"event": "repeated", "source_id": source_id, "sha256": sha256,
                                     "size": size, "original_name": name, "first_seq": first, "at": now})
    return Preserved(source_id, sha256, size, recorded["original_name"], copy, True, seq)
