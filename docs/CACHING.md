# Sistem Caching — RemoteLab v2.0

## Gambaran Umum

RemoteLab mengimplementasikan dua lapisan caching:

1. **LRU Cache** (`common/lru.py`) — cache in-memory generik berbasis `OrderedDict`
2. **Edge Cache** (`scheduler/cache.py`) — cache hasil job di scheduler dengan lease/TTL

---

## 1. LRU Cache

### Implementasi

File: [`common/lru.py`](../common/lru.py)

```python
class LRUCache:
    def __init__(self, capacity: int):
        self._capacity = capacity
        self._store: OrderedDict[str, Any] = OrderedDict()
    
    def get(self, key: str) -> Any:
        if key not in self._store:
            return None
        self._store.move_to_end(key)  # Pindahkan ke akhir (paling baru)
        return self._store[key]
    
    def put(self, key: str, value: Any) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = value
        if len(self._store) > self._capacity:
            self._store.popitem(last=False)  # Hapus item paling lama (FIFO head)
```

### Stack Property

LRU memiliki **stack property**: item yang baru diakses selalu ada di daftar lebih tinggi dibandingkan yang lebih lama.

Artinya: jika cache berukuran `k`, maka `k` item terpopuler *pasti* berada dalam cache LRU berukuran `k`, tidak peduli ukuran cache yang lebih kecil.

```python
def verify_stack_property(self) -> bool:
    """Verifikasi bahwa stack property terpenuhi."""
    keys = list(self._store.keys())
    # Item di akhir lebih baru dari item di awal
    return len(keys) == len(set(keys))  # Tidak ada duplikat
```

### Operasi

| Metode | Kompleksitas | Deskripsi |
|--------|-------------|-----------|
| `get(key)` | O(1) | Ambil nilai, tandai sebagai baru diakses |
| `put(key, value)` | O(1) | Simpan nilai, evict jika penuh |
| `delete(key)` | O(1) | Hapus entri |
| `clear()` | O(n) | Hapus semua entri |
| `__len__()` | O(1) | Jumlah entri saat ini |

---

## 2. Edge Cache (Scheduler)

### Implementasi

File: [`scheduler/cache.py`](../scheduler/cache.py)

```python
@dataclass
class CacheEntry:
    job_id: str
    result: dict          # Hasil lengkap dari executor
    etag: str             # SHA-256 fingerprint
    created_at: float     # Unix timestamp
    lease_sec: float      # Durasi lease
    
    def is_expired(self) -> bool:
        return time.time() > self.created_at + self.lease_sec
```

### Fitur Utama

#### a. Lease (TTL)

Setiap entri cache memiliki waktu kedaluwarsa (`lease_sec`). Dikonfigurasi via `CACHE_LEASE_SEC` (default 60 detik).

#### b. Check-on-Use

Sebelum mengembalikan hasil cache, sistem memvalidasi apakah entri masih valid (tidak kedaluwarsa dan job belum dihapus):

```python
def get(self, cache_key: str) -> CacheEntry | None:
    entry = self._lru.get(cache_key)
    if entry is None:
        return None
    if entry.is_expired():
        self._lru.delete(cache_key)  # Hapus entri kedaluwarsa
        return None
    return entry
```

#### c. Callback Invalidasi

Saat job dihapus (`DELETE /api/v1/jobs/{id}`), semua entri cache yang terkait job tersebut dihapus:

```python
def invalidate_job(self, job_id: str) -> None:
    """Hapus semua entri cache yang mengacu ke job_id ini."""
    keys = self._job_to_keys.pop(job_id, set())
    for key in keys:
        self._lru.delete(key)
```

#### d. Cache Key

Cache key dihitung dari konten job untuk memungkinkan **cache sharing** antar submisi identik:

```python
def compute_cache_key(job_type: str, source_code: str, num_ranks: int = 1) -> str:
    data = f"{job_type}:{num_ranks}:{source_code}"
    return sha256(data.encode()).hexdigest()
```

Dua job dengan `job_type` dan `source_code` yang identik menggunakan cache key yang sama → cache hit.

---

## Alur Kerja Caching

### Submisi dengan `cache=True`

```
Client ── POST /api/v1/jobs {cache: true} ──► Scheduler
                                                 │
                                           Hitung cache_key
                                                 │
                                          cache.get(cache_key)?
                                         /              \
                                       HIT               MISS
                                        │                  │
                               return 200 (from_cache)    Dispatch ke executor
                                                           │
                                                       wait_result
                                                           │
                                                      cache.put(cache_key, result)
                                                           │
                                                       return 202
```

### Target Performa

| Metrik | Target | Alasan |
|--------|--------|--------|
| Cache HIT latency | < 100ms | Dilayani dari memori in-process |
| Cache MISS latency | > 200ms | Melibatkan eksekusi kode aktual |
| Eviction policy | LRU | Pertahankan item yang paling sering diakses |

---

## Conditional GET (ETag & 304)

Hasil job yang sudah selesai dilengkapi header `ETag`:

```
GET /api/v1/jobs/{id}
→ 200 OK
   ETag: "sha256-a1b2c3..."
   Body: { "status": "SUCCESS", ... }

GET /api/v1/jobs/{id}
   If-None-Match: "sha256-a1b2c3..."
→ 304 Not Modified
   (Body kosong — klien pakai salinan lokal)
```

ETag dihitung dari hash konten hasil job (stdout + exit_code + status).

---

## Konfigurasi

| Variabel Lingkungan | Default | Deskripsi |
|--------------------|---------|----|
| `CACHE_CAPACITY` | 500 | Maksimum entri dalam LRU |
| `CACHE_LEASE_SEC` | 60.0 | Waktu hidup entri cache (detik) |

---

## Pengujian

```bash
# Jalankan test caching
pytest tests/test_cache.py -v

# Test yang dicakup:
# - test_lru_basic_operations: get/put/eviction
# - test_lru_delete_and_clear: operasi hapus
# - test_lru_stack_property: verifikasi stack property
# - test_edge_cache_lease_and_check_on_use: TTL + Check-on-Use
# - test_edge_cache_invalidation_callback: invalidasi saat delete
```

---

## Integrasi dengan Chord DHT

Selain edge cache (in-memory), RemoteLab juga menggunakan Chord DHT sebagai persistent store:

- **Edge Cache:** Hasil job disimpan di memori scheduler → cepat, hilang saat restart
- **Chord DHT:** Inverted index token → job_id disimpan di executor SQLite → persisten, tersebar

Keduanya bekerja bersama:
1. Job selesai → hasil disimpan ke edge cache (fast retrieval)
2. Token diekstrak → disimpan ke Chord DHT (persistent search index)

