# RemoteLab v2.0 — Distributed Parallel Code Execution Platform

RemoteLab v2.0 adalah platform eksekusi kode terdistribusi berbasis **Hybrid Master-Slave & Peer-to-Peer (P2P)** yang dibangun untuk tugas akhir mata kuliah **Sistem Terdistribusi** (PSTIF UTM). Sistem ini memungkinkan pengiriman job Python dan MPI ke kluster executor terdistribusi dengan penjadwalan cerdas, replikasi data, caching canggih, dan toleransi kesalahan.

---

## 🏛️ Enam Pilar Sistem Terdistribusi

| # | Pilar | Deskripsi | File Implementasi Utama | File Uji Terkait |
|---|-------|-----------|-------------------------|------------------|
| 1 | **Hybrid Master-Slave & P2P** | Scheduler mengelola antrian & dispatch (Master-Slave); Executor membentuk ring Chord DHT untuk indexing & pencarian terdesentralisasi (P2P). | `scheduler/dispatcher.py`<br>`scheduler/registry.py`<br>`executor/chord/node.py` | `tests/test_scenarios.py`<br>`tests/test_recovery.py` |
| 2 | **Naming** | 3 skema nama: Struktural (`exec1`, `exec2`), Flat Chord DHT (`m=32` bit hash ring), dan Attribute-Based (kapasitas, beban, MPI rank). | `common/hashing.py`<br>`scheduler/registry.py`<br>`executor/chord/node.py` | `tests/test_chord.py`<br>`tests/test_scenarios.py` (skenario 7 & 8) |
| 3 | **RESTful API** | REST API lengkap (HTTP/JSON) untuk submisi job, polling status, list, pencarian berbasis DHT, pembatalan, dan caching berbasis header `ETag` (304 Not Modified). | `scheduler/api.py`<br>`common/models.py` | `tests/test_api.py`<br>`tests/test_scenarios.py` (skenario 1 & 9) |
| 4 | **RPC (JSON-RPC 2.0)** | Komunikasi internal Scheduler ↔ Executor menggunakan JSON-RPC 2.0 dengan semantik *at-most-once* (deduplikasi SQLite) dan kode error standar. | `common/jsonrpc.py`<br>`executor/rpc_server.py`<br>`scheduler/rpc_client.py`<br>`executor/dedup.py` | `tests/test_rpc.py`<br>`tests/test_scenarios.py` (skenario 5) |
| 5 | **MPI (Message Passing Interface)** | Eksekusi komputasi paralel menggunakan `mpi4py` dan `mpiexec` (`MPI_COMM_WORLD`, rank 0 coordinator, scatter/gather/reduce, non-blocking Isend/Irecv). | `executor/mpi_runner.py`<br>`examples/mpi/` | `tests/test_mpi.py`<br>`tests/test_scenarios.py` (skenario 6) |
| 6 | **Caching** | Caching 2 tingkat: LRU Cache in-memory dengan *Stack Property* & Edge Cache di Scheduler dengan mekanisme Lease (TTL), *Check-on-Use*, dan callback invalidasi (target hit < 100ms). | `common/lru.py`<br>`scheduler/cache.py`<br>`common/hashing.py` | `tests/test_cache.py`<br>`tests/test_scenarios.py` (skenario 9) |

---

## ⚡ Quickstart & Setup Otomatis 1-Klik

> [!TIP]
> **Zero-Config untuk Semua Laptop:** Teman Anda **TIDAK PERLU menginstal Python manual secara global**! Jika laptop mereka belum punya Python atau terpasang versi yang tidak kompatibel (misal Python 3.14+), skrip setup otomatis akan mengunduh **Python 3.12 mandiri (portable & terisolasi)** khusus di dalam folder proyek ini tanpa mengubah sistem host!
> 
> 📖 **Lihat Panduan Lengkap:** [Panduan Setup & Presentasi (docs/PANDUAN_SETUP_DAN_PRESENTASI.md)](docs/PANDUAN_SETUP_DAN_PRESENTASI.md)

### Cara 1: Setup Otomatis (Sangat Disarankan)

**Di Windows:**
- **Cara Termudah (1-Klik Explorer):** Cukup **double-click** file `setup.bat` di File Explorer!
- **Atau via Terminal (PowerShell / CMD):**
```powershell
# 1. Jalankan setup otomatis (membuat .venv & install dependensi otomatis)
.\setup.bat
# (atau: .\setup.ps1)

# 2. Jalankan klaster lokal (1 Scheduler :8000 + 3 Executor :9001-:9003)
.\scripts\run_local.ps1
```

