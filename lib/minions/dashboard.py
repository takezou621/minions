"""Minimal local dashboard: minion run 一覧 + transcript ビューア (stdlib のみ)."""
import html
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .core import Run, RUNS_DIR, now_iso

PAGE = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>minion dashboard</title>
<style>
 body{font-family:-apple-system,sans-serif;background:#0f1116;color:#e6e6e6;margin:2rem}
 h1{font-size:1.3rem} table{border-collapse:collapse;width:100%}
 td,th{padding:.45rem .7rem;border-bottom:1px solid #2a2d37;text-align:left;font-size:.85rem}
 th{color:#8b93a7;font-weight:600} a{color:#7ab7ff;text-decoration:none}
 .ok{color:#5dd39e}.fail{color:#ff6b6b}.run{color:#aaa;font-size:.75rem;white-space:pre-wrap}
 .pill{display:inline-block;padding:.1rem .5rem;border-radius:99px;font-size:.72rem}
 .done{background:#12362b;color:#5dd39e}.failed{background:#3d1e22;color:#ff6b6b}
 .other{background:#2a2d37;color:#cdd3e0}
 pre{background:#161922;padding:1rem;border-radius:8px;overflow:auto;font-size:.75rem;max-height:70vh}
 .refresh{color:#8b93a7;font-size:.75rem}
</style>{REFRESH}</head><body>{BODY}</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, refresh=True):
        r = '<meta http-equiv="refresh" content="5">' if refresh else ""
        data = PAGE.replace("{REFRESH}", r).replace("{BODY}", body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            rows = []
            for r in Run.list_all()[:50]:
                cls = "done" if r.state in ("done", "done_local") else "failed" if r.state == "failed" else "other"
                last = r.events[-1]["detail"] if r.events else ""
                pr_cell = f"<a href='{r.pr_url}'>PR</a>" if r.pr_url else html.escape(last[:60])
                rows.append(
                    f"<tr><td><a href='/run/{r.run_id}'>{r.run_id}</a></td>"
                    f"<td><span class='pill {cls}'>{r.state}</span></td>"
                    f"<td>{html.escape(r.branch)}</td>"
                    f"<td>{pr_cell}</td>"
                    f"<td class='refresh'>{r.updated}</td></tr>")
            body = ("<h1>🧞 minion dashboard</h1><p class='refresh'>auto-refresh 5s · "
                    + now_iso() + "</p><table><tr><th>run</th><th>state</th>"
                    "<th>branch</th><th>pr / last event</th><th>updated</th></tr>"
                    + "".join(rows) + "</table>")
            self._send(body)
            return
        if self.path.startswith("/run/"):
            rid = urllib.parse.unquote(self.path[5:].split("/")[0])
            try:
                r = Run.load(rid)
            except Exception:
                self._send("<h1>not found</h1>", refresh=False)
                return
            tl = "".join(f"<div>{html.escape(e['t'])} {'✓' if e['ok'] else '✗'} "
                         f"<b>{html.escape(e['state'])}</b> {html.escape(e['detail'][:120])}</div>"
                         for e in r.events)
            tp = os.path.join(RUNS_DIR, rid, "transcript.log")
            log = open(tp, encoding="utf-8", errors="ignore").read()[-30000:] if os.path.exists(tp) else ""
            body = (f"<h1>🧞 {rid}</h1><p><b>task:</b> {html.escape(r.task)}</p>"
                    f"<p><b>branch:</b> {html.escape(r.branch)} · <b>state:</b> {r.state}"
                    + (f" · <a href='{r.pr_url}'>PR</a>" if r.pr_url else "") + "</p>"
                    f"<h2>timeline</h2><div class='run'>{tl}</div>"
                    f"<h2>transcript (tail)</h2><pre>{html.escape(log)}</pre>"
                    "<p><a href='/'>← back</a></p>")
            self._send(body)
            return
        self._send("<h1>minion</h1>", refresh=False)


def serve(port=8765):
    print(f"minion dashboard → http://localhost:{port}  (Ctrl+C で終了)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
