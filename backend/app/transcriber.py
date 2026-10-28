import asyncio
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.audio import AudioError, run_tool
from app.config import Settings

Model = Literal["small", "medium"]
Engine = Literal["mock", "whisper"]


@dataclass
class Transcription:
    text: str
    segments: list[dict]


class Transcriber(Protocol):
    # Production Jobs supplies a validated WAV: PCM s16le, 16 kHz, mono.
    # Cancellation contract: propagate CancelledError only after stopping and
    # awaiting owned subprocesses. The manager awaits this before freeing a slot.
    async def transcribe(self, path: Path, model: Model) -> str | Transcription: ...


class MockTranscriber:
    engine: Engine = 'mock'

    def __init__(self, seconds: float):
        self.seconds = seconds

    async def transcribe(self, path: Path, model: Model) -> str:
        await asyncio.sleep(self.seconds)
        return f"[TESTE MOCK — {model}] Transcrição fictícia; nenhum áudio foi transcrito."


class TranscriptionError(Exception):
    pass


def read_transcription(path: Path) -> Transcription:
    try:
        # Bound both the disk read and JSON parsing; never publish CLI metadata/paths.
        with path.open('rb') as source:
            raw = source.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get('transcription'), list):
            raise ValueError
        segments = []
        for segment in data['transcription']:
            if not isinstance(segment, dict) or not isinstance(segment.get('text'), str):
                raise ValueError
            segment['text'].encode('utf-8')
            saved = {'text': segment['text']}
            for key in ('offsets', 'timestamps'):
                if key not in segment:
                    continue
                times = segment[key]
                if not isinstance(times, dict) or not {'from', 'to'} <= times.keys():
                    raise ValueError
                start, end = times['from'], times['to']
                if key == 'offsets':
                    if type(start) is not int or type(end) is not int or not 0 <= start <= end:
                        raise ValueError
                elif any(not isinstance(t, str) or not re.fullmatch(r'\d{2,}:[0-5]\d:[0-5]\d[,.]\d{3}', t)
                         for t in (start, end)):
                    raise ValueError
                saved[key] = {'from': start, 'to': end}
            segments.append(saved)
        # Concatenate verbatim: spaces, punctuation and line breaks belong to the model.
        return Transcription(''.join(segment['text'] for segment in segments), segments)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise TranscriptionError('Saída inválida do transcritor.') from None


class WhisperTranscriber:
    engine: Engine = 'whisper'

    def __init__(self, config: Settings):
        self.config = config

    async def transcribe(self, path: Path, model: Model) -> Transcription:
        models = {'small': self.config.whisper_model_small, 'medium': self.config.whisper_model_medium}
        configured = models.get(model)
        if not configured or not Path(configured).is_file():
            raise TranscriptionError('Modelo de transcrição indisponível.')
        # The queue supplies a unique prepared input. A fresh directory isolates even
        # retries of that same input and removes JSON/partial output on every exit.
        with tempfile.TemporaryDirectory(prefix='whisper-', dir=path.parent) as directory:
            output = Path(directory) / 'result'
            try:
                await run_tool(self.config.whisper_cli_path, [
                    '-m', str(Path(configured).resolve()), '-f', str(path.resolve()),
                    '-l', self.config.whisper_language, '-t', str(self.config.whisper_threads),
                    '-ng', '-oj', '-of', str(output.resolve()),
                ], self.config.whisper_timeout_seconds, capture_output=False)
            except AudioError:
                raise TranscriptionError('Não foi possível executar o transcritor.') from None
            reading = asyncio.create_task(asyncio.to_thread(read_transcription, output.with_suffix('.json')))
            try:
                return await asyncio.shield(reading)
            finally:
                # to_thread keeps running after cancellation; close the file before cleanup.
                finished = asyncio.gather(reading, return_exceptions=True)
                cancelled = False
                while not finished.done():
                    try:
                        await asyncio.shield(finished)
                    except asyncio.CancelledError:
                        cancelled = True
                if cancelled:
                    raise asyncio.CancelledError
