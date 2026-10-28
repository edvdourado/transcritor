import asyncio
import io
import json
import shutil
import subprocess
import sys
import wave
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import audio as module
from app.audio import AudioError, AudioProcessor, run_tool
from app.config import settings
from app.main import create_app
from app.uploads import upload_form


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b'\0\0' * 1600)
    return output.getvalue()


def probe(container='wav', codec='pcm_s16le', duration='0.1'):
    return {'format': {'format_name': container, 'duration': duration},
            'streams': [{'codec_type': 'audio', 'codec_name': codec, 'sample_rate': '16000', 'channels': 1}]}


@pytest.mark.parametrize('container,codec', [
    ('wav', 'pcm_s16le'), ('ogg', 'opus'), ('mp3', 'mp3'), ('mov,mp4,m4a,3gp,3g2,mj2', 'aac'),
])
def test_valid_probe(tmp_path, monkeypatch, container, codec):
    source = tmp_path / 'source'
    source.write_bytes(b'audio')
    mocked = AsyncMock(return_value=json.dumps(probe(container, codec)).encode())
    monkeypatch.setattr(module, 'run_tool', mocked)
    assert asyncio.run(AudioProcessor(settings).validate(source)) == 0.1
    args = mocked.call_args.args[1]
    assert args[-1] == str(source.resolve())
    assert '-protocol_whitelist' in args and '-format_whitelist' in args


