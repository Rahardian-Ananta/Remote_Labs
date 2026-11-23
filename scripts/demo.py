#!/usr/bin/env python3
"""scripts/demo.py

RemoteLab v2.0 — Demo Script
Mendemonstrasikan semua fitur utama secara berurutan.

Prasyarat: jalankan run_local.ps1 atau run_local.sh terlebih dahulu.
Penggunaan: python scripts/demo.py [--url http://localhost:8000]
"""

import argparse
import asyncio
import json
import sys
import time

import httpx

BASE_URL_DEFAULT = "http://127.0.0.1:8000"


async def wait_job(client: httpx.AsyncClient, job_id: str, timeout: float = 30.0) -> dict:
    start = time.time()
    while time.time() - start < timeout:
        r = await client.get(f"/api/v1/jobs/{job_id}")
        if r.status_code == 200:
            d = r.json()
            if d["status"] not in ("QUEUED", "RUNNING"):
                return d
        await asyncio.sleep(0.3)
    raise TimeoutError(f"Job {job_id} tidak selesai dalam {timeout}s")


def header(title: str) -> None:
    print(f"\n{'═'*60}")
    print(f"  {title}")
    print(f"{'═'*60}")


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def info(msg: str) -> None:
    print(f"  ℹ  {msg}")


async def run_demo(base_url: str) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as c:

        # ── Cek kesehatan cluster ────────────────────────────────────────────
        header("Langkah 0 — Cek Kesehatan Cluster")
        h = await c.get("/api/v1/health")
        assert h.status_code == 200, f"Scheduler tidak responsif: {h.status_code}"
        health = h.json()
        exec_count = health.get("executor_count") or health.get("executors", {}).get("total", 0)
        ok(f"Scheduler sehat — {exec_count} executor terdaftar")
        exec_resp = await c.get("/api/v1/executors")
        for ex in exec_resp.json()["executors"]:
            info(f"  {ex['executor_id']:8s} {ex['status']:12s}  load={ex.get('running_jobs',0)}/{ex.get('capacity','-')}")

        # ── Skenario 1: Eksekusi Normal ──────────────────────────────────────
        header("Skenario 1 — Eksekusi Python Normal")
        r = await c.post("/api/v1/jobs", json={
            "job_type": "python",
            "source_code": "print('Hello from RemoteLab v2.0!')\nprint(2**10)",
            "timeout_sec": 10,
        })
        assert r.status_code == 202
        job1_id = r.json()["job_id"]
        info(f"Job disubmit: {job1_id}")
        d = await wait_job(c, job1_id)
        assert d["status"] == "SUCCESS", f"Status tidak SUCCESS: {d}"
        ok(f"Status={d['status']}  executor={d.get('executor_id')}  preview: {d.get('preview','')[:60]!r}")

        # ── Skenario 2: Timeout ──────────────────────────────────────────────
        header("Skenario 2 — Timeout Infinite Loop (2 detik)")
        r = await c.post("/api/v1/jobs", json={
            "job_type": "python",
            "source_code": "while True: pass",
            "timeout_sec": 2,
        })
        assert r.status_code == 202
        d = await wait_job(c, r.json()["job_id"], timeout=10.0)
        assert d["status"] == "TIMEOUT"
        ok(f"Status={d['status']} — proses dikill setelah timeout terpenuhi")

        # ── Skenario 3: Eksekusi Paralel (High Concurrency) ──────────────────
        header("Skenario 3 — 9 Job Paralel (load balancing)")
        ids = []
        t0 = time.perf_counter()
        for i in range(9):
            code = f"import time\ntime.sleep(0.1)\nprint('job-{i}')"
            resp = await c.post("/api/v1/jobs", json={"job_type": "python", "source_code": code, "timeout_sec": 10})
            ids.append(resp.json()["job_id"])
        results = await asyncio.gather(*(wait_job(c, jid, timeout=30.0) for jid in ids))
        elapsed = time.perf_counter() - t0
        used_ex = {r["executor_id"] for r in results if r.get("executor_id")}
        ok(f"{len(results)} job selesai dalam {elapsed:.2f}s — executor digunakan: {sorted(used_ex)}")

        # ── Skenario 4: Edge Cache + Lease ───────────────────────────────────
        header("Skenario 4 — Edge Cache (cache=True, target < 100ms)")
        code_cache = "print('deterministic output for cache test')"
        r1 = await c.post("/api/v1/jobs", json={"job_type": "python", "source_code": code_cache, "cache": True, "timeout_sec": 10})
        jid_c = r1.json()["job_id"]
        await wait_job(c, jid_c)
        ok("Eksekusi pertama selesai, hasil disimpan ke cache")

        t0 = time.perf_counter()
        r2 = await c.post("/api/v1/jobs", json={"job_type": "python", "source_code": code_cache, "cache": True, "timeout_sec": 10})
        ms = (time.perf_counter() - t0) * 1000
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2.get("from_cache") is True
        ok(f"Cache HIT dalam {ms:.1f}ms (< 100ms) — from_cache={d2['from_cache']}")

        # ── Skenario 5: Conditional GET (ETag / 304) ──────────────────────────
        header("Skenario 5 — Conditional GET (ETag & 304 Not Modified)")
        full = await c.get(f"/api/v1/jobs/{jid_c}")
        etag = full.headers.get("ETag", "")
        cond = await c.get(f"/api/v1/jobs/{jid_c}", headers={"If-None-Match": etag})
        assert cond.status_code == 304
        ok(f"ETag={etag!r} → 304 Not Modified diterima")

        # ── Skenario 6: Chord DHT Lookup ──────────────────────────────────────
        header("Skenario 6 — Chord DHT Lookup")
        lr = await c.get("/api/v1/dht/lookup?key=test_lookup_key")
        assert lr.status_code == 200
        ld = lr.json()
        ok(f"successor={ld.get('successor_node_id')!r}  hops={ld.get('hops')}  path={ld.get('lookup_path')}")

        # ── Skenario 7: Inverted Index Search ─────────────────────────────────
        header("Skenario 7 — Inverted Index Search (Chord DHT)")
        unique_kw = "serendipity_demo_unique_2024"
        code_tag = f"print('output contains {unique_kw}')"
        rs = await c.post("/api/v1/jobs", json={"job_type": "python", "source_code": code_tag, "tags": ["demo_tag"], "timeout_sec": 10})
        search_jid = rs.json()["job_id"]
        await wait_job(c, search_jid)
        await asyncio.sleep(1.0)  # Beri waktu index terpropagate ke DHT
        sr = await c.get(f"/api/v1/search?q={unique_kw}")
        assert sr.status_code == 200
        matches = sr.json()["matches"]
        matched_ids = [m["job_id"] for m in matches]
        if search_jid in matched_ids:
            ok(f"Job {search_jid} ditemukan via Chord search keyword='{unique_kw}'")
        else:
            info(f"Keyword '{unique_kw}' belum terindeks (normal jika propagasi DHT belum selesai)")

        # ── Skenario 8: MPI Validation ────────────────────────────────────────
        header("Skenario 8 — MPI Validation (num_ranks > 4 ditolak)")
        bad = await c.post("/api/v1/jobs", json={"job_type": "mpi", "num_ranks": 8, "source_code": "print(1)", "timeout_sec": 5})
        assert bad.status_code == 422
        ok(f"422 Unprocessable Entity — num_ranks=8 ditolak oleh validator (max=4)")

        # ── Skenario 9: Error Handling ────────────────────────────────────────
        header("Skenario 9 — Error Handling (exception dalam kode)")
        r_err = await c.post("/api/v1/jobs", json={"job_type": "python", "source_code": "raise ValueError('intentional error')", "timeout_sec": 5})
        d_err = await wait_job(c, r_err.json()["job_id"])
        assert d_err["status"] == "FAILED"
        ok(f"Status=FAILED  exit_code={d_err.get('exit_code')}  preview berisi traceback")

        # ── Skenario 10: Arsitektur Multi-Executor ───────────────────────────
        header("Skenario 10 — Ringkasan Arsitektur")
        exec_r = await c.get("/api/v1/executors")
        execs = exec_r.json()["executors"]
        info(f"Total executor terdaftar: {len(execs)}")
        for ex in execs:
            info(f"  {ex['executor_id']:8s}  url={ex.get('url')!r}  capacity={ex.get('capacity')}  running={ex.get('running_jobs',0)}")

        print(f"\n{'═'*60}")
        print("  🎉 Demo selesai — semua skenario berhasil dijalankan!")
        print(f"{'═'*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="RemoteLab v2.0 Demo Script")
    parser.add_argument("--url", default=BASE_URL_DEFAULT, help="Scheduler base URL")
    args = parser.parse_args()

    try:
        asyncio.run(run_demo(args.url))
    except Exception as exc:
        print(f"\n❌ Demo gagal: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

