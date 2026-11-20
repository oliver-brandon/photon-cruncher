"""Exercise an installed Aurora GUI on a disposable runner using synthetic inputs.

QT WebEngine's loopback debugger drives the real UI. Native pickers are bypassed
by supplying a path to the same frontend import controller used by those pickers.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from websocket import create_connection

from smoke_packaged_analysis import write_synthetic_recordings


def run(executable: Path, source: Path, output: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = dict(os.environ, PHOTON_CRUNCHER_DEV="1", QTWEBENGINE_REMOTE_DEBUGGING=f"127.0.0.1:{port}")
    process = subprocess.Popen([str(executable)], env=env)
    connection = None
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Installed app exited early ({process.returncode})")
            try:
                with urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as response:
                    pages = json.load(response)
                page = next((p for p in pages if p.get("type") == "page" and "index.html" in p.get("url", "")), None)
                if page:
                    break
            except (URLError, TimeoutError, OSError):
                pass
            time.sleep(0.5)
        else:
            raise TimeoutError("Installed Aurora interface did not appear")
        connection = create_connection(page["webSocketDebuggerUrl"], timeout=90,
                                       origin=f"http://127.0.0.1:{port}")

        def evaluate(expression: str):
            connection.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
                "expression": expression, "awaitPromise": True, "returnByValue": True,
            }}))
            while True:
                message = json.loads(connection.recv())
                if message.get("id") == 1:
                    result = message.get("result", {})
                    if "error" in message or "exceptionDetails" in result:
                        raise RuntimeError(str(message))
                    return result.get("result", {}).get("value")

        def wait(expression: str, description: str, seconds: int = 90):
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                if process.poll() is not None:
                    raise RuntimeError("Installed app exited while testing")
                if evaluate(expression):
                    return
                time.sleep(0.3)
            raise TimeoutError(f"Timed out waiting for {description}")

        wait("!!window.Aurora?.ready && !!window.auroraBridge", "native bridge")
        evaluate(f"window.Aurora.openLiveSession({json.dumps(str(source))})")
        wait("document.querySelector('#alignRunStatus').dataset.status === 'current'", "analysis")
        evaluate("window.Aurora.showView('batch')")
        evaluate(f"document.querySelector('#exportDir').value = {json.dumps(str(output))}; "
                 "document.querySelector('#exportDir').dispatchEvent(new Event('input', {bubbles:true})); "
                 "document.querySelector('#expFig').checked = true")
        wait("!document.querySelector('#launchBatch').disabled", "batch export enabled")
        evaluate("document.querySelector('#launchBatch').click()")
        wait("document.querySelector('#batchStatus').textContent === 'DONE' || "
             "document.querySelector('#batchStatus').textContent === 'FAIL'", "batch completion")
        status = evaluate("document.querySelector('#batchStatus').textContent")
        if status != "DONE":
            raise RuntimeError(f"Batch failed: {evaluate('document.querySelector(\"#batchDetail\").textContent')}")
        outcomes = evaluate("Array.from(document.querySelectorAll('#batchResults .batch-result-status'), "
                            "item => item.textContent.trim().toLowerCase())")
        if not outcomes or any(outcome != "exported" for outcome in outcomes):
            raise AssertionError(f"GUI batch did not export all selections: {outcomes}")
        manifests = list(output.rglob("*_analysis.json"))
        if not manifests or not list(output.rglob("*_heatmap.csv")) or not list(output.rglob("*_summary.png")):
            raise AssertionError("GUI export did not produce CSV, figure, and provenance")
        for path in manifests:
            data = json.loads(path.read_text(encoding="utf-8"))
            if Path(data["source"]["path"]).resolve() != source.resolve():
                raise AssertionError("GUI export provenance has incorrect source")
        print(f"Installed GUI import, analysis and CSV/figure export passed for {source.name}")
    finally:
        if connection:
            connection.close()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


if __name__ == "__main__":
    if os.environ.get("GITHUB_ACTIONS") != "true" or len(sys.argv) != 2:
        raise SystemExit("Usage on an isolated GitHub runner: python smoke_installed_gui.py EXECUTABLE")
    with tempfile.TemporaryDirectory(prefix="aurora-gui-smoke-") as temporary:
        root = Path(temporary)
        mat, tdt = write_synthetic_recordings(root)
        for source in (mat, tdt):
            run(Path(sys.argv[1]), source, root / (source.name + "-exports"))