def test_cover_art_is_not_video_content(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.write_bytes(b'audio')
    data = probe('mp3', 'mp3')
    data['streams'].append({'codec_type': 'video', 'disposition': {'attached_pic': 1}})
    monkeypatch.setattr(module, 'run_tool', AsyncMock(return_value=json.dumps(data).encode()))
    asyncio.run(AudioProcessor(settings).validate(source))


@pytest.mark.parametrize('data', [
    b'not json', b'{}', json.dumps(probe(duration='nan')).encode(),
    json.dumps(probe(duration='-1')).encode(), json.dumps(probe(duration='0')).encode(),
    json.dumps(probe(duration='1801')).encode(), json.dumps(probe('ogg', 'vorbis')).encode(),
    json.dumps({'format': probe()['format'], 'streams': []}).encode(),
    json.dumps({'format': probe()['format'], 'streams': [{'codec_type': 'video'}]}).encode(),
    json.dumps(probe('matroska', 'opus')).encode(),
])
def test_invalid_probe(tmp_path, monkeypatch, data):
    source = tmp_path / 'source'
    source.write_bytes(b'audio')
    monkeypatch.setattr(module, 'run_tool', AsyncMock(return_value=data))
    with pytest.raises(AudioError):
        asyncio.run(AudioProcessor(settings).validate(source))


@pytest.mark.parametrize('mode', ['error', 'timeout', 'cancel', 'success', 'output-limit'])
def test_subprocess_lifecycle(monkeypatch, mode):
    class Process:
        returncode = None
        killed = False
        waited = False

        def __init__(self):
            self.stdout = self
            self.reads = 0

        async def read(self, size):
            if self.killed:
                return b''
            self.reads += 1
            started.set()
            if mode in ('timeout', 'cancel'):
                await asyncio.Event().wait()
            if mode == 'output-limit':
                return b'x' * 8192
            return b'{}' if self.reads == 1 else b''

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            self.waited = True
            if not self.killed:
                self.returncode = 1 if mode == 'error' else 0

    async def check():
        nonlocal started
        started = asyncio.Event()
        process = Process()
        spawn = AsyncMock(return_value=process)
        monkeypatch.setattr(module.shutil, 'which', lambda name: name)
        monkeypatch.setattr(module.asyncio, 'create_subprocess_exec', spawn)
        task = asyncio.create_task(run_tool('tool', ['safe', 'arguments'], 0.01 if mode == 'timeout' else 5))
        if mode == 'cancel':
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif mode == 'success':
            assert await task == b'{}'
        else:
            with pytest.raises(AudioError):
                await task
        assert process.waited
        assert process.killed == (mode in ('timeout', 'cancel', 'output-limit'))
        assert spawn.call_args.args == ('tool', 'safe', 'arguments')
        assert 'shell' not in spawn.call_args.kwargs
        assert spawn.call_args.kwargs['stderr'] == subprocess.DEVNULL

    started = None
    asyncio.run(asyncio.wait_for(check(), 5))


@pytest.mark.parametrize('missing', [True, False])
def test_unavailable_tool(monkeypatch, missing):
    monkeypatch.setattr(module.shutil, 'which', lambda name: None if missing else name)
    monkeypatch.setattr(module.asyncio, 'create_subprocess_exec', AsyncMock(side_effect=OSError('secret path')))
    with pytest.raises(AudioError) as caught:
        asyncio.run(run_tool('missing', [], 1))
    assert caught.value.status == 503
    assert 'secret' not in str(caught.value)


def test_cancel_during_process_creation(monkeypatch):
    async def check():
        entered, proceed = asyncio.Event(), asyncio.Event()

        class Process:
            returncode = None
            killed = False
            waited = False

            def kill(self):
                self.killed = True
                self.returncode = -9

            async def wait(self):
                self.waited = True

        process = Process()
        process.stdout = AsyncMock()
        process.stdout.read.return_value = b''

        async def spawn(*args, **kwargs):
            entered.set()
            await proceed.wait()
            return process

        monkeypatch.setattr(module.shutil, 'which', lambda name: name)
        monkeypatch.setattr(module.asyncio, 'create_subprocess_exec', spawn)
        task = asyncio.create_task(run_tool('tool', [], 1))
        await entered.wait()
        task.cancel()
        proceed.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert process.killed and process.waited
    asyncio.run(asyncio.wait_for(check(), 3))


@pytest.mark.parametrize('mode', ['error', 'timeout', 'cancel', 'success', 'bad-output'])
def test_conversion_and_partial_cleanup(tmp_path, monkeypatch, mode):
    source = tmp_path / 'random-id'
    source.write_bytes(b'original')
    target = source.with_suffix('.wav')

    async def fake(executable, args, timeout):
        assert args[args.index('-acodec') + 1] == 'pcm_s16le'
        assert args[args.index('-ar') + 1] == '16000'
        assert args[args.index('-ac') + 1] == '1'
        target.write_bytes(wav_bytes() if mode == 'success' else b'partial')
        if mode == 'cancel':
            raise asyncio.CancelledError
        if mode in ('error', 'timeout'):
            raise AudioError('Falha segura', 504 if mode == 'timeout' else 422)
        return b''

    monkeypatch.setattr(module, 'run_tool', fake)
    if mode == 'success':
        assert asyncio.run(AudioProcessor(settings).prepare(source)) == target
    else:
        with pytest.raises(asyncio.CancelledError if mode == 'cancel' else AudioError):
            asyncio.run(AudioProcessor(settings).prepare(source))
        assert not target.exists()
    assert source.read_bytes() == b'original'


@pytest.fixture
def client(tmp_path, monkeypatch):
    async def fake(executable, args, timeout):
        if '-show_entries' in args:
            return json.dumps(probe()).encode()
        Path(args[-1]).write_bytes(wav_bytes())
        return b''

    monkeypatch.setattr(module, 'run_tool', fake)
    config = replace(settings, temp_dir=tmp_path, max_upload_size_mb=1, mock_processing_seconds=0)
    with TestClient(create_app(config)) as connection:
        yield connection
    assert list(tmp_path.iterdir()) == []


def post(client, content=b'audio', filename='voice.ogg'):
    return client.post('/api/v1/jobs', data={'model': 'small'}, files={'file': (filename, content, 'text/plain')})


def finish(client, job_id):
    async def wait():
        await client.app.state.jobs.items[UUID(job_id)].task
    client.portal.call(wait)


def test_http_playback_and_retention(client, tmp_path):
    job = post(client, filename='../../evil; & name.wav').json()
    finish(client, job['id'])
    url = '/api/v1/jobs/' + job['id'] + '/audio'
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers['content-type'] == 'audio/wav'
    assert response.content == wav_bytes()
    assert client.get(url, headers={'Range': 'bytes=0-9'}).status_code == 206
    manager = client.app.state.jobs
    stored = manager.items[UUID(job['id'])]
    assert stored.prepared_path.parent == client.app.state.directory
    assert stored.path.name not in response.headers.get('content-disposition', '')
    assert client.get('/api/v1/jobs/' + job['id']).json()['state'] == 'completed'
    manager.clock = lambda: stored.finished + manager.retention
    assert client.get(url).status_code == 404
    assert not stored.path.exists() and not stored.prepared_path.exists()
    assert client.get('/api/v1/jobs/' + job['id']).status_code == 404
    assert client.get('/api/v1/jobs/' + str(uuid4()) + '/audio').status_code == 404


def test_no_playback_outside_session(client, tmp_path):
    job = post(client).json()
    finish(client, job['id'])
    stored = client.app.state.jobs.items[UUID(job['id'])]
    original = stored.prepared_path
    outside = tmp_path / 'private.wav'
    outside.write_bytes(wav_bytes())
    stored.prepared_path = outside
    assert client.get('/api/v1/jobs/' + job['id'] + '/audio').status_code == 404
    stored.prepared_path = original
    outside.unlink()


def test_probe_failure_http(client, monkeypatch):
    monkeypatch.setattr(module, 'run_tool', AsyncMock(side_effect=AudioError('Áudio inválido.')))
    response = post(client)
    assert response.status_code == 422
    assert list(client.app.state.directory.iterdir()) == []
    assert client.app.state.jobs.reservations == 0


@pytest.mark.parametrize('status', [503, 504])
def test_probe_operational_errors_http(client, monkeypatch, status):
    monkeypatch.setattr(module, 'run_tool', AsyncMock(side_effect=AudioError('Falha segura.', status)))
    assert post(client).status_code == status
    assert client.app.state.jobs.reservations == 0
    assert list(client.app.state.directory.iterdir()) == []


def test_multipart_cardinality_and_invalid_body(client):
    response = client.post('/api/v1/jobs', data={'model': 'small'},
                           files=[('file', ('a.wav', b'a')), ('file', ('b.wav', b'b'))])
    assert response.status_code == 422
    response = client.post('/api/v1/jobs', data={'model': 'small', 'extra': 'value'},
                           files={'file': ('a.wav', b'a')})
    assert response.status_code == 422
    response = client.post('/api/v1/jobs', content=b'garbage',
                           headers={'content-type': 'multipart/form-data; boundary=x'})
    assert response.status_code == 422
    assert client.app.state.jobs.reservations == 0
    assert list(client.app.state.directory.iterdir()) == []


def test_real_spool_rollover_is_inside_session(client, monkeypatch):
    from app import uploads
    real_spool = uploads.tempfile.SpooledTemporaryFile
    tracked = []

    def track(*args, **kwargs):
        result = real_spool(*args, **kwargs)
        if kwargs.get('dir') == client.app.state.directory:
            tracked.append(result)
        return result

    monkeypatch.setattr(uploads.tempfile, 'SpooledTemporaryFile', track)
    assert post(client, b'a' * (1024 * 1024 + 1)).status_code == 413
    assert tracked and all(spool._rolled and spool.closed for spool in tracked)
    assert list(client.app.state.directory.iterdir()) == []


def test_ffmpeg_failure_preserves_safe_job_error(client, monkeypatch):
    async def fake(executable, args, timeout):
        if '-show_entries' in args:
            return json.dumps(probe()).encode()
        Path(args[-1]).write_bytes(b'partial')
        raise AudioError('secret internal detail')
    monkeypatch.setattr(module, 'run_tool', fake)
    job = post(client).json()
    finish(client, job['id'])
    result = client.get('/api/v1/jobs/' + job['id']).json()
    assert result['state'] == 'failed' and 'secret' not in result['error']
    assert client.get('/api/v1/jobs/' + job['id'] + '/audio').status_code == 404
    assert len(list(client.app.state.directory.iterdir())) == 1


def test_cancel_conversion_releases_queue_after_stop(client, monkeypatch):
    started = asyncio.Event()
    stopped = []

    async def prepare(self, source):
        target = source.with_suffix('.wav')
        target.write_bytes(b'partial')
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            target.unlink(missing_ok=True)
            stopped.append(source)

    monkeypatch.setattr(AudioProcessor, 'prepare', prepare)
    first = post(client).json()
    client.portal.call(started.wait)
    second = post(client).json()
    assert second['state'] == 'queued'
    assert client.get('/api/v1/jobs/' + first['id'] + '/audio').status_code == 404
    assert post(client).status_code == 429
    assert client.delete('/api/v1/jobs/' + first['id']).status_code == 204
    assert len(stopped) == 1
    assert client.get('/api/v1/jobs/' + second['id']).json()['state'] == 'processing'


@pytest.mark.parametrize('mode', ['oversized', 'disconnect', 'timeout', 'malformed'])
def test_streamed_multipart_limits_and_spool_cleanup(tmp_path, monkeypatch, mode):
    from app import uploads
    from starlette.requests import ClientDisconnect

    spools = []
    real_spool = uploads.tempfile.SpooledTemporaryFile

    def track(*args, **kwargs):
        result = real_spool(*args, **kwargs)
        if kwargs.get('dir') == tmp_path:
            spools.append(result)
        return result

    monkeypatch.setattr(uploads.tempfile, 'SpooledTemporaryFile', track)

    async def check():
        calls = 0

        async def receive():
            nonlocal calls
            calls += 1
            if calls == 1:
                return {'type': 'http.request', 'body': b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="x.wav"\r\n\r\n' + b'x' * 4096,
                        'more_body': True}
            if mode == 'disconnect':
                return {'type': 'http.disconnect'}
            if mode == 'timeout':
                await asyncio.Event().wait()
            return {'type': 'http.request', 'body': b'x' * (70 * 1024), 'more_body': False}

        headers = [(b'content-type', b'multipart/form-data; boundary=boundary')]
        if mode == 'malformed':
            headers = [(b'content-type', b'multipart/form-data')]
        request = Request({'type': 'http', 'headers': headers}, receive)
        with pytest.raises((ClientDisconnect, uploads.HTTPException)) as caught:
            async with upload_form(request, tmp_path, 1024, 0.01):
                pytest.fail('Invalid upload accepted')
        if mode != 'disconnect':
            assert caught.value.status_code == {'oversized': 413, 'timeout': 408, 'malformed': 422}[mode]
        assert all(spool.closed for spool in spools)
        assert list(tmp_path.iterdir()) == []

    asyncio.run(asyncio.wait_for(check(), 3))


@pytest.mark.parametrize('codec,extension,container', [
    ('pcm_s16le', 'wav', 'wav'), ('libopus', 'ogg', 'ogg'), ('libmp3lame', 'mp3', 'mp3'), ('aac', 'm4a', 'ipod'),
])
def test_real_audio_pipeline(tmp_path, codec, extension, container):
    if not shutil.which(settings.ffmpeg_path) or not shutil.which(settings.ffprobe_path):
        pytest.skip('FFmpeg/FFprobe não disponíveis; demais testes usam mocks.')
    source = tmp_path / ('generated.' + extension)
    subprocess.run([settings.ffmpeg_path, '-nostdin', '-v', 'error', '-f', 'lavfi',
                    '-i', 'sine=frequency=440:sample_rate=44100:duration=0.2',
                    '-ac', '2', '-c:a', codec, '-f', container, str(source)],
                   check=True, timeout=15, capture_output=True)
    config = replace(settings, temp_dir=tmp_path / 'sessions', mock_processing_seconds=0)
    with TestClient(create_app(config)) as client:
        result = post(client, source.read_bytes(), 'misleading.wav')
        assert result.status_code == 202, result.text
        job = result.json()
        finish(client, job['id'])
        assert client.get('/api/v1/jobs/' + job['id']).json()['state'] == 'completed'
        playback = client.get('/api/v1/jobs/' + job['id'] + '/audio')
        assert playback.status_code == 200
        with wave.open(io.BytesIO(playback.content), 'rb') as audio:
            assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 16000)
            assert audio.getnframes() > 0
        for invalid in (b'not audio', b'RIFF\xff\xff\xff\xffWAVE', b''):
            assert post(client, invalid, 'allowed.wav').status_code == 422
    assert list(config.temp_dir.iterdir()) == []