**Di Linux / macOS (Bash):**
```bash
# 1. Jalankan setup otomatis
chmod +x setup.sh && ./setup.sh

# 2. Jalankan klaster lokal
./scripts/run_local.sh
```

### Cara 2: Setup Manual

```bash
# 1. Masuk ke direktori dan siapkan virtual environment
cd remotelab
python -m venv .venv

# 2. Aktifkan venv dan instal seluruh dependensi
# Windows PowerShell:
.venv\Scripts\Activate.ps1; pip install -r requirements.txt
# Linux/macOS:
source .venv/bin/activate && pip install -r requirements.txt

# 3. Jalankan pengujian otomatis (pytest)
pytest -q

# 4. Jalankan kluster lokal (1 Scheduler :8000 + 3 Executor :9001-:9003)
# Windows PowerShell:
.\scripts\run_local.ps1
# Linux/macOS:
bash scripts/run_local.sh

# 5. Jalankan demonstrasi end-to-end (di terminal terpisah)
python scripts/demo.py
```

Setelah kluster berjalan, buka dashboard web di: **`http://localhost:8000`**

---

### 🌐 Cara 3: Menjalankan di 4 Laptop / PC Terpisah (Skenario Kelompok 4 Anggota)

Jika Anda memiliki **4 laptop untuk 4 anggota kelompok**, ini adalah skenario paling ideal untuk demonstrasi tugas akhir Sistem Terdistribusi. Sambungkan seluruh laptop ke **1 jaringan Wi-Fi / Hotspot yang sama**.

#### 📋 Pembagian Peran Anggota Kelompok

| Laptop | Anggota | Peran Sistem | Port | Perintah yang Dijalankan |
|:---:|:---:|:---:|:---:|---|
| **Laptop 1** | Ketua | **Scheduler (Master)** | `8000` | `.\scripts\run_cluster_scheduler.ps1` |
| **Laptop 2** | Anggota 1 | **Executor 1 (Worker & Peer Chord)** | `9001` | `.\scripts\run_cluster_executor.ps1` (pilih 1) |
| **Laptop 3** | Anggota 2 | **Executor 2 (Worker & Peer Chord)** | `9001` | `.\scripts\run_cluster_executor.ps1` (pilih 2) |
| **Laptop 4** | Anggota 3 | **Executor 3 (Worker & Peer Chord)** | `9001` | `.\scripts\run_cluster_executor.ps1` (pilih 3) |

#### 🚀 Urutan Eksekusi saat Presentasi:
1. **Langkah 1 (Laptop 2, 3, 4):** Jalankan `.\scripts\run_cluster_executor.ps1` di masing-masing laptop worker. Masukkan peran masing-masing (1/2/3). Ketiga node akan otomatis saling terhubung membentuk cincin P2P Chord DHT.
2. **Langkah 2 (Laptop 1):** Jalankan `.\scripts\run_cluster_scheduler.ps1` di laptop ketua. Masukkan IP laptop 2, 3, dan 4 saat diminta.
3. **Langkah 3 (Buka Dashboard):** Buka browser di Laptop 1 (atau laptop mana saja): `http://<IP_Laptop_1>:8000`. Dashboard akan langsung menampilkan 3 laptop worker aktif secara real-time!
4. **Langkah 4 (Jalankan Demo):** Di Laptop 1, jalankan `.\.venv\Scripts\python.exe scripts\demo.py --url http://127.0.0.1:8000`.

> 💡 **Trik Demo Dosen:** Matikan Wi-Fi pada Laptop 2 saat demo berlangsung. Dosen dapat melihat di dashboard Laptop 1 status Laptop 2 langsung berubah merah (`UNAVAILABLE`) dan job otomatis dialihkan ke Laptop 3 & 4 tanpa henti (*fault-tolerant*).
>
> 📖 **Panduan Detail 4 Laptop:** Baca panduan lengkap di [`docs/PANDUAN_4_LAPTOP.md`](docs/PANDUAN_4_LAPTOP.md).

---

## 📁 Struktur Repositori

