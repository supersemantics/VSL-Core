---
title: immudb ledger storage
description: Configure dual writes to local JSONL and Codenotary immudb, with verified replication and recovery.
---

## Install and prepare

Install the optional SDK from the repository root:

```powershell
pip install -e ".[immudb]"
```

You need a running [Codenotary immudb server](https://docs.immudb.io/), an
existing database, and a user with read/write access to that database. This
store does not create databases or users. Local-only applications can keep
using `JsonlLedgerStore` without installing the SDK.

## Enter connection details

Your application can prompt for the connection details. Password input uses
`getpass` so it is not echoed to the terminal:

```python
from getpass import getpass

from vsl_core import ImmuDBConfig, ImmuDBLedgerStore, VerbaLedger

config = ImmuDBConfig(
    host=input("immudb host [localhost]: ").strip() or "localhost",
    port=int(input("immudb port [3322]: ").strip() or "3322"),
    database=input("Database [defaultdb]: ").strip() or "defaultdb",
    namespace=input("Ledger namespace [my-agent]: ").strip() or "my-agent",
    username=input("Username: ").strip(),
    password=getpass("Password: "),
)

with ImmuDBLedgerStore("ledger.jsonl", config) as store:
    store.sync()
    ledger = VerbaLedger(store)
    entry = ledger.write_monitor(
        identity_key="my-agent", drift_detected=False,
        extra_payload={"action": "request-reviewed"},
    )
    print(entry.entry_id, ledger.verify_integrity())
```

Construct `ImmuDBConfig` directly when your application already collects
these settings. Credentials are neither serialized into ledger entries nor
included in the configuration's representation.

For unattended use, set environment variables through your deployment's
secret configuration and call `ImmuDBConfig.from_env()`.

| Variable | Required | Default |
| --- | --- | --- |
| `IMMUDB_USERNAME` | Yes | None |
| `IMMUDB_PASSWORD` | Yes | None |
| `IMMUDB_HOST` | No | `localhost` |
| `IMMUDB_PORT` | No | `3322` |
| `IMMUDB_DATABASE` | No | `defaultdb` |
| `IMMUDB_NAMESPACE` | No | `vsl-ledger` |
| `IMMUDB_TIMEOUT` | No | `10` seconds |
| `IMMUDB_PUBLIC_KEY_FILE` | No | None |

```python
from vsl_core import ImmuDBConfig, ImmuDBLedgerStore, VerbaLedger

with ImmuDBLedgerStore("ledger.jsonl", ImmuDBConfig.from_env()) as store:
    store.sync()
    ledger = VerbaLedger(store)
    ledger.write_monitor(identity_key="my-agent", drift_detected=False)
```

`public_key_file` optionally supplies the server's signing public key to
the SDK. `timeout` bounds SDK requests. The SDK's default connection uses
unencrypted gRPC: use a trusted local network or a secure tunnel, not an
untrusted public connection. For custom transport, pass an already
authenticated SDK `client=` dedicated to the store. The caller owns and
closes an injected client.

## Persistence and recovery

Each append first seals and saves the entry locally, flushing and syncing
the file to disk by default. It then synchronizes local entries using
immudb `verifiedGet` and `verifiedSet`. Remote keys have the form
`<namespace>/entries/<20-digit-sequence>` and contain the complete JSON
entry, including its original ID, timestamp, sequence, and hashes.
Reading, auditing, and `verify_integrity()` use the local file; call
`store.sync()` to verify remote agreement.

> [!WARNING]
> Local and remote writes are not one atomic transaction. If replication
> fails, `ImmuDBSyncError` is raised with the committed entry in `.entry`.
> The entry is already saved locally. Retry `store.sync()`, not
> `ledger.write()`, to avoid recording the same event twice.

```python
from vsl_core import ImmuDBSyncError

try:
    ledger.write_monitor(identity_key="my-agent", drift_detected=False)
except ImmuDBSyncError as error:
    saved_entry = error.entry
    raise
```

After restoring connectivity, reopen the store over the same file and call
`sync()`. It returns the number of missing entries written. Repeated syncs
skip byte-identical remote values, including writes whose responses were
lost. Every append also retries synchronization of earlier entries.
Conflicting remote values and a corrupt local chain are rejected rather
than overwritten. A remote entry immediately beyond the local tip is
treated as possible truncation; restore the original local file before
continuing. Remote failures during append, including conflicts, are
reported as `ImmuDBSyncError` because a local commit has already occurred;
the underlying exception is available through `__cause__`.

Keep the local file and its sibling `.immudb-state` file. The latter stores
the SDK's trusted verification state across restarts. The sibling `.lock`
file coordinates writers sharing the local path. All writers for one
namespace must share that path and connection settings; separate machines
or independent local files must use distinct namespaces. This store does
not provide distributed writer coordination or remote-only restoration.

Synchronization validates and compares the whole local history, so its
cost grows with the ledger. It is synchronous and performs no background
retries. If used in an async application, run storage operations off the
event-loop thread. Neither this adapter nor immudb proofs encrypt payloads
or prevent a privileged database user from making later key revisions;
the adapter detects conflicting current values when it synchronizes.