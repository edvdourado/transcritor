import asyncio
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import HTTPException, Request
from starlette.formparsers import MultiPartException, MultiPartParser
from python_multipart.exceptions import FormParserError


class UploadParser(MultiPartParser):
    """Keep Starlette's streaming parser, but place its spools in our session."""

    spool_max_size = 1024 * 1024

    def __init__(self, *args, directory: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self.directory = directory

    def on_headers_finished(self):
        super().on_headers_finished()
        # Starlette has no public spool-directory option. Keep this adapter small
        # and covered by upload/aborted-upload tests when upgrading Starlette.
        if self._current_part.file is not None:
            self._current_part.file.file.close()
            spool = tempfile.SpooledTemporaryFile(max_size=self.spool_max_size, dir=self.directory)
            self._files_to_close_on_error.append(spool)
            self._current_part.file.file = spool


@asynccontextmanager
async def upload_form(request: Request, directory: Path, maximum: int, timeout: float):
    # Multipart headers/boundaries also consume resources. Do not trust Content-Length.
    limit = maximum + 64 * 1024
    length = request.headers.get('content-length')
    if length is not None:
        try:
            if int(length) < 0:
                raise ValueError
            if int(length) > limit:
                raise HTTPException(413, 'Arquivo excede o tamanho permitido.')
        except ValueError:
            raise HTTPException(400, 'Requisição inválida.') from None
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'multipart/form-data':
        raise HTTPException(422, 'Envie um arquivo e um modelo em multipart/form-data.')

    async def bounded_stream():
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, 'Arquivo excede o tamanho permitido.')
            # Bound parser work per iteration, including when an ASGI server sends a large chunk.
            for offset in range(0, len(chunk), 64 * 1024):
                yield chunk[offset:offset + 64 * 1024]

    parser = UploadParser(request.headers, bounded_stream(), directory=directory,
                          max_files=1, max_fields=1, max_part_size=1024)
    try:
        try:
            form = await asyncio.wait_for(parser.parse(), timeout)
        except (MultiPartException, FormParserError):
            raise HTTPException(422, 'Multipart inválido. Envie um arquivo e um modelo.') from None
        except asyncio.TimeoutError:
            raise HTTPException(408, 'Tempo limite do upload excedido.') from None
        yield form
    finally:
        # Also close incomplete parts on disconnect/cancellation on older Starlette versions.
        for spool in parser._files_to_close_on_error:
            await asyncio.to_thread(spool.close)
