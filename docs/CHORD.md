# Chord DHT — RemoteLab v2.0

## Apa itu Chord?

Chord adalah protokol Distributed Hash Table (DHT) yang memetakan kunci ke node dalam ring dengan jaminan lookup O(log N) hop.

**Referensi:** Stoica et al., "Chord: A Scalable Peer-to-peer Lookup Service for Internet Applications" (SIGCOMM 2001)

---

## Implementasi

| File | Deskripsi |
|------|-----------|
| `executor/chord/node.py` | `ChordNode` — finger table, join, stabilize, lookup |
| `executor/chord/store.py` | `ChordStore` — primary/replica store, inverted index |
| `executor/chord/index.py` | `extract_search_tokens()` — tokenisasi untuk index |
| `executor/chord/maintenance.py` | `ChordMaintenance` — loop periodik async |

---

## Konsep Dasar

### Ring Identifier Space

Semua node dan kunci dipetakan ke ring sirkuler dengan rentang `[0, 2^m)`.

Untuk RemoteLab, `m = 32`:
- Ring range: `[0, 4294967296)` (0 s.d. 2³²−1)
- Hash function: SHA-256 dari string, ambil 4 byte pertama → int 32-bit

```
chord_hash(key) = int.from_bytes(sha256(key.encode()).digest()[:4], 'big')
```

### Struktur Ring (N=3 node)

```
                    0
                   / \
          exec3  /     \  exec1
      (ID: 3B)  /       \  (ID: 1A)
               /         \
              ·           ·
               \         /
                \       /
          exec2  \     /
      (ID: 2B)    \   /
                   \ /
              4294967295
```

Setiap node bertanggung jawab atas segmen ring dari `predecessor.id + 1` hingga `node.id` (inklusif).

---

## Finger Table

Setiap node menyimpan `m` entri finger table:

```
finger[i].start = (node.id + 2^i) mod 2^m    (i = 0, 1, ..., m-1)
finger[i].node  = successor dari finger[i].start
```

Finger table memungkinkan lookup "melompat" setengah ring setiap langkah → O(log N) hop.

### Contoh Finger Table (m=4 untuk ilustrasi, node ID=0)

| i | start | successor |
|---|-------|-----------|
| 0 | 1 | node-A (ID=3) |
| 1 | 2 | node-A (ID=3) |
| 2 | 4 | node-B (ID=7) |
| 3 | 8 | node-C (ID=14) |

---

## Algoritma Lookup

```python
def find_successor(self, key_id: int) -> NodeRef:
    if in_interval(key_id, self.id, self.successor.id):
        return self.successor
    else:
        # Gunakan finger table untuk melompat lebih jauh
        closest = self.closest_preceding_node(key_id)
        return closest.rpc_find_successor(key_id)
```

### Trace Lookup (N=3, kunci → exec2)

```
Client
  │── findSuccessor(key_id=2500000000) ──►  exec1 (ID=1A)
                                               │
                                               │  finger[1] → exec2? Ya, lebih dekat
                                               │
  ◄── findSuccessor(key_id) ────────────────  exec2 (ID=2B)
                                               │  (is successor of key_id)
                                               │
  Hasil: exec2, hops=2
```

---

## Join Ring

Ketika executor baru bergabung:

1. Hubungi node bootstrap (`BOOTSTRAP_NODES` env var)
2. Panggil `find_successor(self.id)` pada node bootstrap → dapatkan successor
3. Set `self.successor = hasil`
4. Mulai loop `stabilize` → beritahu successor tentang diri sendiri

```python
async def join(self, bootstrap_url: str) -> None:
    # Minta successor dari bootstrap node
    succ = await rpc_call(bootstrap_url, "chord.findSuccessor", {"key_id": self.id})
    self.successor = NodeRef(node_id=succ["node_id"], url=succ["url"])
```

---

## Stabilisasi (Periodik)

```python
async def stabilize(self) -> None:
    # Periksa apakah ada node baru antara kita dan successor
    x = await rpc_call(self.successor.url, "chord.getPredecessor", {})
    if x and in_interval(x.node_id, self.id, self.successor.node_id):
        self.successor = x
    
    # Beritahu successor bahwa kita adalah predecessor-nya
    await rpc_call(self.successor.url, "chord.notify", {"node_id": self.id, "url": self.url})
```

---

## Replikasi Kunci

Setiap kunci disimpan di **2 node**:
- **Primary:** `succ(key_id)` — node yang bertanggung jawab
- **Replica:** `succ(succ(key_id))` — node successor berikutnya

Saat node crash, data replika tetap tersedia dari secondary node.

---

## Inverted Index untuk Search

Setelah job selesai:
1. `extract_search_tokens(tags, stdout)` → daftar token (kata-kata unik)
2. Per-token: `chord.put(key=f"idx:{token}", value={job_ids})`
3. Saat search: `chord.get(key=f"idx:{keyword}")` → daftar job yang mengandung keyword

```python
# executor/chord/index.py
def extract_search_tokens(tags: list[str], stdout: str) -> set[str]:
    tokens = set()
    # Dari tags
    for tag in tags:
        tokens.update(tag.lower().split())
    # Dari stdout (hanya kata alfanumerik ≥ 3 karakter)
    for word in re.findall(r'\b[a-z0-9]{3,}\b', stdout.lower()):
        tokens.add(word)
    return tokens
```

---

## Pemeliharaan Periodik

`ChordMaintenance` menjalankan tiga tugas secara async:

| Tugas | Interval | Fungsi |
|-------|----------|--------|
| `stabilize()` | `CHORD_MAINTENANCE_SEC` | Memperbarui successor/predecessor |
| `fix_fingers()` | `CHORD_MAINTENANCE_SEC` | Memperbarui satu entry finger table per siklus |
| `check_predecessor()` | `CHORD_MAINTENANCE_SEC * 2` | Deteksi predecessor yang crash |

---

## Transfer Kunci saat Join/Leave

Ketika node baru bergabung dan mendapat predecessor baru, kunci yang sekarang menjadi tanggung jawab node baru ditransfer dari successor:

```python
async def transfer_keys_to_predecessor(self, pred_id: int, pred_url: str) -> None:
    keys_to_transfer = [k for k in self.store.primary if in_interval(chord_hash(k), pred_id, self.id)]
    for k in keys_to_transfer:
        await rpc_call(pred_url, "chord.put", {"key": k, "value": self.store.primary[k]})
        del self.store.primary[k]
```

---

## Pengujian

```bash
# Jalankan test Chord
pytest tests/test_chord.py -v

# Test yang dicakup:
# - test_chord_ring_formation: 5 node, verifikasi successor/predecessor
# - test_chord_lookup_accuracy_and_hops: 16 node, cek hop ≤ log2(N)+1
# - test_chord_replication_factor_2: verifikasi data di primary dan replica
# - test_chord_crash_recovery: crash 1 node, lookup tetap berhasil via replika
```

