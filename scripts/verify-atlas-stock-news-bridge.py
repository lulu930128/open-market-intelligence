"""Isolated persisted-evidence acceptance for Atlas REST -> OMI -> MCP omi.ask.

Reads explicit input SQLite files, copies Atlas using SQLite backup and copies
only selected OMI StockMaster rows. Never starts provider collectors or the OMI
lifespan. All processes and servers are closed before exit.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atlas-repo", type=Path, required=True)
    parser.add_argument("--atlas-db", type=Path, required=True)
    parser.add_argument("--omi-db", type=Path, required=True)
    args = parser.parse_args()
    run = ROOT / ".tmp" / "atlas-stock-news" / time.strftime("%Y%m%d-%H%M%S")
    run.mkdir(parents=True, exist_ok=False)
    atlas_copy = run / "atlas.sqlite"
    with sqlite3.connect(args.atlas_db.resolve().as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(atlas_copy) as destination:
            source.backup(destination)
    with sqlite3.connect(args.omi_db.resolve().as_uri() + "?mode=ro", uri=True) as source:
        source.row_factory = sqlite3.Row
        stocks = [dict(row) for row in source.execute(
            "SELECT * FROM stock_master WHERE stock_id IN ('2330','6488','1101') ORDER BY stock_id"
        )]
    assert len(stocks) == 3, "Required canonical StockMaster identities missing"

    ready_path = run / "atlas-ready.json"
    js = f'''
import {{ writeFileSync }} from "node:fs";
import {{ createAtlasRuntime }} from {json.dumps((args.atlas_repo.resolve() / 'src/atlasServer.js').as_uri())};
import {{ loadConfig }} from {json.dumps((args.atlas_repo.resolve() / 'src/config.js').as_uri())};
const config = loadConfig({{ ATLAS_DB_PATH: {json.dumps(str(atlas_copy))}, HOST: "127.0.0.1", PORT: "1",
  ATLAS_AUTO_COLLECT: "false", ATLAS_COLLECT_ON_START: "false", ATLAS_CONTENT_USAGE_CONTEXT: "personal_noncommercial" }});
config.port = 0;
let providerCalls = 0;
const forbidden = async () => {{ providerCalls++; throw new Error("Provider I/O forbidden in bridge acceptance"); }};
const runtime = createAtlasRuntime({{ config, http: {{ getText: forbidden, getJson: forbidden }} }});
runtime.store.db.exec("PRAGMA query_only = ON");
const address = await runtime.listen();
writeFileSync({json.dumps(str(ready_path))}, JSON.stringify({{ port: address.port, providerCalls, query_only: true }}));
process.stdin.resume();
process.stdin.on("end", async () => {{ await runtime.close(); process.exit(providerCalls ? 1 : 0); }});
'''
    node_log = (run / "atlas.stderr.log").open("w", encoding="utf-8")
    atlas = subprocess.Popen(["node", "--input-type=module", "-e", js], cwd=args.atlas_repo,
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=node_log)
    server = None
    thread = None
    sock = None
    try:
        deadline = time.monotonic() + 20
        while not ready_path.exists():
            if atlas.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Atlas isolated startup failed; inspect atlas.stderr.log")
            time.sleep(0.1)
        atlas_port = json.loads(ready_path.read_text())["port"]
        os.environ["DATABASE_URL"] = "sqlite:///" + (run / "omi.sqlite").as_posix()
        os.environ["OMI_ATLAS_NEWS_ENABLED"] = "true"
        os.environ["OMI_ATLAS_ENDPOINT_MODE"] = "static"
        os.environ["OMI_ATLAS_SHADOW_ENABLED"] = "false"
        os.environ["OMI_ATLAS_API_BASE_URL"] = f"http://127.0.0.1:{atlas_port}"
        from datetime import datetime
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import Session
        from app.db.models import Base, StockMaster
        engine = create_engine(os.environ["DATABASE_URL"], connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            for row in stocks:
                for key in ("first_seen_at", "last_seen_at", "created_at", "updated_at"):
                    row[key] = datetime.fromisoformat(row[key])
                db.add(StockMaster(**row))
            db.commit()
        @event.listens_for(engine, "connect")
        def read_only(connection, record):
            connection.execute("PRAGMA query_only = ON")
        engine.dispose()
        from app.main import app
        from app.db.session import get_db
        def isolated_db():
            with Session(engine, autoflush=False) as db:
                yield db
        app.dependency_overrides[get_db] = isolated_db
        import uvicorn
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        omi_port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 20
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("OMI isolated startup failed")
            time.sleep(0.1)
        import requests
        http = requests.Session()
        http.trust_env = False
        base = f"http://127.0.0.1:{omi_port}"
        summaries = []
        for symbol in ("2330", "6488", "1101"):
            stock = next(row for row in stocks if row["stock_id"] == symbol)
            upstream = http.get(f"http://127.0.0.1:{atlas_port}/api/v1/stocks/{stock['market']}/{symbol}/news?limit=3", timeout=10)
            upstream.raise_for_status()
            upstream = upstream.json()
            rest = http.get(f"{base}/api/stocks/{symbol}/news?limit=3", timeout=10)
            rest.raise_for_status()
            rest = rest.json()
            assert rest["items"] == upstream["data"], rest
            assert rest["coverage"] == upstream["coverage"]
            request = {"contract_version": "omi.decision.v4", "question": f"{symbol} 的個股新聞文件有哪些？",
                       "target": {"type": "tw_stock", "id": symbol, "market": "TW"},
                       "mode": "data_only", "output": "evidence_only", "realtime_policy": "cache_only",
                       "selection": {"include": ["target.identity", "news.company_documents"],
                                     "limits": {"news.company_documents": 3}, "max_response_bytes": 262144},
                       "tool_budget": {"max_external_fetches": 0, "max_calls": 1, "max_total_seconds": 15}}
            http_ask = http.post(f"{base}/api/ai/ask", json={**request, "allow_llm": False, "allow_write": False,
                                                        "allow_external_fetch": False}, timeout=25)
            http_ask.raise_for_status()
            expected = http_ask.json()
            stream = http.post(f"{base}/api/ai/ask/stream", json={**request, "allow_llm": False,
                               "allow_write": False, "allow_external_fetch": False}, timeout=25)
            stream.raise_for_status()
            stream.encoding = "utf-8"
            final = next(block for block in stream.text.split("\n\n") if block.startswith("event: final\n"))
            streamed = json.loads(next(line[6:] for line in final.splitlines() if line.startswith("data: ")))
            assert streamed["evidence"]["data"]["news.company_documents"]["items"] == rest["items"]
            messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "bridge-acceptance", "version": "1"}}},
                        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "omi.ask", "arguments": request}}]
            mcp_env = {**os.environ, "OMI_API_BASE_URL": base, "OMI_MCP_AI_TRUST_TOKEN": "",
                       "OMI_AI_TRUST_TOKEN": "", "OMI_MCP_TRUSTED_DEFAULT_EXTERNAL_FETCH": "false"}
            call = subprocess.run([sys.executable, str(ROOT / "agents/omi_mcp_server/server.py")],
                                  input="\n".join(json.dumps(message, ensure_ascii=False) for message in messages) + "\n",
                                  capture_output=True, encoding="utf-8", env=mcp_env, timeout=45, check=True)
            replies = [json.loads(line) for line in call.stdout.splitlines() if line.strip()]
            (run / f"mcp-{symbol}.json").write_text(json.dumps(replies, ensure_ascii=False, indent=2), encoding="utf-8")
            result = next(reply for reply in replies if reply.get("id") == 3)["result"]
            assert not result.get("isError"), result
            payload = result.get("structuredContent")
            if payload is None:
                payload = json.loads(next(item["text"] for item in result["content"] if item["type"] == "text"))
            news = payload["evidence"]["data"]["news.company_documents"]
            assert news["items"] == rest["items"], news
            assert news["items"] == expected["evidence"]["data"]["news.company_documents"]["items"]
            assert news["decision_usable"] is False
            assert news["freshness"] == upstream["freshness"]
            assert symbol == "1101" or len(news["items"]) > 0
            summaries.append({"symbol": symbol, "market": stock["market"], "status": news["status"],
                              "freshness": news["freshness"], "document_count": len(news["items"]),
                              "document_ids": [item["id"] for item in news["items"]], "rest_mcp_parity": True,
                              "sse_final_parity": True})
        assert http.get(f"{base}/api/stocks/2330/news?limit=51", timeout=10).status_code == 422
        # Shut down only the isolated Atlas process, then test the same OMI reader.
        atlas.stdin.close()
        assert atlas.wait(timeout=10) == 0, "Provider I/O occurred"
        degraded = http.get(f"{base}/api/stocks/2330/news", timeout=10).json()
        assert degraded["status"] == "unavailable", degraded
        summary = {"ok": True, "data_origin": str(args.atlas_db.resolve()), "omi_master_origin": str(args.omi_db.resolve()),
                   "acceptance": "isolated_persisted_evidence", "provider_calls": 0, "sqlite_query_only": True,
                   "atlas_down_status": degraded["status"], "stocks": summaries}
        (run / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"artifact": str(run / "summary.json"), **summary}, ensure_ascii=False, indent=2))
    finally:
        if server:
            server.should_exit = True
        if thread:
            thread.join(timeout=10)
        if sock:
            sock.close()
        if atlas.poll() is None:
            atlas.stdin.close()
            try:
                atlas.wait(timeout=10)
            except subprocess.TimeoutExpired:
                atlas.terminate()
                atlas.wait(timeout=5)
        node_log.close()


if __name__ == "__main__":
    main()
