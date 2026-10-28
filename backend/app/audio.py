import asyncio
import json
import math
import shutil
import subprocess
import wave
from pathlib import Path

from app.config import Settings


class AudioError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


async def run_tool(executable: str, arguments: list[str], timeout: float, *, capture_output: bool = True) -> bytes:
    executable = shutil.which(executable)
    # Windows may implicitly launch batch files through a shell even with exec.
    if not executable or Path(executable).suffix.lower() in {'.bat', '.cmd'}:
        raise AudioError('Ferramenta de áudio indisponível. Contate o administrador.', 503)
    # Shield creation so cancellation cannot orphan a child before we own its handle.
    creation = asyncio.create_task(asyncio.create_subprocess_exec(
        executable, *arguments, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ))
    process = None
    reader = None
    try:
        process = await asyncio.shield(creation)

        async def read_output():
            if not capture_output:
                await process.wait()
                return b''
            output = bytearray()
            while chunk := await process.stdout.read(8192):
                output.extend(chunk)
                if len(output) > 64 * 1024:
                    raise AudioError('Resposta inválida da ferramenta de áudio.')
            await process.wait()
            return bytes(output)

        reader = asyncio.create_task(read_output())
        output = await asyncio.wait_for(asyncio.shield(reader), timeout)
        if process.returncode:
            raise AudioError('Arquivo de áudio inválido ou corrompido.')
        return output
    except asyncio.TimeoutError:
        raise AudioError('Tempo limite de processamento do áudio excedido.', 504) from None
    except OSError:
        raise AudioError('Ferramenta de áudio indisponível. Contate o administrador.', 503) from None
    finally:
        async def stop():
            owned = process
            if owned is None:
                try:
                    owned = await creation
                except OSError:
                    return
            if owned.returncode is None:
                try:
                    owned.kill()
                except ProcessLookupError:
                    pass
            if reader is not None:
                if not reader.done():
                    reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
            if capture_output:
                # Drain a killed child's PIPE before wait(), including output-limit errors.
                while await owned.stdout.read(8192):
                    pass
            await owned.wait()

        # Repeated DELETE/shutdown cancellation must not interrupt process reaping.
        cleanup = asyncio.create_task(stop())
        cancelled = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        await cleanup
        if cancelled:
            raise asyncio.CancelledError


class AudioProcessor:
    def __init__(self, config: Settings):
        self.config = config

    async def validate(self, path: Path):
        if not 0 < path.stat().st_size <= self.config.max_upload_size_mb * 1024 * 1024:
            raise AudioError('Arquivo vazio ou acima do tamanho permitido.')
        output = await run_tool(self.config.ffprobe_path, [
            '-v', 'error', '-protocol_whitelist', 'file',
            '-format_whitelist', 'ogg,mp3,mov,wav',
            '-show_entries', 'format=format_name,duration:stream=codec_type,codec_name,sample_rate,channels,duration:stream_disposition=attached_pic',
            '-of', 'json', str(path.resolve()),
        ], self.config.ffprobe_timeout_seconds)
        try:
            data = json.loads(output)
            container = set(data['format']['format_name'].split(','))
            streams = data['streams']
            audio = [s for s in streams if s.get('codec_type') == 'audio']
            allowed = (
                ('ogg' in container and all(s.get('codec_name') == 'opus' for s in audio))
                or ('mp3' in container and all(s.get('codec_name') == 'mp3' for s in audio))
                or ('m4a' in container and all(s.get('codec_name') in {'aac', 'alac'} for s in audio))
                or ('wav' in container and all(s.get('codec_name') not in (None, 'unknown') for s in audio))
            )
            duration = float(data['format']['duration'])
            durations = [duration] + [float(s['duration']) for s in audio if s.get('duration') not in (None, 'N/A')]
            if (not allowed or not audio
                    or any(s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic') for s in streams)
                    or any(int(s.get('sample_rate', 0)) <= 0 or int(s.get('channels', 0)) <= 0 for s in audio)
                    or any(not math.isfinite(d) or d <= 0 for d in durations)):
                raise ValueError
            if max(durations) > self.config.max_audio_duration_seconds:
                raise AudioError('Áudio excede a duração máxima permitida.')
            return duration
        except (ValueError, KeyError, TypeError, AttributeError):
            raise AudioError('Arquivo de áudio inválido ou incompatível.') from None

    async def prepare(self, source: Path) -> Path:
        target = source.with_suffix('.wav')
        inspection = None
        try:
            await run_tool(self.config.ffmpeg_path, [
                '-nostdin', '-v', 'error', '-xerror', '-n',
                '-protocol_whitelist', 'file', '-format_whitelist', 'ogg,mp3,mov,wav',
                '-threads', '1', '-i', str(source.resolve()), '-map', '0:a:0',
                '-vn', '-sn', '-dn', '-map_metadata', '-1', '-threads', '1',
                '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
                # Decode one extra sample to detect understated input durations, never silently truncate.
                '-t', str(self.config.max_audio_duration_seconds + 1 / 16000),
                '-f', 'wav', str(target.resolve()),
            ], self.config.ffmpeg_timeout_seconds)
            inspection = asyncio.create_task(asyncio.to_thread(self.check_wav, target))
            await asyncio.shield(inspection)
            return target
        except BaseException:
            if inspection is not None:
                # A cancelled to_thread call keeps running. Wait for wave.open to
                # close its handle before unlinking the partial file on Windows.
                await asyncio.gather(inspection, return_exceptions=True)
            target.unlink(missing_ok=True)
            raise

    def check_wav(self, path: Path):
        try:
            with wave.open(str(path), 'rb') as audio:
                if (audio.getnchannels() != 1 or audio.getsampwidth() != 2
                        or audio.getframerate() != 16000 or audio.getnframes() <= 0
                        or audio.getnframes() > self.config.max_audio_duration_seconds * 16000):
                    raise ValueError
        except (OSError, EOFError, wave.Error, ValueError):
            raise AudioError('Não foi possível preparar o áudio dentro dos limites permitidos.') from None
