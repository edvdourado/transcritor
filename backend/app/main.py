import asyncio
import tempfile
import shutil
import time
import math
import re
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import UUID, uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from starlette.datastructures import UploadFile
from starlette.responses import FileResponse

from app.config import Settings, settings
from app.jobs import JobResponse, Jobs
from app.transcriber import MockTranscriber, Transcriber, WhisperTranscriber
from app.audio import AudioError, AudioProcessor
from app.uploads import upload_form


class AudioResponse(FileResponse):
    def __init__(self, path, lock):
        super().__init__(path, media_type='audio/wav', headers={'Cache-Control': 'no-store'})
        self.lock = lock

    async def __call__(self, scope, receive, send):
        # Windows cannot unlink an open file. Deletion waits for this transfer;
        # the queue's lock remains free and other jobs can keep processing.
        async with self.lock:
            if not Path(self.path).is_file():
                await Response(status_code=404)(scope, receive, send)
                return
            await super().__call__(scope, receive, send)


def create_app(config: Settings = settings, transcriber: Transcriber | None = None):
    @asynccontextmanager
    async def lifespan(app):
        limits = (config.file_retention_seconds, config.max_upload_size_mb, config.max_audio_duration_seconds,
                  config.ffprobe_timeout_seconds, config.ffmpeg_timeout_seconds, config.upload_timeout_seconds)
        if (any(not math.isfinite(value) or value <= 0 for value in limits)
                or not math.isfinite(config.mock_processing_seconds) or config.mock_processing_seconds < 0):
            raise ValueError('Limits must be finite and positive; mock delay must be finite and nonnegative')
        if config.engine not in ('mock', 'whisper'):
            raise ValueError('TRANSCRITOR_ENGINE must be mock or whisper')
        if (config.whisper_threads <= 0 or not math.isfinite(config.whisper_timeout_seconds)
                or config.whisper_timeout_seconds <= 0
                or not re.fullmatch(r'[a-z]{2,3}|auto', config.whisper_language)):
            raise ValueError('Invalid Whisper threads, timeout or language')
        config.temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='transcritor-', dir=config.temp_dir) as directory:
            audio = AudioProcessor(config)
            selected = transcriber if transcriber is not None else (
                WhisperTranscriber(config) if config.engine == 'whisper' else MockTranscriber(config.mock_processing_seconds))
            manager = Jobs(selected,
                           config.file_retention_seconds, audio=audio)
            app.state.jobs = manager
            app.state.directory = Path(directory)

            async def cleanup():
                while True:
                    # Only abandoned session directories owned by this application.
                    for old in config.temp_dir.glob('transcritor-*'):
                        if (old != Path(directory) and not old.is_symlink() and old.is_dir()
                                and time.time() - old.stat().st_mtime >= config.file_retention_seconds):
                            await asyncio.to_thread(shutil.rmtree, old)
                    await manager.expire()
                    await asyncio.sleep(min(60, config.file_retention_seconds))

            cleaner = asyncio.create_task(cleanup())
            try:
                yield
            finally:
                cleaner.cancel()
                with suppress(asyncio.CancelledError):
                    await cleaner
                await manager.close()

    application = FastAPI(title='Transcritor API', version='0.3.0', lifespan=lifespan,
                          docs_url=None, redoc_url=None, openapi_url=None)

    @application.get('/api/v1/health')
    def health() -> dict[str, str]:
        return {'status': 'ok'}

    @application.get('/api/v1/capabilities')
    async def capabilities(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        return {'engine': application.state.jobs.engine}

    @application.post('/api/v1/jobs', status_code=202, response_model=JobResponse)
    async def upload(request: Request):
        manager = application.state.jobs
        path = application.state.directory / uuid4().hex
        reserved = False
        submitted = False
        try:
            reserved = await manager.reserve()
            if not reserved:
                raise HTTPException(429, 'Fila cheia. Aguarde e tente novamente.')
            async with upload_form(request, application.state.directory,
                                   config.max_upload_size_mb * 1024 * 1024,
                                   config.upload_timeout_seconds) as form:
                file, model = form.get('file'), form.get('model')
                if not isinstance(file, UploadFile) or model not in ('small', 'medium'):
                    raise HTTPException(422, 'Arquivo ou modelo inválido.')
                if Path(file.filename or '').suffix.lower() not in {'.ogg', '.mp3', '.m4a', '.wav'}:
                    raise HTTPException(422, 'Extensão não permitida. Use OGG, MP3, M4A ou WAV.')
                size = 0
                with path.open('xb') as target:
                    while chunk := await file.read(64 * 1024):
                        size += len(chunk)
                        if size > config.max_upload_size_mb * 1024 * 1024:
                            raise HTTPException(413, 'Arquivo excede o tamanho permitido.')
                        writing = asyncio.create_task(asyncio.to_thread(target.write, chunk))
                        try:
                            await asyncio.shield(writing)
                        finally:
                            # Cancellation must not close a file still owned by a writer thread.
                            await writing
                if not size:
                    raise HTTPException(422, 'O arquivo está vazio.')
            duration = await manager.audio.validate(path)
            result = await manager.submit(path, model, duration)
            submitted = True
            return result
        except AudioError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError:
            raise HTTPException(503, 'Armazenamento temporário indisponível.') from None
        finally:
            if not submitted:
                try:
                    path.unlink(missing_ok=True)
                finally:
                    if reserved:
                        await manager.release()

    @application.get('/api/v1/jobs/{job_id}/audio')
    async def get_audio(job_id: UUID):
        manager = application.state.jobs
        await manager.expire()
        async with manager.lock:
            job = manager.items.get(job_id)
            path = job.prepared_path if job else None
            root = application.state.directory.resolve()
            if (path is None or path.is_symlink() or path.resolve().parent != root or not path.is_file()):
                raise HTTPException(404, 'Áudio não disponível.')
            return AudioResponse(path, job.audio_lock)

    @application.get('/api/v1/jobs/{job_id}', response_model=JobResponse)
    async def get_job(job_id: UUID):
        await application.state.jobs.expire()
        job = await application.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, 'Trabalho não encontrado.')
        return job

    @application.delete('/api/v1/jobs/{job_id}', status_code=204)
    async def delete_job(job_id: UUID):
        if not await application.state.jobs.delete(job_id):
            raise HTTPException(404, 'Trabalho não encontrado.')
        return Response(status_code=204)

    return application


app = create_app()

if __name__ == '__main__':
    uvicorn.run(app, host=settings.host, port=settings.port)