def test_real_subprocess_timeout_and_cancel(tmp_path):
    async def check():
        with pytest.raises(AudioError):
            await run_tool(sys.executable, ['-c', "print('x' * 10000000)"], 3)
        with pytest.raises(AudioError) as caught:
            await run_tool(sys.executable, ['-c', 'import time; time.sleep(30)'], 0.1)
        assert caught.value.status == 504
        task = asyncio.create_task(run_tool(sys.executable, ['-c', 'import time; time.sleep(30)'], 30))
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(asyncio.wait_for(check(), 5))


def test_playback_deletion_waits_without_holding_queue_lock(tmp_path):
    from app.jobs import Jobs
    from app.main import AudioResponse
    from app.transcriber import MockTranscriber

    async def check():
        manager = Jobs(MockTranscriber(0), 3600)
        source = tmp_path / 'original'
        source.write_bytes(b'original')
        await manager.reserve()
        response = await manager.submit(source, 'small')
        job = manager.items[response.id]
        await job.task
        job.prepared_path = tmp_path / 'prepared.wav'
        job.prepared_path.write_bytes(wav_bytes())
        sending, proceed = asyncio.Event(), asyncio.Event()

        async def send(message):
            if message['type'] == 'http.response.body':
                sending.set()
                await proceed.wait()

        scope = {'type': 'http', 'method': 'GET', 'headers': [], 'asgi': {'spec_version': '2.4'}}
        transfer = asyncio.create_task(AudioResponse(job.prepared_path, job.audio_lock)(scope, None, send))
        await sending.wait()
        deletion = asyncio.create_task(manager.delete(response.id))
        # get() acquires the queue lock and must complete while the transfer is paused.
        await manager.get(response.id)
        assert not deletion.done() and job.prepared_path.exists()
        proceed.set()
        await transfer
        assert await deletion
        assert not job.prepared_path.exists() and not source.exists()

    asyncio.run(asyncio.wait_for(check(), 5))


