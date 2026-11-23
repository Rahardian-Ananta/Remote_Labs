# Asumsi Desain — RemoteLab v2.0

Dokumen ini mencatat semua asumsi dan keputusan desain yang dibuat selama implementasi.

---

## 1. MPI Runtime (MS-MPI / OpenMPI)

**Asumsi:** MS-MPI tidak tersedia di host Windows saat pengembangan.

**Implikasi:**
- Implementasi MPI lengkap tersedia di `executor/mpi_runner.py` dan `examples/mpi/`.
- Fungsi `is_mpi_available()` memeriksa ketersediaan runtime MPI saat startup.
- Tes MPI (`test_mpi.py` scenario 6) di-skip secara otomatis dengan pesan dokumentasi.
- Pada Docker dengan image Linux + OpenMPI, semua tes MPI berjalan penuh.

**Alasan:** Menginstall MS-MPI di Windows memerlukan hak administrator (UAC). Lingkungan CI/CD menggunakan Linux dengan OpenMPI.

---

## 2. Chord DHT — Parameter m=32 bit

**Asumsi:** Ring identifier space menggunakan 32-bit bawah dari SHA-256.

**Implikasi:**
- `chord_hash(key)` mengambil 4 byte pertama dari SHA-256 → integer 0 s.d. 2³²-1.
- Finger table memiliki `m=32` entry; dalam praktik dengan N=3 node, sebagian besar jari menunjuk ke successor yang sama.
- Pencarian tetap O(log N) karena finger table mempercepat lookup melewati setengah ring.

**Alasan:** Spesifikasi asli Chord menggunakan SHA-1 160-bit. Untuk kemudahan implementasi dan pengujian dengan N kecil, 32 bit sudah cukup dan menghindari integer besar.

---

## 3. Replication Factor = 2

**Asumsi:** Setiap kunci Chord direplikasi ke dua node: primary (`succ(k)`) dan secondary (successor dari successor).

**Implikasi:**
- Chord `handle_put` menyimpan data ke store primer dan store replika.
- Saat node bergabung (`join`), transfer kunci memindahkan data ke node yang benar.
- Crash satu node tidak menghilangkan data selama node replika masih hidup.

**Alasan:** Replication factor 2 memberikan keseimbangan antara keandalan (toleransi 1 kegagalan) dan overhead jaringan.

---

## 4. Edge Cache — LRU + Lease

**Asumsi:** Cache menggunakan LRU eviction dengan TTL lease per entry.

**Implikasi:**
- `SchedulerEdgeCache` menyimpan hasil job di memori dengan batas kapasitas.
- Setiap entry memiliki waktu kedaluwarsa (lease); Check-on-Use memvalidasi entry yang kadaluarsa.
- Callback invalidasi menghapus entry terkait saat job di-delete.
- Target: latensi cache hit < 100ms (diukur dalam `benchmark.py`).

**Alasan:** Tidak menggunakan Redis/Memcached untuk menghindari dependensi eksternal dan mendukung operasi offline sepenuhnya.

---

## 5. At-Most-Once untuk executeCode

**Asumsi:** Setiap executor memiliki SQLite deduplication store (`executor/dedup.py`).

**Implikasi:**
- `ExecutorRPCServer.handle_execute_code()` memeriksa `job_id` di store sebelum eksekusi.
- Permintaan duplikat (job_id sama) mengembalikan hasil tersimpan tanpa eksekusi ulang.
- SQLite dipilih karena ringan, file-based, dan tidak memerlukan server terpisah.

**Alasan:** Spec Skenario 5 mensyaratkan at-most-once semantics untuk tolak deraian jaringan.

---

## 6. Windows Sandbox Fallback

**Asumsi:** `subprocess.CREATE_NEW_PROCESS_GROUP` digunakan di Windows alih-alih `os.setsid`.

**Implikasi:**
- `executor/sandbox.py` mendeteksi platform dan menggunakan flag yang sesuai.
- `psutil` digunakan untuk tree-kill semua child process saat timeout.
- Output di-cap pada 65536 karakter untuk mencegah memory exhaustion.

**Alasan:** `os.setsid()` tidak tersedia di Windows; `CREATE_NEW_PROCESS_GROUP` memberikan isolasi proses yang setara.

---

## 7. Scheduler Fault Handling

**Asumsi:** Job yang sedang berjalan saat scheduler restart di-reconcile via RPC `getStatus`.

**Implikasi:**
- `dispatcher.py` memanggil `reconcile_running_jobs_on_startup()` saat lifespan startup.
- Job dengan status RUNNING di DB tapi executor mengembalikan SUCCESS/FAILED/TIMEOUT akan diupdate.
- Job yang executor-nya tidak responsif ditandai EXECUTOR_LOST.

**Alasan:** Spec Section 7 mensyaratkan fault tolerance dan recovery otomatis.

---

## 8. Naming — Tiga Skema

| Skema | Implementasi | Keterangan |
|-------|--------------|------------|
| Struktural (hierarkis) | `scheduler/registry.py` — `executor_id` berbentuk `exec1`, `exec2` | ID unik struktural |
| Flat Chord DHT | `executor/chord/node.py` — SHA-256 hash → ring ID | Decentralized lookup |
| Attribute-Based | `scheduler/registry.py` — filter berdasarkan `tags`, `capacity` | Seleksi kapabilitas |

---

## 9. Batasan Diketahui

1. **MS-MPI**: Tidak tersedia di Windows host → tes MPI di-skip.
2. **Docker**: Tidak tersedia di host → `docker-compose.yml` divalidasi via `docker compose config`.
3. **Skala Ring**: Diuji dengan N=3 node; algoritma Chord bekerja untuk N berapapun.
4. **Persistensi Cache**: Cache hilang saat scheduler restart (in-memory). DHT menyimpan indeks ke disk via executor SQLite.
5. **MPI Multi-node**: Implementasi menggunakan `mpiexec` pada satu host; distribusi antar-host memerlukan shared filesystem.
