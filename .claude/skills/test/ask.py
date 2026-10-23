"""Ask the RAG backend one question and print the streamed result.

Used by the /test skill's live-tester agents. Handles UTF-8 (Polish questions are
mangled by curl in a Windows console) and reassembles the SSE stream.

Usage:
    backend/.venv/Scripts/python .claude/skills/test/ask.py --url http://localhost:8765 "Question?"
    ... --json   # machine-readable output
"""

import argparse
import json
import sys
import time

import httpx


def ask(base_url: str, question: str, timeout: float) -> dict:
    result = {"question": question, "sources": [], "answer": "", "error": None, "events": []}
    start = time.monotonic()
    first_token_at = None
    with httpx.stream(
        "POST", f"{base_url}/api/chat", json={"question": question}, timeout=timeout
    ) as response:
        result["status"] = response.status_code
        if response.status_code != 200:
            result["error"] = response.read().decode("utf-8", "replace")
            return result
        buffer = ""
        for text in response.iter_text():
            buffer += text
            *events, buffer = buffer.split("\n\n")
            for raw in events:
                # split("\n"), not splitlines(): JSON data may contain U+2028 and the like
                lines = (line.rstrip("\r") for line in raw.split("\n"))
                fields = dict(line.split(": ", 1) for line in lines if ": " in line)
                event, data = fields.get("event"), json.loads(fields.get("data", "null"))
                result["events"].append(event)
                if event == "sources":
                    result["sources"] = data
                elif event == "token":
                    first_token_at = first_token_at or time.monotonic()
                    result["answer"] += data
                elif event == "error":
                    result["error"] = data
    result["seconds_total"] = round(time.monotonic() - start, 1)
    result["seconds_to_first_token"] = round(first_token_at - start, 1) if first_token_at else None
    return result


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--url", required=True, help="backend base URL, e.g. http://localhost:8765")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    r = ask(args.url.rstrip("/"), args.question, args.timeout)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return
    print(f"Q: {r['question']}")
    events = r["events"]
    print(
        f"status={r.get('status')} total={r.get('seconds_total')}s "
        f"first_token={r.get('seconds_to_first_token')}s events={events[:3]}...{events[-1:]}"
    )
    for s in r["sources"]:
        page = f", page {s['page']}" if s.get("page") else ""
        print(f"  [{s['number']}] {s['source']}{page} relevance={s['score']}")
    if r["error"]:
        print(f"ERROR: {r['error']}")
    print(f"A: {r['answer'].strip()}")


if __name__ == "__main__":
    main()
