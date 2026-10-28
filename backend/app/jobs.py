import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.transcriber import Engine, Model, Transcriber, Transcription
from app.audio import AudioProcessor

logger = logging.getLogger(__name__)


class JobResponse(BaseModel):
    id: UUID
    model: Model
    state: Literal["queued", "processing", "completed", "failed"]
    transcript: str | None = None
    error: str | None = None
    engine: Engine | None = None
    total_seconds: float | None = None
    processing_seconds: float | None = None
    audio_duration_seconds: float | None = None


@dataclass
class Job:
    response: JobResponse
    path: Path
    accepted: float
    started: float | None = None
    finished: float | None = None
    task: asyncio.Task | None = None
    prepared_path: Path | None = None
    segments: list[dict] | None = None
    audio_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class Jobs:
    def __init__(self, transcriber: Transcriber, retention: int, clock=time.monotonic,
                 audio: AudioProcessor | None = None):
        self.transcriber = transcriber
        engine = getattr(transcriber, 'engine', None)
        self.engine = engine if engine in ('mock', 'whisper') else None
        self.audio = audio
        self.retention = retention
        self.clock = clock
        self.lock = asyncio.Lock()
        self.items: dict[UUID, Job] = {}
        self.active: Job | None = None
        self.waiting: Job | None = None
        self.reservations = 0

    async def reserve(self) -> bool:
        async with self.lock:
            if self.reservations + int(self.active is not None) + int(self.waiting is not None) >= 2:
                return False
            self.reservations += 1
            return True

    async def release(self):
        async with self.lock:
            self.reservations -= 1

    async def submit(self, path: Path, model: Model, audio_duration_seconds: float | None = None) -> JobResponse:
        async with self.lock:
            self.reservations -= 1
            job = Job(JobResponse(id=uuid4(), model=model, state="queued", engine=self.engine,
                                  audio_duration_seconds=audio_duration_seconds), path, self.clock())
            self.items[job.response.id] = job
            if self.active is None:
                self.start(job)
            else:
                self.waiting = job
            return self.snapshot(job)

    def snapshot(self, job: Job) -> JobResponse:
        end = job.finished if job.finished is not None else self.clock()
        return job.response.model_copy(update={
            'total_seconds': max(0.0, end - job.accepted),
            'processing_seconds': max(0.0, end - job.started) if job.started is not None else None,
        })

    def start(self, job: Job):
        self.active = job
        job.response.state = "processing"
        job.task = asyncio.create_task(self.run(job))

    async def run(self, job: Job):
        job.started = self.clock()
        try:
            if self.audio:
                job.prepared_path = await self.audio.prepare(job.path)
            result = await self.transcriber.transcribe(
                job.prepared_path or job.path, job.response.model)
            if isinstance(result, Transcription):
                job.segments = result.segments
                result = result.text
            job.response.transcript = result
            job.response.state = "completed"
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Audio processing failed for job %s", job.response.id)
            job.response.state = "failed"
            job.response.error = "Não foi possível processar o áudio. Tente novamente."
        finally:
            job.finished = self.clock()
            async with self.lock:
                self.active = None
                if self.waiting is not None:
                    following, self.waiting = self.waiting, None
                    self.start(following)

    async def get(self, job_id: UUID) -> JobResponse | None:
        async with self.lock:
            job = self.items.get(job_id)
            return self.snapshot(job) if job else None

    async def delete(self, job_id: UUID) -> bool:
        async with self.lock:
            job = self.items.pop(job_id, None)
            if job is None:
                return False
            if self.waiting is job:
                self.waiting = None
            if job.task and not job.task.done():
                job.task.cancel()
        if job.task:
            try:
                await job.task
            except asyncio.CancelledError:
                pass
        async with self.lock:
            if self.active is job:
                self.active = None
                if self.waiting is not None:
                    following, self.waiting = self.waiting, None
                    self.start(following)
        async with job.audio_lock:
            job.path.unlink(missing_ok=True)
            if job.prepared_path:
                job.prepared_path.unlink(missing_ok=True)
        return True

    async def expire(self):
        async with self.lock:
            expired = [key for key, job in self.items.items()
                       if job.finished is not None and self.clock() - job.finished >= self.retention]
        for key in expired:
            await self.delete(key)

    async def close(self):
        # Remove queued jobs first so shutdown never starts another transcription.
        if self.waiting:
            await self.delete(self.waiting.response.id)
        for key in list(self.items):
            await self.delete(key)
