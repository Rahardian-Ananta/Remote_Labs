# Referensi REST API — RemoteLab v2.0

**Base URL:** `http://localhost:8000`  
**Content-Type:** `application/json`

---

## POST /api/v1/jobs

Mengirimkan job baru untuk dieksekusi.

**Request Body:**

```json
{
  "job_type": "python",
  "source_code": "print('Hello World')",
  "timeout_sec": 30,
  "num_ranks": 1,
  "tags": ["demo"],
  "cache": false
}
```

| Field | Tipe | Wajib | Constraint | Default |
|-------|------|-------|-----------|---------|
| `job_type` | string | ✅ | `"python"` atau `"mpi"` | — |
| `source_code` | string | ✅ | Tidak boleh kosong | — |
| `timeout_sec` | float | ❌ | 1–300 | 30 |
| `num_ranks` | int | ❌ | 1–4 | 1 |
| `tags` | array[string] | ❌ | — | [] |
| `cache` | bool | ❌ | — | false |

**Response 202 (Accepted — job baru):**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "QUEUED",
  "from_cache": false
}
```

**Response 200 (cache hit — hanya saat `cache=true`):**
```json
{
  "job_id": "550e8400-...",
  "status": "SUCCESS",
  "from_cache": true,
  "preview": "Hello World",
  "exit_code": 0,
  "executor_id": "exec1",
  "duration_sec": 0.04
}
```

**Response 422 (Validation Error):**
```json
{
  "detail": [{"loc": ["body","num_ranks"], "msg": "ensure this value is less than or equal to 4", "type": "value_error.number.not_le"}]
}
```

---

## GET /api/v1/jobs/{job_id}

Mendapatkan status dan hasil job.

**Response 200:**
```json
{
  "job_id": "550e8400-...",
  "status": "SUCCESS",
  "job_type": "python",
  "source_code": "print('Hello')",
  "exit_code": 0,
  "stdout": "Hello\n",
  "stderr": "",
  "preview": "Hello",
  "duration_sec": 0.05,
  "executor_id": "exec1",
  "created_at": "2024-01-01T00:00:00.000Z",
  "finished_at": "2024-01-01T00:00:00.500Z",
  "tags": []
}
```

**Header Respons:**
- `ETag: "sha256-<hash>"` — fingerprint hasil job
- Saat `If-None-Match: <etag>` dikirim dan cocok → **304 Not Modified**

**Response 404:** Job tidak ditemukan.

**Status Job:**
| Status | Deskripsi |
|--------|-----------|
| `QUEUED` | Menunggu di antrian dispatcher |
| `RUNNING` | Sedang dieksekusi di executor |
| `SUCCESS` | Selesai, exit code 0 |
| `FAILED` | Selesai, exit code bukan 0 |
| `TIMEOUT` | Proses dihentikan karena melebihi `timeout_sec` |
| `CANCELLED` | Dibatalkan oleh klien |
| `EXECUTOR_LOST` | Executor tidak responsif saat pemulihan |

---

## GET /api/v1/jobs

Mendapatkan daftar semua job.

**Query Params:**
- `status` — filter berdasarkan status (opsional)
- `limit` — maksimum jumlah hasil (default 50)
- `offset` — offset paginasi (default 0)

**Response 200:**
```json
{
  "jobs": [
    { "job_id": "...", "status": "SUCCESS", "job_type": "python", "created_at": "...", "executor_id": "exec1" }
  ],
  "total": 42
}
```

---

## DELETE /api/v1/jobs/{job_id}

Membatalkan job yang sedang QUEUED atau RUNNING.

**Response 200:**
```json
{ "cancelled": true, "job_id": "550e8400-..." }
```

**Response 404:** Job tidak ditemukan.
**Response 409:** Job sudah selesai (tidak bisa dibatalkan).

---

## GET /api/v1/search

Mencari job menggunakan Chord DHT inverted index.

**Query Params:**
- `q` — kata kunci pencarian (wajib)

**Response 200:**
```json
{
  "query": "keyword",
  "matches": [
    { "job_id": "...", "score": 1.0, "tags": ["demo"] }
  ]
}
```

---

## GET /api/v1/executors

Mendapatkan daftar semua executor yang terdaftar.

**Response 200:**
```json
{
  "executors": [
    {
      "executor_id": "exec1",
      "url": "http://127.0.0.1:9001",
      "status": "HEALTHY",
      "capacity": 4,
      "running_jobs": 1,
      "max_ranks": 4,
      "node_id": 1234567890
    }
  ]
}
```

**Status Executor:**
| Status | Deskripsi |
|--------|-----------|
| `HEALTHY` | Responsif dan siap menerima job |
| `UNAVAILABLE` | Tidak responsif ≥3 kali berturut-turut |
| `DEGRADED` | Responsif tapi kapasitas penuh |

---

## POST /api/v1/executors/register

Mendaftarkan executor baru ke scheduler (opsional, umumnya dikonfigurasi via env `EXECUTORS`).

**Request Body:**
```json
{
  "executor_id": "exec4",
  "url": "http://127.0.0.1:9004",
  "capacity": 4,
  "max_ranks": 4
}
```

**Response 201:**
```json
{ "registered": true, "executor_id": "exec4" }
```

---

## GET /api/v1/dht/lookup

Melakukan Chord DHT lookup secara manual.

**Query Params:**
- `key` — kunci string untuk di-hash dan di-lookup

**Response 200:**
```json
{
  "key": "my_key",
  "key_id": 987654321,
  "successor_node_id": 3000000000,
  "successor_url": "http://127.0.0.1:9003",
  "hops": 2,
  "lookup_path": ["http://127.0.0.1:9001", "http://127.0.0.1:9002", "http://127.0.0.1:9003"]
}
```

---

## GET /api/v1/health

Memeriksa kesehatan scheduler.

**Response 200:**
```json
{
  "status": "ok",
  "executor_count": 3,
  "healthy_executors": 3,
  "queued_jobs": 0,
  "running_jobs": 2
}
```

---

## Contoh curl

```bash
# Submit job Python
curl -s -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type":"python","source_code":"print(2**32)","timeout_sec":10}' | python -m json.tool

# Cek status
curl -s http://localhost:8000/api/v1/jobs/<job_id> | python -m json.tool

# Daftar executor
curl -s http://localhost:8000/api/v1/executors | python -m json.tool

# Cari job
curl -s "http://localhost:8000/api/v1/search?q=keyword" | python -m json.tool

# DHT lookup
curl -s "http://localhost:8000/api/v1/dht/lookup?key=test_key" | python -m json.tool

# Submit MPI job (perlu MPI runtime)
curl -s -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type":"mpi","num_ranks":4,"source_code":"from mpi4py import MPI\nprint(MPI.COMM_WORLD.Get_rank())","timeout_sec":15}' | python -m json.tool

# Caching
curl -s -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type":"python","source_code":"print(42)","cache":true}' | python -m json.tool
# Ulangi untuk mendapatkan cache hit (from_cache=true, status 200)
```

