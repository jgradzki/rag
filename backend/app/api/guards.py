"""Checks that run before FastAPI reads a request body."""

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
UPLOAD_PATH = "/api/documents"
# Per uploaded file: its part headers and boundary - generous, real ones are ~200 bytes.
MULTIPART_OVERHEAD = 16 * 1024
# Any other request body (the chat question is at most 4000 characters).
MAX_JSON_BODY = 64 * 1024


class RequestGuard:
    """Rejects data-changing requests from foreign browser origins (CSRF) and bodies
    larger than an upload can be.

    FastAPI parses the whole body - and spools uploaded files to disk - before any
    dependency or route runs, so checks there come too late: another website's page
    could make the backend write gigabytes to the temp dir before getting its 403.
    A multipart upload is a CORS "simple request", sent without asking the server
    first, so CORS alone does not stop it. Browsers always add Origin to such requests;
    curl and scripts send none and pass.
    """

    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.allowed_origins = set(settings.cors_origins)
        per_file = int(settings.max_upload_mb * 1024 * 1024) + MULTIPART_OVERHEAD
        self.max_upload_body = settings.max_upload_files * per_file
        self.upload_limit = (
            f"at most {settings.max_upload_files} files of {settings.max_upload_mb:g} MB each"
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in WRITE_METHODS:
            rejection = self.check(scope)
            if rejection:
                status, detail = rejection
                await JSONResponse({"detail": detail}, status)(scope, receive, send)
                return
        await self.app(scope, receive, send)

    def check(self, scope: Scope) -> tuple[int, str] | None:
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if origin is not None and origin not in self.allowed_origins:
            return 403, f"Origin {origin} is not allowed (see CORS_ORIGINS)"

        is_upload = scope["path"].rstrip("/") == UPLOAD_PATH and scope["method"] == "POST"
        length = headers.get("content-length")
        if length is None:
            # A body without a declared length (chunked) can't be measured until it has
            # been read whole. Browsers and curl always send one; a DELETE has no body.
            if is_upload or "transfer-encoding" in headers:
                return 411, "Content-Length is required"
            return None
        if is_upload:
            if not length.isdigit() or int(length) > self.max_upload_body:
                return 413, f"Upload too large ({self.upload_limit})"
        elif not length.isdigit() or int(length) > MAX_JSON_BODY:
            return 413, f"Request body too large (at most {MAX_JSON_BODY // 1024} KB)"
        return None
