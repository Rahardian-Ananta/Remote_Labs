# Spesifikasi RPC — RemoteLab v2.0

## Protokol: JSON-RPC 2.0

RemoteLab menggunakan JSON-RPC 2.0 ([spesifikasi resmi](https://www.jsonrpc.org/specification)) sebagai protokol komunikasi antara Scheduler dan Executor.

### Transport

- **Protokol:** HTTP/1.1 POST
- **Endpoint:** `http://<executor_host>:<port>/rpc`
- **Content-Type:** `application/json`
- **Respons Content-Type:** `application/json`

---

## Format Request

```json
{
  "jsonrpc": "2.0",
  "method": "<method_name>",
  "params": { ... },
  "id": "<string_or_int>"
}
```

| Field | Tipe | Wajib | Deskripsi |
|-------|------|-------|-----------|
| `jsonrpc` | string | ✅ | Harus `"2.0"` |
| `method` | string | ✅ | Nama metode |
| `params` | object | ✅ | Parameter metode |
| `id` | string/int | ✅ | ID permintaan (dipakai untuk korelasi respons) |

---

## Format Respons Sukses

```json
{
  "jsonrpc": "2.0",
  "result": { ... },
  "id": "<sama_dengan_request>"
}
```

---

## Format Respons Error

```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32600,
    "message": "Invalid Request",
    "data": "<opsional>"
  },
  "id": "<sama_atau_null>"
}
```

---

## Kode Error

| Kode | Konstanta | Deskripsi |
|------|-----------|-----------|
| -32700 | `PARSE_ERROR` | JSON tidak valid |
| -32600 | `INVALID_REQUEST` | Request tidak memenuhi spesifikasi JSON-RPC 2.0 |
| -32601 | `METHOD_NOT_FOUND` | Metode tidak dikenal |
| -32602 | `INVALID_PARAMS` | Parameter tidak valid |
| -32603 | `INTERNAL_ERROR` | Kesalahan internal executor |
| -32001 | `EXECUTOR_BUSY` | Executor penuh (running_jobs >= capacity) |
| -32002 | `JOB_NOT_FOUND` | Job ID tidak ditemukan di executor |
| -32003 | `KEY_NOT_FOUND` | Kunci tidak ditemukan di Chord DHT |

---

## Metode yang Tersedia

### `ping`

Memeriksa ketersediaan executor dan mendapatkan informasi beban.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "ping",
  "params": {},
  "id": "1"
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "executor_id": "exec1",
    "status": "healthy",
    "running_jobs": 1,
    "capacity": 4,
    "node_id": 1234567890
  },
  "id": "1"
}
```

---

### `executeCode`

Menjalankan kode sumber pada executor. Menggunakan semantik **at-most-once**: request duplikat dengan `job_id` yang sama mengembalikan hasil tersimpan.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "executeCode",
  "params": {
    "job_id": "job-uuid-123",
    "job_type": "python",
    "source_code": "print('Hello')",
    "timeout_sec": 30,
    "num_ranks": 1,
    "tags": ["demo", "test"]
  },
  "id": "2"
}
```

| Parameter | Tipe | Wajib | Deskripsi |
|-----------|------|-------|-----------|
| `job_id` | string | ✅ | ID unik job (UUID) |
| `job_type` | string | ✅ | `"python"` atau `"mpi"` |
| `source_code` | string | ✅ | Kode sumber yang dieksekusi |
| `timeout_sec` | float | ✅ | Timeout dalam detik (1-300) |
| `num_ranks` | int | ❌ | Jumlah rank MPI (1-4, default 1) |
| `tags` | array | ❌ | Tag untuk indexing DHT |

**Response (Sukses):**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "job_id": "job-uuid-123",
    "status": "SUCCESS",
    "exit_code": 0,
    "stdout": "Hello\n",
    "stderr": "",
    "preview": "Hello",
    "duration_sec": 0.05,
    "executor_id": "exec1"
  },
  "id": "2"
}
```

**Response (Error — Executor Penuh):**
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32001,
    "message": "Executor busy: 4/4 slots occupied"
  },
  "id": "2"
}
```

**Status Hasil:**
| Status | Deskripsi |
|--------|-----------|
| `SUCCESS` | Eksekusi berhasil, exit code 0 |
| `FAILED` | Exit code bukan 0 |
| `TIMEOUT` | Proses dihentikan karena timeout |
| `CANCELLED` | Job dibatalkan via `cancelJob` |

---

### `getStatus`

Mendapatkan status job yang sedang berjalan di executor.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "getStatus",
  "params": { "job_id": "job-uuid-123" },
  "id": "3"
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "job_id": "job-uuid-123",
    "status": "RUNNING",
    "duration_sec": 5.2
  },
  "id": "3"
}
```

**Error (Job Tidak Ditemukan):**
```json
{
  "jsonrpc": "2.0",
  "error": { "code": -32002, "message": "Job not found: job-uuid-123" },
  "id": "3"
}
```

---

### `cancelJob`

Membatalkan job yang sedang berjalan.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "cancelJob",
  "params": { "job_id": "job-uuid-123" },
  "id": "4"
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "result": { "cancelled": true },
  "id": "4"
}
```

---

### `chord.findSuccessor`

Melakukan lookup Chord DHT untuk kunci tertentu.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "chord.findSuccessor",
  "params": { "key_id": 1234567890 },
  "id": "5"
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "node_id": 3000000000,
    "url": "http://127.0.0.1:9003",
    "hops": 2,
    "path": ["http://127.0.0.1:9001", "http://127.0.0.1:9002", "http://127.0.0.1:9003"]
  },
  "id": "5"
}
```

---

### `chord.put`

Menyimpan nilai ke Chord DHT.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "chord.put",
  "params": {
    "key": "result_cache_key_abc",
    "value": {"stdout": "output...", "exit_code": 0},
    "tags": ["python", "math"]
  },
  "id": "6"
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "result": { "stored": true },
  "id": "6"
}
```

---

### `chord.get`

Mengambil nilai dari Chord DHT.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "chord.get",
  "params": { "key": "result_cache_key_abc" },
  "id": "7"
}
```

**Response (Ada):**
```json
{
  "jsonrpc": "2.0",
  "result": { "key": "result_cache_key_abc", "value": {...}, "found": true },
  "id": "7"
}
```

**Response (Tidak Ada):**
```json
{
  "jsonrpc": "2.0",
  "error": { "code": -32003, "message": "Key not found: result_cache_key_abc" },
  "id": "7"
}
```

---

### `chord.delete`

Menghapus nilai dari Chord DHT.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "chord.delete",
  "params": { "key": "result_cache_key_abc" },
  "id": "8"
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "result": { "deleted": true },
  "id": "8"
}
```

---

## Contoh Penggunaan dengan curl

```bash
# Ping executor
curl -s -X POST http://localhost:9001/rpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"ping","params":{},"id":1}' | python -m json.tool

# Eksekusi kode Python
curl -s -X POST http://localhost:9001/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "method":"executeCode",
    "params":{
      "job_id":"test-001",
      "job_type":"python",
      "source_code":"print(sum(range(100)))",
      "timeout_sec":5
    },
    "id":"2"
  }' | python -m json.tool
```

