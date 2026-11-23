# Arsitektur RemoteLab v2.0

## Gambaran Umum

RemoteLab v2.0 adalah platform eksekusi kode terdistribusi yang mengimplementasikan enam pilar sistem terdistribusi:
Master-Slave + P2P, Naming, REST API, RPC, MPI, dan Caching.

---

## Diagram Arsitektur

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT (Browser / curl)                   │
│                    http://localhost:8000                          │
└───────────────────────────┬─────────────────────────────────────┘
                            │ REST API (HTTP/JSON)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SCHEDULER (Master Node)                        │
│   ┌──────────────┐  ┌────────────┐  ┌──────────────────────┐   │
│   │ REST API      │  │ Dispatcher │  │  Edge Cache (LRU)    │   │
│   │ /api/v1/jobs  │  │  FIFO Queue│  │  Lease + Check-on-  │   │
│   │ /api/v1/search│  │  Fault     │  │  Use, Stack Property │   │
│   │ /api/v1/dht   │  │  Recovery  │  └──────────────────────┘   │
│   └──────────────┘  └────────────┘                              │
│   ┌──────────────┐  ┌────────────┐  ┌──────────────────────┐   │
│   │ Registry      │  │Health Mon. │  │  DHT Client          │   │
│   │ Attr-based   │  │ Ping loop  │  │  Chord lookup/search  │   │
│   │ Least-loaded │  │ 3-strike   │  └──────────────────────┘   │
│   └──────────────┘  └────────────┘                              │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │             SQLite DB (jobs, queue, status)              │   │
│   └─────────────────────────────────────────────────────────┘   │
└──────────┬───────────────┬───────────────┬───────────────────────┘
           │ JSON-RPC 2.0  │ JSON-RPC 2.0  │ JSON-RPC 2.0
           ▼               ▼               ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  EXECUTOR 1  │  │  EXECUTOR 2  │  │  EXECUTOR 3  │
│  :9001       │  │  :9002       │  │  :9003       │
│              │  │              │  │              │
│ ┌──────────┐ │  │ ┌──────────┐ │  │ ┌──────────┐ │
│ │ Sandbox  │ │  │ │ Sandbox  │ │  │ │ Sandbox  │ │
│ │ Python   │ │  │ │ Python   │ │  │ │ Python   │ │
│ │ MPI exec │ │  │ │ MPI exec │ │  │ │ MPI exec │ │
│ └──────────┘ │  │ └──────────┘ │  │ └──────────┘ │
│ ┌──────────┐ │  │ ┌──────────┐ │  │ ┌──────────┐ │
│ │ Chord    │◄├──┼►│ Chord    │◄├──┼►│ Chord    │ │
│ │ DHT Node │ │  │ │ DHT Node │ │  │ │ DHT Node │ │
│ │ m=32 bit │ │  │ │ m=32 bit │ │  │ │ m=32 bit │ │
│ └──────────┘ │  │ └──────────┘ │  │ └──────────┘ │
│ ┌──────────┐ │  │ ┌──────────┐ │  │ ┌──────────┐ │
│ │ SQLite   │ │  │ │ SQLite   │ │  │ │ SQLite   │ │
│ │ dedup.db │ │  │ │ dedup.db │ │  │ │ dedup.db │ │
│ └──────────┘ │  │ └──────────┘ │  │ └──────────┘ │
└──────────────┘  └──────────────┘  └──────────────┘
       ▲                  ▲                  ▲
       └──────── P2P Chord Ring ─────────────┘