def test_real_audio_without_track_and_exceeded_duration(tmp_path):
    if not shutil.which(settings.ffmpeg_path) or not shutil.which(settings.ffprobe_path):
        pytest.skip('FFmpeg/FFprobe não disponíveis.')
    video = tmp_path / 'video.m4a'
    subprocess.run([settings.ffmpeg_path, '-nostdin', '-v', 'error', '-f', 'lavfi',
                    '-i', 'color=c=black:s=16x16:d=0.1', '-an', '-c:v', 'mpeg4', '-f', 'mp4', str(video)],
                   check=True, timeout=15, capture_output=True)
    config = replace(settings, temp_dir=tmp_path / 'sessions', max_audio_duration_seconds=1)
    long_audio = io.BytesIO()
    with wave.open(long_audio, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b'\0\0' * 17600)
    with TestClient(create_app(config)) as client:
        assert post(client, video.read_bytes(), 'allowed.m4a').status_code == 422
        assert post(client, long_audio.getvalue(), 'allowed.wav').status_code == 422
        assert list(client.app.state.directory.iterdir()) == []


def test_cancel_during_wav_inspection(tmp_path, monkeypatch):
    import threading

    source = tmp_path / 'original'
    source.write_bytes(b'audio')
    entered, proceed = threading.Event(), threading.Event()

    async def fake(*args):
        source.with_suffix('.wav').write_bytes(wav_bytes())

    def inspect(self, path):
        with path.open('rb'):
            entered.set()
            assert proceed.wait(2)

    monkeypatch.setattr(module, 'run_tool', fake)
    monkeypatch.setattr(AudioProcessor, 'check_wav', inspect)

    async def check():
        task = asyncio.create_task(AudioProcessor(settings).prepare(source))
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        proceed.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not source.with_suffix('.wav').exists()

    asyncio.run(asyncio.wait_for(check(), 5))
