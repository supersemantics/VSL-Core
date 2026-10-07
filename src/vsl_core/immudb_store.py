"""Optional immudb replication of a durable local JSONL ledger."""

from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .exceptions import LedgerIntegrityError, VSLError
from .ledger import (
    GENESIS_HASH,
    JsonlLedgerStore,
    LedgerEntry,
    _CrossProcessFileLock,
    _compute_entry_hash,
)


@dataclass(frozen=True)
class ImmuDBConfig:
    """Connection settings; passwords are excluded from the representation."""

    username: str
    password: str = field(repr=False)
    host: str = "localhost"
    port: int = 3322
    database: str = "defaultdb"
    namespace: str = "vsl-ledger"
    timeout: float = 10.0
    public_key_file: str | None = None

    def __post_init__(self) -> None:
        for name in ("username", "password", "host", "database", "namespace"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be finite and positive")

    @classmethod
    def from_env(cls) -> "ImmuDBConfig":
        """Read IMMUDB_* settings without providing default credentials."""
        missing = [name for name in ("IMMUDB_USERNAME", "IMMUDB_PASSWORD") if not os.environ.get(name)]
        if missing:
            raise ValueError("Missing required environment variables: " + ", ".join(missing))
        return cls(
            username=os.environ["IMMUDB_USERNAME"],
            password=os.environ["IMMUDB_PASSWORD"],
            host=os.environ.get("IMMUDB_HOST", "localhost"),
            port=int(os.environ.get("IMMUDB_PORT", "3322")),
            database=os.environ.get("IMMUDB_DATABASE", "defaultdb"),
            namespace=os.environ.get("IMMUDB_NAMESPACE", "vsl-ledger"),
            timeout=float(os.environ.get("IMMUDB_TIMEOUT", "10")),
            public_key_file=os.environ.get("IMMUDB_PUBLIC_KEY_FILE") or None,
        )


class ImmuDBSyncError(VSLError):
    """Remote replication failed; the local entry is already committed."""

    def __init__(self, entry: LedgerEntry | None = None) -> None:
        self.entry = entry
        super().__init__(
            "immudb synchronization failed. Local entries are retained; "
            "retry store.sync(), not ledger.write()."
        )


class ImmuDBLedgerStore:
    """Write identical sealed entries to local JSONL and immudb.

    Reads and audits use the local file. sync() verifies the entire local
    chain and backfills missing remote entries, including after a restart.
    Writers must share the same local path for a namespace; independent
    machines must use distinct namespaces. There is no distributed transaction.
    A supplied client must be authenticated and dedicated to this store.
    """

    def __init__(
        self,
        path: Path | str,
        config: ImmuDBConfig,
        *,
        client: Any = None,
        fsync: bool = True,
    ) -> None:
        self.local = JsonlLedgerStore(path, fsync=fsync)
        self.config = config
        self._client = client
        self._owns_client = client is None
        self._lock = threading.RLock()
        self._prefix = config.namespace.encode("utf-8") + b"/entries/"
        self._state_path = self.local.path.with_name(self.local.path.name + ".immudb-state")

    def _connect(self) -> Any:
        if self._client is None:
            try:
                from immudb import ImmudbClient
                from immudb.client import PersistentRootService
            except ImportError as error:
                raise ImportError(
                    "immudb support requires the optional dependency: "
                    "pip install 'super-semantics-vsl[immudb]'"
                ) from error
            client = ImmudbClient(
                f"{self.config.host}:{self.config.port}",
                rs=PersistentRootService(str(self._state_path)),
                timeout=self.config.timeout,
                publicKeyFile=self.config.public_key_file,
            )
            try:
                client.login(
                    self.config.username,
                    self.config.password,
                    database=self.config.database.encode("utf-8"),
                )
            except Exception:
                client.shutdown()
                raise
            self._client = client
        return self._client

    def _remote_value(self, client: Any, key: bytes) -> bytes | None:
        try:
            response = client.verifiedGet(key)
        except Exception as error:
            try:
                import grpc
            except ImportError:
                raise error
            if isinstance(error, grpc.RpcError):
                if error.code() == grpc.StatusCode.NOT_FOUND:
                    return None
                if error.code() == grpc.StatusCode.UNKNOWN and error.details().endswith("key not found"):
                    return None
            raise
        if response is None:
            return None
        if not response.verified:
            raise LedgerIntegrityError("immudb read proof verification failed")
        return response.value

    def _sync_locked(self) -> int:
        entries = list(self.local.all_entries())
        previous_hash = GENESIS_HASH
        for sequence, entry in enumerate(entries):
            if (
                entry.sequence != sequence
                or entry.prev_hash != previous_hash
                or _compute_entry_hash(entry) != entry.entry_hash
            ):
                raise LedgerIntegrityError("Refusing to replicate a corrupted local ledger")
            previous_hash = entry.entry_hash
        client = self._connect()
        next_key = self._prefix + f"{len(entries):020d}".encode("ascii")
        if self._remote_value(client, next_key) is not None:
            raise LedgerIntegrityError("Remote ledger is ahead of the local file; restore the local file")
        written = 0
        for entry in entries:
            key = self._prefix + f"{entry.sequence:020d}".encode("ascii")
            value = json.dumps(entry.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
            existing = self._remote_value(client, key)
            if existing is not None:
                if existing != value:
                    raise LedgerIntegrityError("Remote ledger conflicts with the local chain")
                continue
            response = client.verifiedSet(key, value)
            if not response.verified:
                raise LedgerIntegrityError("immudb write proof verification failed")
            written += 1
        return written

    def sync(self) -> int:
        """Verify and backfill the remote ledger; return the number written."""
        with self._lock, self.local._lock, _CrossProcessFileLock(self.local.path):
            try:
                return self._sync_locked()
            except LedgerIntegrityError:
                raise
            except Exception as error:
                raise ImmuDBSyncError() from error

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        with self._lock, self.local._lock, _CrossProcessFileLock(self.local.path):
            last = self.local.last_entry()
            if last is not None and _compute_entry_hash(last) != last.entry_hash:
                raise LedgerIntegrityError("Refusing to append to a corrupted local ledger")
            sealed = self.local._append_locked(entry)
            try:
                self._sync_locked()
            except Exception as error:
                raise ImmuDBSyncError(sealed) from error
            return sealed

    def all_entries(self) -> Iterator[LedgerEntry]:
        yield from self.local.all_entries()

    def entries_for_identity(self, identity_key: str) -> Iterator[LedgerEntry]:
        yield from self.local.entries_for_identity(identity_key)

    def last_entry(self) -> LedgerEntry | None:
        return self.local.last_entry()

    def close(self) -> None:
        """Close an owned SDK connection, leaving injected clients untouched."""
        with self._lock:
            if self._owns_client and self._client is not None:
                self._client.shutdown()
                self._client = None

    def __enter__(self) -> "ImmuDBLedgerStore":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()