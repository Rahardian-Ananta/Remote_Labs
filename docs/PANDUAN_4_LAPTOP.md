# Panduan Konfigurasi & Presentasi 4 Laptop / PC — RemoteLab v2.0

Panduan ini khusus disusun untuk kelompok dengan **4 anggota yang masing-masing membawa laptop/PC sendiri**. Ini adalah skenario pengujian paling ideal untuk mata kuliah **Sistem Terdistribusi**, di mana sistem berjalan di atas 4 perangkat fisik nyata yang terhubung melalui jaringan lokal (Wi-Fi).

---

## 1. Topologi Jaringan & Pembagian Peran 4 Laptop

Semua 4 laptop harus terhubung ke **satu jaringan Wi-Fi yang sama** (bisa menggunakan Wi-Fi kampus, Wi-Fi rumah, atau **Hotspot Tethering dari 1 HP**).

```
                      ┌────────────────────────────────────────┐
                      │      ROUTER WI-FI / HOTSPOT HP         │
                      └───────────────────┬────────────────────┘
                                          │
       ┌──────────────────┬───────────────┴───────────────┬──────────────────┐
       │                  │                               │                  │
┌──────▼──────┐    ┌──────▼──────┐                 ┌──────▼──────┐    ┌──────▼──────┐
│  LAPTOP 1   │    │  LAPTOP 2   │                 │  LAPTOP 3   │    │  LAPTOP 4   │
│  (Ketua)    │    │ (Anggota 1) │                 │ (Anggota 2) │    │ (Anggota 3) │
│             │    │             │                 │             │    │             │
│  SCHEDULER  │    │ EXECUTOR 1  │◄──(Chord P2P)──►│ EXECUTOR 2  │◄──►│ EXECUTOR 3  │
│  (Port 8000)│    │ (Port 9001) │                 │ (Port 9001) │    │ (Port 9001) │
└─────────────┘    └─────────────┘                 └─────────────┘    └─────────────┘
```

| Laptop | Anggota Kelompok | Peran Sistem | Fungsi Utama | Port |
|:---:|:---:|:---:|---|:---:|
| **Laptop 1** | Anggota 1 (Ketua) | **Scheduler (Master)** | Menerima request dari client, antrean FIFO, monitoring kesehatan, dan web dashboard UI. | `8000` |
| **Laptop 2** | Anggota 2 | **Executor 1 (Worker & Peer 1)** | Mengeksekusi kode Python/MPI sandbox dan node ring Chord DHT. | `9001` |
| **Laptop 3** | Anggota 3 | **Executor 2 (Worker & Peer 2)** | Mengeksekusi kode Python/MPI sandbox dan node ring Chord DHT. | `9001` |
| **Laptop 4** | Anggota 4 | **Executor 3 (Worker & Peer 3)** | Mengeksekusi kode Python/MPI sandbox dan node ring Chord DHT. | `9001` |

---

## 2. Persiapan Sebelum Memulai

### Langkah A: Sambungkan ke 1 Jaringan Wi-Fi / Hotspot
Pastikan ke-4 laptop terhubung ke hotspot yang sama.

### Langkah B: Ketahui IP Masing-Masing Laptop
Di setiap laptop, buka PowerShell dan ketik:
```powershell
ipconfig
```
Cari bagian **Wireless LAN adapter Wi-Fi** -> lihat **IPv4 Address**.  
*Catat di kertas / grup WhatsApp:*
- Laptop 1 (Master): misal `192.168.43.10`
- Laptop 2 (Exec 1): misal `192.168.43.11`
- Laptop 3 (Exec 2): misal `192.168.43.12`
- Laptop 4 (Exec 3): misal `192.168.43.13`

> [!IMPORTANT]
> **Firewall Windows:**  
> Saat pertama kali menjalankan skrip, Windows Firewall mungkin akan memunculkan pop-up *"Windows Defender Firewall has blocked some features of Python"*.  
> **Wajib klik "Allow access" (Centang Private networks)** agar laptop teman bisa saling berkomunikasi.

---

## 3. Langkah Menjalankan Sistem (Urutan Eksekusi)

### Langkah 1: Laptop 2, 3, dan 4 Menyalakan Node Executor Terlebih Dahulu
Di **Laptop 2**:
```powershell
.\scripts\run_cluster_executor.ps1
```
- Skrip akan otomatis mendeteksi IP laptop Anda. Tekan Enter.
- Pilih peran: ketik **`1`** (untuk `exec1`).
- IP Bootstrap: Tekan Enter.

Di **Laptop 3**:
```powershell
.\scripts\run_cluster_executor.ps1
```
- Tekan Enter untuk konfirmasi IP.
- Pilih peran: ketik **`2`** (untuk `exec2`).
- IP Bootstrap: Masukkan IP Laptop 2 (misal: `192.168.43.11`).

