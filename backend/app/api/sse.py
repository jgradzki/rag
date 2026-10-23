"""Server-Sent Events formatting for the streamed chat answer."""

import json


def sse(event: str, data: object) -> str:
    """Format one Server-Sent Event. Data is JSON-encoded so newlines are safe."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
