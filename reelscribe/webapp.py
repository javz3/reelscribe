"""Minimal local web UI: paste URLs, watch progress, see library stats.

One page, no build step, no external assets. Jobs run in a single background
worker thread (the pipeline is deliberately serial — numbering + one Whisper
model in memory).
"""

from __future__ import annotations

import queue
import threading
from typing import List

from .library import Library, extract_urls
from .pipeline import ReelResult, process_batch


class JobRunner:
    def __init__(self, lib: Library, cfg: dict):
        self.lib = lib
        self.cfg = cfg
        self.results: List[ReelResult] = []
        self.log: List[str] = []
        self.busy = False
        self._q: "queue.Queue[List[str]]" = queue.Queue()
        self._lock = threading.Lock()
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(self, urls: List[str]) -> int:
        with self._lock:
            new = [ReelResult(url=u) for u in urls
                   if u not in {r.url for r in self.results if r.status != "error"}]
            self.results.extend(new)
        if new:
            self._q.put([r.url for r in new])
        return len(new)

    def _sink(self, result: ReelResult, message: str) -> None:
        num = f"#{result.number}" if result.number else "·"
        with self._lock:
            self.log.append(f"[{num}] {result.stage}: {message}")
            self.log = self.log[-400:]

    def _worker(self) -> None:
        while True:
            urls = self._q.get()
            self.busy = True
            try:
                with self._lock:
                    batch = [r for r in self.results
                             if r.url in set(urls) and r.status == "pending"]
                process_batch(
                    [r.url for r in batch], self.lib,
                    whisper_model=self.cfg.get("whisper_model", "small.en"),
                    cookies_from_browser=self.cfg.get("cookies_from_browser"),
                    sink=self._sink, results=batch)
            finally:
                self.busy = self._q.qsize() > 0

    def state(self) -> dict:
        with self._lock:
            return {
                "busy": self.busy or not self._q.empty(),
                "results": [r.as_dict() for r in self.results],
                "log": list(self.log[-60:]),
                "stats": self.lib.stats(),
            }


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>reelscribe</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#fff;--fg:#1a1a1a;--muted:#667;--card:#f5f6f8;--acc:#0a7d4f;--err:#b3261e;}
@media (prefers-color-scheme: dark){:root{--bg:#111417;--fg:#e8eaed;--muted:#9aa0a6;--card:#1c2126;--acc:#4cc38a;--err:#f28b82;}}
body{font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);max-width:880px;margin:2rem auto;padding:0 1rem}
h1{font-size:1.4rem} textarea{width:100%;height:7rem;background:var(--card);color:var(--fg);border:1px solid var(--muted);border-radius:8px;padding:.6rem;font:13px/1.4 ui-monospace,monospace}
button{background:var(--acc);color:#fff;border:0;border-radius:8px;padding:.55rem 1.2rem;font-size:15px;cursor:pointer}
button:disabled{opacity:.5;cursor:wait}
.stats{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0}
.stat{background:var(--card);border-radius:8px;padding:.5rem .9rem}.stat b{font-size:1.2rem;display:block}
table{width:100%;border-collapse:collapse;margin-top:1rem;font-size:14px}
td,th{text-align:left;padding:.35rem .5rem;border-bottom:1px solid var(--card)}
.done{color:var(--acc)}.error{color:var(--err)}.skipped{color:var(--muted)}.running{font-weight:600}
pre{background:var(--card);border-radius:8px;padding:.7rem;font-size:12px;max-height:14rem;overflow:auto;white-space:pre-wrap}
small{color:var(--muted)}
</style></head><body>
<h1>🎞️ reelscribe</h1>
<p><small id="lib"></small></p>
<div class="stats" id="stats"></div>
<textarea id="urls" placeholder="Paste video URLs — one per line, or any text containing links (Facebook, YouTube, Instagram, TikTok, …)"></textarea>
<p><button id="go" onclick="submitUrls()">Ingest</button>
<span id="busy"></span></p>
<table id="results" hidden><thead><tr><th>#</th><th>Creator</th><th>Title</th><th>Status</th><th>Stage</th></tr></thead><tbody></tbody></table>
<h3>Log</h3><pre id="log">—</pre>
<script>
async function submitUrls(){
  const t=document.getElementById('urls');
  await fetch('/api/ingest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t.value})});
  t.value='';poll();
}
async function poll(){
  const r=await fetch('/api/state');const s=await r.json();
  document.getElementById('lib').textContent='library: '+s.stats.root;
  document.getElementById('busy').textContent=s.busy?'⏳ working…':'';
  document.getElementById('go').disabled=s.busy;
  const st=document.getElementById('stats');
  st.innerHTML=['videos','audio','transcripts','documents'].map(k=>`<div class="stat"><b>${s.stats[k]}</b>${k}</div>`).join('')
    +`<div class="stat"><b>${s.stats.next_number}</b>next #</div>`;
  const tb=document.querySelector('#results tbody');
  if(s.results.length){document.getElementById('results').hidden=false;
    tb.innerHTML=s.results.map(x=>`<tr class="${x.status}"><td>${x.number??'—'}</td><td>${x.uploader||''}</td><td>${(x.title||x.url).slice(0,60)}</td><td>${x.status}${x.error?' — '+x.error:''}</td><td>${x.stage}</td></tr>`).join('');}
  document.getElementById('log').textContent=s.log.length?s.log.join('\\n'):'—';
  setTimeout(poll, s.busy?1200:4000);
}
poll();
</script></body></html>"""


def create_app(lib: Library, cfg: dict):
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse

    app = FastAPI(title="reelscribe")
    runner = JobRunner(lib, cfg)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PAGE

    @app.post("/api/ingest")
    async def ingest(payload: dict):
        urls = extract_urls(payload.get("text", ""))
        added = runner.submit(urls)
        return JSONResponse({"found": len(urls), "queued": added})

    @app.get("/api/state")
    def state():
        return JSONResponse(runner.state())

    return app