```

---

## Enam Pilar Implementasi

### Pilar 1: Hybrid Master-Slave & P2P

**Master-Slave:**
- Scheduler (master) menerima semua permintaan klien dan mendistribusikan job ke executor (slave).
- Dispatcher menggunakan antrian FIFO dengan kebijakan `least_loaded` (default) atau `round_robin`.
- Health Monitor memantau executor setiap `HEALTH_INTERVAL_SEC` detik; executor dengan 3 kegagalan berturut-turut ditandai UNAVAILABLE.

**P2P (Peer-to-Peer):**
- Executor membentuk Chord DHT ring secara peer-to-peer tanpa otoritas terpusat.
- Setiap executor menjalankan `ChordNode` dengan finger table m=32 bit.
- Pemeliharaan ring (stabilize, fix_fingers, check_predecessor) berjalan secara periodik.

### Pilar 2: Naming

| Skema | Komponen | Detail |
|-------|----------|--------|
| **Struktural** | `ExecutorRegistry` | ID hierarkis: `exec1`, `exec2`, `exec3` |
| **Flat (Chord DHT)** | `ChordNode` | SHA-256 hash → 32-bit ring ID; `find_successor` |
| **Attribute-Based** | `ExecutorRegistry.select()` | Filter: `capacity`, `max_ranks`, status=HEALTHY |

**Inverted Index:**  
Setiap executor mengekstrak token dari tag job dan stdout, lalu menyimpannya ke Chord DHT.
Pencarian (`/api/v1/search?q=keyword`) melakukan lookup per-token dan menggabungkan hasil.

### Pilar 3: REST API

Endpoint utama (lihat `docs/API.md` untuk detail):

| Method | Path | Deskripsi |
|--------|------|-----------|
| POST | `/api/v1/jobs` | Submit job baru |
| GET | `/api/v1/jobs/{id}` | Status job (ETag + 304) |
| GET | `/api/v1/jobs` | Daftar semua job |
| DELETE | `/api/v1/jobs/{id}` | Batalkan job |
| GET | `/api/v1/search` | Cari job via Chord |
| GET | `/api/v1/executors` | Daftar executor |
| POST | `/api/v1/executors/register` | Daftar executor baru |
| GET | `/api/v1/dht/lookup` | Chord lookup manual |
| GET | `/api/v1/health` | Health check |

### Pilar 4: RPC (JSON-RPC 2.0)

Komunikasi scheduler↔executor menggunakan JSON-RPC 2.0 via HTTP POST `/rpc`.

**Metode:**
- `ping` — cek ketersediaan executor
- `executeCode` — eksekusi kode dengan at-most-once semantics
- `getStatus` — cek status job yang sedang berjalan
- `cancelJob` — batalkan job
- `chord.findSuccessor` — Chord lookup
- `chord.put` / `chord.get` / `chord.delete` — operasi DHT

**At-Most-Once:** Setiap request `executeCode` membawa `job_id`. Executor menyimpan hasil ke SQLite dedup store; duplikat mengembalikan hasil tersimpan.

### Pilar 5: MPI

**Implementasi:** `executor/mpi_runner.py`
- `find_mpi_executable()` — mencari `mpiexec` di PATH atau lokasi default
- `is_mpi_available()` — validasi runtime
- `execute_mpi_job()` — menjalankan kode MPI via subprocess `mpiexec -n <ranks> python -c <code>`

**Contoh MPI (`examples/mpi/`):**
- `parallel_sum.py` — MPI_Bcast + MPI_Scatter + MPI_Reduce
- `pagerank.py` — Distributed PageRank
- `ring_isend_irecv.py` — Non-blocking Isend/Irecv ring

**Keterbatasan Host:** Jika MS-MPI tidak terinstal di Windows host, tes eksekusi MPI di-skip dengan graceful fallback sementara validasi parameter tetap berjalan penuh.

### Pilar 6: Caching

**LRU Cache (`common/lru.py`):**
- `LRUCache` berbasis `OrderedDict`
- Stack property: item paling baru di atas
- Metode: `get`, `put`, `delete`, `clear`, `verify_stack_property`

**Edge Cache (`scheduler/cache.py`):**
- `SchedulerEdgeCache` — cache in-memory scheduler
- Lease/TTL: setiap entry memiliki waktu kedaluwarsa
- Check-on-Use: validasi sebelum mengembalikan cached result
- Callback Invalidasi: hapus cache saat job di-delete
- Target: latensi hit < 100ms

---

## Alur Kerja Job

```
Client                Scheduler              Executor
  │                      │                      │
  │── POST /api/v1/jobs──►│                      │
  │                      │── cek cache ──────────│
  │                      │   (cache hit? →200)    │
  │◄── 202 Accepted ─────│                      │
  │                      │                      │
  │                      │── select executor ──►│
  │                      │   (least_loaded)      │
  │                      │                      │
  │                      │── JSON-RPC ──────────►│
  │                      │   executeCode          │
  │                      │                      │── run subprocess
  │                      │                      │   (sandbox.py)
  │                      │                      │── store dedup
  │                      │                      │── index Chord DHT
  │                      │◄── result ───────────│
  │                      │                      │
  │                      │── update DB ──────────│
  │                      │── update cache ───────│
  │                      │                      │
  │── GET /api/v1/jobs/{id}►│                    │
  │◄── 200 + ETag ───────│                      │
  │                      │                      │
  │── GET (If-None-Match)►│                     │
  │◄── 304 Not Modified──│                      │
```

---

## Struktur Direktori

```
remotelab/
├── common/          # Model, konfigurasi, utilitas bersama
│   ├── config.py    # SchedulerConfig, ExecutorConfig
│   ├── hashing.py   # chord_hash, compute_cache_key
│   ├── jsonrpc.py   # JSON-RPC 2.0 types & error codes
│   ├── lru.py       # LRUCache + stack property verification
│   └── models.py    # Pydantic models
├── executor/        # Node executor
│   ├── chord/       # Chord DHT implementation
│   │   ├── node.py  # ChordNode (finger table, stabilize, lookup)
│   │   ├── store.py # ChordStore (primary, replica, inverted index)
│   │   ├── index.py # Token extraction for inverted index
│   │   └── maintenance.py # Periodic maintenance tasks
│   ├── sandbox.py   # Subprocess execution + timeout
│   ├── dedup.py     # SQLite at-most-once deduplication
│   ├── mpi_runner.py # MPI execution via mpiexec
│   ├── rpc_server.py # JSON-RPC 2.0 server
│   └── main.py      # FastAPI app + lifespan
├── scheduler/       # Node scheduler (master)
│   ├── api.py       # REST API router
│   ├── db.py        # SQLite job store
│   ├── dispatcher.py # Job dispatcher + fault handling
│   ├── registry.py  # Executor registry + attribute selection
│   ├── health.py    # Health monitor
│   ├── cache.py     # Edge cache (LRU + lease)
│   ├── dht_client.py # DHT client (lookup, search)
│   ├── rpc_client.py # JSON-RPC client
│   ├── static/      # Frontend UI
│   └── main.py      # FastAPI app
├── examples/mpi/    # Contoh program MPI
├── scripts/         # Skrip operasional
├── tests/           # Test suite
└── docs/            # Dokumentasi
```

