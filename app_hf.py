"""app.py - Entrypoint untuk Hugging Face Spaces (SDK Gradio) tanpa Docker.

100% Gratis & Tanpa Kartu Kredit di Hugging Face Spaces.
"""

import os
import gradio as gr
import uvicorn
from executor.main import app

# Pasang tampilan antarmuka status sederhana agar Hugging Face mendeteksinya sebagai aplikasi Gradio
with gr.Blocks(title="RemoteLab Executor Node") as demo:
    gr.Markdown("# 🚀 RemoteLab v2.0 — Executor Node (Worker)")
    gr.Markdown(f"**Status:** Aktif dan siap menerima job dari Scheduler.")
    gr.Markdown(f"**Executor ID:** `{os.getenv('EXECUTOR_ID', 'exec1')}`")
    gr.Markdown("Endpoint RPC: `/rpc` | Health Check: `/health`")

# Gabungkan Gradio dengan FastAPI aplikasi RemoteLab
app = gr.mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)