Di **Laptop 4**:
```powershell
.\scripts\run_cluster_executor.ps1
```
- Tekan Enter untuk konfirmasi IP.
- Pilih peran: ketik **`3`** (untuk `exec3`).
- IP Bootstrap: Masukkan IP Laptop 2 (misal: `192.168.43.11`).

*Ketiga laptop worker sekarang sudah saling terhubung dan membentuk topologi cincin Chord DHT!*

---

### Langkah 2: Laptop 1 Menyalakan Scheduler (Master)
Di **Laptop 1**:
```powershell
.\scripts\run_cluster_scheduler.ps1
```
- Masukkan IP Laptop 2 saat diminta (`192.168.43.11`).
- Masukkan IP Laptop 3 saat diminta (`192.168.43.12`).
- Masukkan IP Laptop 4 saat diminta (`192.168.43.13`).

Scheduler akan menyala di port `8000` dan otomatis menghubungkan ketiga executor.

---

### Langkah 3: Buka Web Dashboard di Browser
Di Laptop 1 (atau laptop siapapun di jaringan tersebut), buka browser:
```
http://192.168.43.10:8000
```
*(Ganti dengan IP Laptop 1)*

**Anda akan melihat:**
- 3 Node Executor aktif dengan status `HEALTHY` (`exec1`, `exec2`, `exec3`).
- Cincin Chord DHT memvisualisasikan 3 node dengan ID Chord masing-masing.

---

## 4. Skenario Live Demo di Hadapan Dosen (Sangat Mengesankan!)

Saat presentasi di depan dosen penguji, lakukan demonstrasi langsung antar-perangkat fisik berikut:

### Demo 1: Eksekusi Kode Nyata Tersebar di 3 Laptop Fisik
1. Di Laptop 1, jalankan skrip demo:
   ```powershell
   .\.venv\Scripts\python.exe scripts\demo.py --url http://127.0.0.1:8000
   ```
2. **Tunjukkan ke dosen:**
   > *"Bapak/Ibu Dosen, saat Laptop 1 mengirimkan batch komputasi, perhatikan layar terminal pada Laptop 2, 3, dan 4. Terlihat log eksekusi subproses berjalan secara simultan di prosesor laptop masing-masing anggota secara paralel!"*

---

### Demo 2: Simulasi Node Mati Nyata (*Physical Failover & Recovery*)
Ini adalah demo paling memukau dalam ujian sistem terdistribusi:
1. Di dashboard Laptop 1, tunjukkan ketiga node berwarna hijau (`HEALTHY`).
2. Minta **Laptop 2 mematikan Wi-Fi atau menekan `Ctrl+C` di terminalnya**.
3. **Lihat di layar Dashboard Laptop 1:**
   - Dalam hitungan beberapa detik, status `exec1` otomatis berubah menjadi merah (`UNAVAILABLE`).
4. Kirim job baru dari Laptop 1.
5. **Tunjukkan ke dosen:**
   > *"Meskipun Laptop 2 mati total secara fisik, sistem tidak mengalami crash! Job secara otomatis dialihkan oleh scheduler ke Laptop 3 dan Laptop 4 yang masih bertahan."*
6. Nyalakan kembali Wi-Fi / skrip di Laptop 2.
7. Status `exec1` di dashboard Laptop 1 otomatis kembali menjadi hijau (`HEALTHY`)!

---

### Demo 3: Chord P2P Inverted Index Terdistribusi
1. Lakukan pencarian melalui endpoint search atau Web Dashboard.
2. Tunjukkan bahwa hasil pencarian data tidak diambil dari database Scheduler, melainkan ditanyakan langsung ke cincin Chord P2P yang terdistribusi di memori Laptop 2, 3, dan 4.

---

## 5. Pertanyaan Umum (FAQ) untuk Penggunaan 4 Laptop

#### Q: "Bagaimana jika kami sedang tidak bersama / ingin latihan sendiri di rumah?"
> Cukup jalankan skrip lokal biasa:  
> `.\scripts\run_local.ps1`  
> Skrip ini akan menyimulasikan 4 node di 1 laptop menggunakan 4 port berbeda (`8000`, `9001`, `9002`, `9003`). Semua fitur tetap bekerja 100% sama!

#### Q: "Apakah port 9001 bisa sama di Laptop 2, 3, dan 4?"
> **Bisa sekali!** Karena masing-masing laptop memiliki IP address yang berbeda, port `9001` tidak akan bertabrakan (`192.168.43.11:9001`, `192.168.43.12:9001`, `192.168.43.13:9001`).