```
remotelab/
├── common/                     # Utilitas & model data bersama
│   ├── config.py               # Konfigurasi via environment variable
│   ├── hashing.py              # SHA-256, Chord 32-bit hash, cache key
│   ├── jsonrpc.py              # Definisi & error codes JSON-RPC 2.0
│   ├── lru.py                  # Implementasi LRUCache & Stack Property
│   └── models.py               # Pydantic models (Job, Executor, Chord)
├── executor/                   # Kode node Executor (Slave & Chord Peer)
│   ├── chord/                  # Implementasi protokol Chord DHT
│   │   ├── index.py            # Ekstraksi token untuk inverted index
│   │   ├── maintenance.py      # Background tasks (stabilize, fix_fingers)
│   │   ├── node.py             # Chord Node, finger table, routing O(log N)
│   │   └── store.py            # Primary & replica key-value store
│   ├── dedup.py                # SQLite store deduplikasi at-most-once
│   ├── main.py                 # FastAPI server executor
│   ├── mpi_runner.py           # Eksekusi subprocess MPI via mpiexec
│   ├── rpc_server.py           # Handler JSON-RPC 2.0
│   └── sandbox.py              # Isolasi subprocess & batasan waktu/output
├── scheduler/                  # Kode node Scheduler (Master)
│   ├── api.py                  # RESTful API router (FastAPI)
│   ├── cache.py                # Scheduler Edge Cache (Lease + Check-on-Use)
│   ├── db.py                   # SQLite storage jobs & antrian
│   ├── dht_client.py           # Client Chord DHT & pencarian terbalik
│   ├── dispatcher.py           # FIFO Job Dispatcher & fault reconciliation
│   ├── health.py               # Health monitor loop (3-strike unavailable)
│   ├── main.py                 # FastAPI server scheduler & lifespans
│   ├── registry.py             # Attribute-based executor registry
│   ├── rpc_client.py           # Client JSON-RPC 2.0 (httpx async)
│   └── static/
│       └── index.html          # Web UI dashboard terintegrasi
├── examples/mpi/               # Contoh program paralel MPI
│   ├── pagerank.py             # Distributed PageRank (power iteration)
│   ├── parallel_sum.py         # Scatter-Reduce paralel sum
│   └── ring_isend_irecv.py     # Non-blocking ring token passing
├── scripts/                    # Skrip operasional
│   ├── benchmark.py            # Script pengukuran throughput, cache, hops
│   ├── demo.py                 # Skrip demonstrasi 10 skenario
│   ├── run_local.ps1           # Peluncur lokal PowerShell (Windows)
│   └── run_local.sh            # Peluncur lokal Bash (Linux/macOS)
├── tests/                      # Rangkaian pengujian otomatis pytest
│   ├── conftest.py             # Fixture live cluster & managed subprocess
│   ├── test_api.py             # Tes REST API & conditional GET
│   ├── test_cache.py           # Tes LRU & Edge Cache
│   ├── test_chord.py           # Tes Chord ring formation & lookup
│   ├── test_mpi.py             # Tes validasi rank & eksekusi MPI
│   ├── test_recovery.py        # Tes scheduler restart & reconciler
│   ├── test_rpc.py             # Tes protokol JSON-RPC 2.0 & dedup
│   ├── test_sandbox.py         # Tes timeout & isolasi subprocess
│   └── test_scenarios.py       # Tes integrasi skenario 1-10 end-to-end
├── docs/                       # Dokumentasi mendalam
│   ├── ARCHITECTURE.md         # Diagram & desain arsitektur
│   ├── ASSUMPTIONS.md          # Asumsi desain & batasan
│   ├── API.md                  # Dokumentasi endpoint REST API
│   ├── BENCHMARK.md            # Hasil benchmark terukur
│   ├── CACHING.md              # Spesifikasi sistem caching
│   ├── CHORD.md                # Spesifikasi & cara kerja Chord DHT
│   ├── MPI.md                  # Panduan komputasi paralel MPI
│   ├── PANDUAN_4_LAPTOP.md     # Panduan setup & live demo klaster 4 laptop/PC
│   ├── PANDUAN_SETUP_DAN_PRESENTASI.md # Panduan setup otomatis & cheat-sheet presentasi
│   ├── RPC_SPEC.md             # Spesifikasi protokol JSON-RPC 2.0
│   └── TEST_REPORT.md          # Laporan eksekusi pengujian pytest
├── Dockerfile.executor         # Container build untuk Executor (OpenMPI)
├── Dockerfile.scheduler        # Container build untuk Scheduler
├── docker-compose.yml          # Konfigurasi orkestrasi 1 Sched + 3 Exec
├── setup.bat                   # Launcher setup 1-klik untuk Windows Explorer
├── setup.ps1                   # Skrip setup otomatis PowerShell (Windows)
├── setup.sh                    # Skrip setup otomatis Bash (Linux/macOS)
├── pytest.ini                  # Konfigurasi pytest (asyncio_mode=auto)
└── requirements.txt            # Daftar pustaka Python yang dibutuhkan
```

