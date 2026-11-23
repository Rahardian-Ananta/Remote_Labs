# MPI di RemoteLab v2.0

## Apa itu MPI?

MPI (Message Passing Interface) adalah standar komunikasi untuk komputasi paralel terdistribusi.
RemoteLab mendukung eksekusi job MPI via `mpi4py` — binding Python untuk MPI.

---

## Implementasi

### File Utama

| File | Deskripsi |
|------|-----------|
| `executor/mpi_runner.py` | Runtime MPI: `find_mpi_executable()`, `is_mpi_available()`, `execute_mpi_job()` |
| `examples/mpi/parallel_sum.py` | Contoh: MPI_Bcast + MPI_Scatter + MPI_Reduce |
| `examples/mpi/pagerank.py` | Contoh: Distributed PageRank |
| `examples/mpi/ring_isend_irecv.py` | Contoh: Non-blocking Isend/Irecv ring |

---

## Cara Kerja

### 1. Deteksi Runtime

```python
# executor/mpi_runner.py
def is_mpi_available() -> bool:
    exe = find_mpi_executable()
    if not exe:
        return False
    # Coba import mpi4py.MPI
    result = subprocess.run([sys.executable, "-c", "from mpi4py import MPI"], ...)
    return result.returncode == 0
```

`find_mpi_executable()` mencari `mpiexec` di:
1. PATH sistem
2. Lokasi default MS-MPI (`C:\Program Files\Microsoft MPI\Bin\mpiexec.exe`)
3. Lokasi default OpenMPI (`/usr/bin/mpiexec`, `/usr/local/bin/mpiexec`)

### 2. Eksekusi Job MPI

```python
async def execute_mpi_job(job_id, source_code, num_ranks, timeout_sec, tags):
    # Tulis kode ke file sementara
    with tempfile.NamedTemporaryFile(...) as f:
        f.write(source_code.encode())
    
    # Jalankan via mpiexec
    cmd = [mpiexec_path, "-n", str(num_ranks), sys.executable, script_path]
    proc = await asyncio.create_subprocess_exec(*cmd, ...)
    
    # Tunggu dengan timeout
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
```

### 3. Perbedaan dengan Eksekusi Python Biasa

| Aspek | Python Biasa | MPI |
|-------|-------------|-----|
| Proses | 1 subprocess | `num_ranks` subprocess |
| Komunikasi | Tidak ada | `MPI.COMM_WORLD` |
| Koordinasi | Tidak ada | Rank 0 sebagai master |
| Command | `python -c <code>` | `mpiexec -n <ranks> python <file>` |
| Output | stdout langsung | Dikumpulkan dari semua rank |

---

## MPI_COMM_WORLD

`MPI.COMM_WORLD` adalah communicator default yang mencakup **semua proses** dalam satu run MPI.

```python
from mpi4py import MPI

comm = MPI.COMM_WORLD
rank = comm.Get_rank()   # ID proses ini (0, 1, 2, ...)
size = comm.Get_size()   # Total jumlah proses
```

### Operasi Kolektif

| Operasi | Deskripsi | Contoh |
|---------|-----------|--------|
| `comm.bcast(data, root=0)` | Broadcast dari rank 0 ke semua | Kirim parameter |
| `comm.scatter(data, root=0)` | Bagi array dari rank 0 | Distribusi data |
| `comm.gather(data, root=0)` | Kumpulkan dari semua ke rank 0 | Hasil per-chunk |
| `comm.reduce(data, op=MPI.SUM, root=0)` | Reduksi (sum, max, dll) | Hitung total |
| `comm.Isend(buf, dest)` | Non-blocking send | Ring communication |
| `comm.Irecv(buf, source)` | Non-blocking receive | Ring communication |

---

## Contoh Program MPI

### 1. parallel_sum.py — Penjumlahan Paralel

```python
from mpi4py import MPI
import numpy as np

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.Get_size()

# Rank 0 siapkan data
N = 1_000_000
if rank == 0:
    data = np.arange(N, dtype=np.float64)
    chunks = np.array_split(data, size)
else:
    chunks = None

# Distribusi ke semua rank
local_chunk = comm.scatter(chunks, root=0)

# Hitung lokal
local_sum = np.sum(local_chunk)

# Reduksi ke rank 0
total_sum = comm.reduce(local_sum, op=MPI.SUM, root=0)

if rank == 0:
    expected = N * (N - 1) / 2
    print(f"Parallel Sum: {total_sum:.0f}")
    print(f"Verification: {'PASS' if abs(total_sum - expected) < 1.0 else 'FAIL'}")
```

### 2. ring_isend_irecv.py — Ring Non-Blocking

```python
from mpi4py import MPI
import numpy as np

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.Get_size()

send_buf = np.array([rank], dtype=np.int32)
recv_buf = np.zeros(1, dtype=np.int32)

dest = (rank + 1) % size
src  = (rank - 1 + size) % size

req_send = comm.Isend(send_buf, dest=dest)
req_recv = comm.Irecv(recv_buf, source=src)
MPI.Request.Waitall([req_send, req_recv])

# Setiap rank menerima nilai dari neighbor kiri
assert recv_buf[0] == src
```

---

## Menjalankan MPI Secara Manual

```bash
# Pastikan mpi4py dan OpenMPI/MS-MPI terinstall
mpiexec -n 4 python examples/mpi/parallel_sum.py

mpiexec -n 3 python examples/mpi/ring_isend_irecv.py

mpiexec -n 2 python examples/mpi/pagerank.py
```

---

## Keterbatasan di Host Windows

MS-MPI memerlukan instalasi dengan hak administrator. Jika belum terinstal di host:

1. **Tes MPI di-skip** secara otomatis dengan pesan gracefully skipped jika runtime mpiexec tidak terdeteksi.
2. **Implementasi tetap lengkap**: Kode `executor/mpi_runner.py` dan template `examples/mpi/` siap mengeksekusi job begitu MS-MPI atau runtime MPI aktif.
3. **Validasi tetap berjalan**: `num_ranks > 4` ditolak dengan HTTP 422 bahkan tanpa runtime MPI.

---

## Instalasi MPI (untuk pengembangan)

### Linux / macOS
```bash
# Ubuntu/Debian
sudo apt-get install openmpi-bin libopenmpi-dev
pip install mpi4py

# macOS
brew install open-mpi
pip install mpi4py
```

### Windows
```powershell
# Download MS-MPI dari Microsoft
# https://learn.microsoft.com/en-us/message-passing-interface/microsoft-mpi
# Jalankan MSMpiSetup.exe dengan hak admin
winget install Microsoft.MPI  # atau dari direct download
pip install mpi4py
```