---

## 🌐 Dokumentasi REST API & Contoh `curl`

### 1. Submit Job Python
```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "python",
    "source_code": "print(\"Hasil komputasi:\", sum(i*i for i in range(1000)))",
    "timeout_sec": 10,
    "tags": ["matematika", "demo"]
  }'
```
*Respons:*
```json
{"job_id": "c1f7a28e-...", "status": "QUEUED", "from_cache": false}
```

### 2. Cek Status Job & Hasil (Mendukung ETag / 304 Not Modified)
```bash
curl -i http://localhost:8000/api/v1/jobs/c1f7a28e-...
```
*Jika menggunakan header `If-None-Match` dengan nilai ETag sebelumnya:*
```bash
curl -i http://localhost:8000/api/v1/jobs/c1f7a28e-... \
  -H 'If-None-Match: "a4f8c9b2..."'
```
*Respons:* `HTTP/1.1 304 Not Modified`

### 3. Eksekusi dengan Caching Determinostik
```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "python",
    "source_code": "print(2**100)",
    "cache": true
  }'
```
*Submisi kedua dengan kode identik akan langsung menghasilkan respons 200 OK dalam < 100ms:*
```json
{"job_id": "...", "status": "SUCCESS", "from_cache": true, "preview": "1267650600228229401496703205376"}
```

### 4. Pencarian Terdistribusi via Chord DHT
```bash
curl "http://localhost:8000/api/v1/search?q=matematika"
```

### 5. Inspeksi Routing Chord DHT
```bash
curl "http://localhost:8000/api/v1/dht/lookup?key=job_result_key_123"
```

---

## 🖥️ Web UI Dashboard

Buka peramban ke **`http://localhost:8000`**. Dashboard menyediakan antarmuka interaktif:
1. **Code Editor**: Tulis kode Python atau pilih template MPI (Parallel Sum, Distributed PageRank, Ring Token Passing).
2. **Cluster Monitor**: Tabel status executor live (kapasitas, beban running jobs, status HEALTHY/UNAVAILABLE).
3. **Job Queue & History**: Pantau transisi status job secara real-time (QUEUED → RUNNING → SUCCESS/FAILED/TIMEOUT).
4. **Chord DHT Explorer**: Visualisasi ring Chord, lookup kunci, dan riwayat hop routing.
5. **Distributed Search**: Form pencarian job berdasarkan kata kunci atau tag.

---

## ⚠️ Asumsi & Keterbatasan yang Diketahui

1. **MPI Runtime di Host Windows**:
   - Pustaka `mpi4py` dan runner MPI `executor/mpi_runner.py` diimplementasikan secara penuh.
   - Pada host Windows pengembangan, `msmpi.dll` memerlukan instalasi Microsoft MPI dengan hak administrator (UAC).
   - Pengujian unit MPI (`tests/test_mpi.py`) mendeteksi ketersediaan runtime via `is_mpi_available()`. Jika tidak ada runtime sistem, pengujian eksekusi akan di-skip dengan dokumentasi yang jelas, sementara validasi parameter (seperti batasan `num_ranks <= 4`) tetap diuji dan lulus.
   - Pada lingkungan kontainer Linux (`Dockerfile.executor` / Docker Compose), OpenMPI dipasang secara otomatis sehingga seluruh pengujian MPI dapat berjalan penuh.
2. **Isolasi Proses**:
   - Di lingkungan Windows, proses executor diisolasi menggunakan flag OS `subprocess.CREATE_NEW_PROCESS_GROUP` dan pohon proses dimatikan menggunakan `psutil`.
   - Di lingkungan Linux, isolasi menggunakan session ID terpisah (`os.setsid`).
3. **Operasi 100% Offline**:
   - Seluruh sistem tidak memerlukan koneksi internet maupun API pihak ketiga berbayar saat dijalankan.
