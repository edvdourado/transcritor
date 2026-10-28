import asyncio
import json
import os
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.audio import AudioProcessor
from app.config import settings
from app.jobs import Jobs
from app.main import create_app
from app.transcriber import MockTranscriber, TranscriptionError, WhisperTranscriber, read_transcription


SEGMENTS = [
    {'text': ' Olá, ação.', 'offsets': {'from': 0, 'to': 1230},
     'timestamps': {'from': '00:00:00,000', 'to': '00:00:01,230'}},
    {'text': '\nSem correções.  ', 'offsets': {'from': 1230, 'to': 2500}},
]
TEXT = ''.join(segment['text'] for segment in SEGMENTS)


@pytest.fixture
def cli(tmp_path, monkeypatch):
    # Python is a portable simulated executable: Windows cannot exec a .py file
    # directly. Only the test launcher inserts the script before the real CLI argv.
    script = tmp_path / 'simulated cli.py'
    script.write_text('''import json, os, pathlib, sys, time
args = sys.argv[1:]
model = pathlib.Path(args[args.index('-m') + 1])
mode = model.read_text()
output = pathlib.Path(args[args.index('-of') + 1] + '.json')
output.write_text('partial')
(output.parent / 'started').write_text(str(os.getpid()))
print('INTERNAL LOG /secret/model ' * 10000, flush=True)
if mode == 'wait':
    time.sleep(60)
if mode == 'exit':
    sys.exit(7)
elif mode == 'invalid':
    output.write_text('invalid json')
elif mode == 'schema':
    output.write_text('{"transcription": [{"text": 42}]}')
elif mode == 'missing':
    output.unlink()
else:
    output.write_text(json.dumps({'transcription': SEGMENTS, 'params': {'model': '/secret/model'}}), encoding='utf-8')
'''.replace('SEGMENTS', repr(SEGMENTS)), encoding='utf-8')
    small = tmp_path / 'small model & safe.bin'
    medium = tmp_path / 'medium model ; safe.bin'
    small.write_text('success')
    medium.write_text('success')
    source = tmp_path / 'prepared input & safe.wav'
    source.write_bytes(b'prepared WAV')
    config = replace(settings, engine='whisper', whisper_cli_path=sys.executable,
                     whisper_model_small=str(small), whisper_model_medium=str(medium),
                     whisper_timeout_seconds=10, temp_dir=tmp_path / 'sessions')
    spawn = asyncio.create_subprocess_exec
    calls, processes = [], []

    async def launch(executable, *args, **kwargs):
        calls.append((executable, args, kwargs))
        process = await spawn(executable, '-u', str(script), *args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', launch)
    return config, source, calls, processes


def assert_clean(source, processes):
    assert not list(source.parent.glob('whisper-*'))
    assert all(process.returncode is not None for process in processes)
    assert source.exists()


@pytest.mark.parametrize('model', ['small', 'medium'])
def test_execution_arguments_and_verbatim_output(cli, model):
    config, source, calls, processes = cli
    result = asyncio.run(WhisperTranscriber(config).transcribe(source, model))
    assert result.text == TEXT
    assert result.segments == SEGMENTS
    executable, args, options = calls[0]
    expected = config.whisper_model_small if model == 'small' else config.whisper_model_medium
    assert executable == sys.executable
    assert args[:-1] == ('-m', str(Path(expected).resolve()), '-f', str(source.resolve()),
                         '-l', 'pt', '-t', '3', '-ng', '-oj', '-of')
    assert Path(args[-1]).parent.parent == source.parent
    assert options['stdin'] == options['stdout'] == options['stderr'] == subprocess.DEVNULL
    assert not options.get('shell')
    assert_clean(source, processes)


def test_configurable_language_threads_and_unique_output(cli):
    config, source, calls, processes = cli

    async def check():
        transcriber = WhisperTranscriber(replace(config, whisper_language='en', whisper_threads=2))
        await transcriber.transcribe(source, 'small')
        await transcriber.transcribe(source, 'medium')

    asyncio.run(check())
    assert calls[0][1][-1] != calls[1][1][-1]
    assert calls[0][1][5:8] == ('en', '-t', '2')
    assert_clean(source, processes)


@pytest.mark.parametrize('model', ['small', 'medium', 'large'])
def test_missing_model(cli, model):
    config, source, calls, processes = cli
    Path(config.whisper_model_small).unlink()
    Path(config.whisper_model_medium).unlink()
    with pytest.raises(TranscriptionError, match='Modelo'):
        asyncio.run(WhisperTranscriber(config).transcribe(source, model))
    assert calls == []
    assert_clean(source, processes)


@pytest.mark.parametrize('unavailable', ['missing', 'cannot-start', 'batch'])
def test_unavailable_executable(cli, monkeypatch, unavailable):
    config, source, calls, processes = cli
    if unavailable == 'missing':
        config = replace(config, whisper_cli_path=str(source.parent / 'missing.exe'))
    elif unavailable == 'batch':
        from app import audio
        monkeypatch.setattr(audio.shutil, 'which', lambda executable: 'resolved.cmd')
    else:
        monkeypatch.setattr(asyncio, 'create_subprocess_exec', AsyncMock(side_effect=OSError('/secret/path')))
    with pytest.raises(TranscriptionError) as caught:
        asyncio.run(WhisperTranscriber(config).transcribe(source, 'small'))
    assert 'secret' not in str(caught.value)
    assert_clean(source, processes)


@pytest.mark.parametrize('mode', ['exit', 'invalid', 'schema', 'missing', 'wait'])
def test_failed_execution_and_timeout_cleanup(cli, mode):
    config, source, calls, processes = cli
    Path(config.whisper_model_small).write_text(mode)
    if mode == 'wait':
        config = replace(config, whisper_timeout_seconds=0.5)
    with pytest.raises(TranscriptionError):
        asyncio.run(WhisperTranscriber(config).transcribe(source, 'small'))
    assert len(processes) == 1
    assert_clean(source, processes)


async def wait_started(source):
    while not list(source.parent.glob('whisper-*/started')):
        await asyncio.sleep(0.01)


def test_cancel_running_process(cli):
    config, source, calls, processes = cli
    Path(config.whisper_model_small).write_text('wait')

    async def check():
        task = asyncio.create_task(WhisperTranscriber(config).transcribe(source, 'small'))
        await wait_started(source)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[0].returncode != 0

    asyncio.run(asyncio.wait_for(check(), 5))
    assert_clean(source, processes)


def test_cancel_while_spawning(cli, monkeypatch):
    config, source, calls, processes = cli
    launch = asyncio.create_subprocess_exec

    async def check():
        entered, proceed = asyncio.Event(), asyncio.Event()

        async def delayed(*args, **kwargs):
            entered.set()
            await proceed.wait()
            return await launch(*args, **kwargs)

        monkeypatch.setattr(asyncio, 'create_subprocess_exec', delayed)
        task = asyncio.create_task(WhisperTranscriber(config).transcribe(source, 'small'))
        await entered.wait()
        task.cancel()
        proceed.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(asyncio.wait_for(check(), 5))
    assert len(processes) == 1
    assert_clean(source, processes)


@pytest.mark.parametrize('data', [
    [], {}, {'transcription': None}, {'transcription': 'text'},
    {'transcription': [None]}, {'transcription': [{}]},
    {'transcription': [{'text': 123}]},
    {'transcription': [{'text': '\ud800'}]},
    {'transcription': [{'text': 'a', 'offsets': {'from': -1, 'to': 2}}]},
    {'transcription': [{'text': 'a', 'offsets': {'from': 3, 'to': 2}}]},
    {'transcription': [{'text': 'a', 'offsets': {'from': True, 'to': 2}}]},
    {'transcription': [{'text': 'a', 'offsets': {'from': 0, 'to': float('nan')}}]},
    {'transcription': [{'text': 'a', 'timestamps': {'from': 'bad', 'to': 'bad'}}]},
    {'transcription': [{'text': 'a', 'timestamps': None}]},
])
def test_invalid_json_structure(tmp_path, data):
    path = tmp_path / 'output.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(TranscriptionError):
        read_transcription(path)


def test_empty_segments_and_output_limit(tmp_path):
    path = tmp_path / 'output.json'
    path.write_text('{"transcription": []}')
    assert read_transcription(path).text == ''
    path.write_bytes(b' ' * (8 * 1024 * 1024 + 1))
    with pytest.raises(TranscriptionError):
        read_transcription(path)


@pytest.mark.parametrize('finish', ['success', 'exit', 'timeout', 'cancel'])
def test_queue_keeps_one_active_and_advances(cli, monkeypatch, finish):
    config, source, calls, processes = cli
    Path(config.whisper_model_small).write_text('wait' if finish in ('timeout', 'cancel') else finish)
    if finish == 'timeout':
        config = replace(config, whisper_timeout_seconds=0.5)

    async def check():
        manager = Jobs(WhisperTranscriber(config), 3600)
        assert await manager.reserve()
        first = await manager.submit(source, 'small')
        first_task = manager.items[first.id].task
        second_input = source.with_name('second.wav')
        second_input.write_bytes(b'prepared WAV')
        assert await manager.reserve()
        second = await manager.submit(second_input, 'medium')
        assert second.state == 'queued'
        assert not await manager.reserve()
        if finish == 'cancel':
            await wait_started(source)
            await manager.delete(first.id)
        else:
            await first_task
            result = await manager.get(first.id)
            assert result.state == ('completed' if finish == 'success' else 'failed')
            assert 0 <= result.processing_seconds <= result.total_seconds
        if finish == 'cancel':
            assert await manager.get(first.id) is None
        await manager.items[second.id].task
        assert (await manager.get(second.id)).transcript == TEXT
        assert manager.items[second.id].segments == SEGMENTS
        assert manager.active is None
        await manager.close()
        assert not second_input.exists()

    # Assert in the spawn wrapper that the previous process was reaped first.
    launch = asyncio.create_subprocess_exec

    async def serial(*args, **kwargs):
        assert all(process.returncode is not None for process in processes)
        return await launch(*args, **kwargs)

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', serial)
    asyncio.run(asyncio.wait_for(check(), 8))
    assert not list(source.parent.glob('whisper-*'))
    assert all(process.returncode is not None for process in processes)
    assert len(processes) == 2
    assert len({call[1][-1] for call in calls}) == 2


@pytest.mark.parametrize('engine', ['mock', 'whisper'])
def test_api_compatibility_and_actual_engine(cli, monkeypatch, engine):
    config, source, calls, processes = cli
    config = replace(config, engine=engine, mock_processing_seconds=0)
    monkeypatch.setattr(AudioProcessor, 'validate', AsyncMock(return_value=0.1))

    async def prepare(self, path):
        target = path.with_suffix('.wav')
        target.write_bytes(b'prepared WAV')
        return target

    monkeypatch.setattr(AudioProcessor, 'prepare', prepare)
    with TestClient(create_app(config)) as client:
        capabilities = client.get('/api/v1/capabilities')
        assert capabilities.json() == {'engine': engine}
        assert capabilities.headers['cache-control'] == 'no-store'
        assert client.get('/api/v1/health').json() == {'status': 'ok'}
        created = client.post('/api/v1/jobs', data={'model': 'medium'}, files={'file': ('audio.wav', b'audio')})
        assert created.status_code == 202
        job = created.json()
        assert set(job) == {'id', 'model', 'state', 'transcript', 'error', 'engine',
                            'total_seconds', 'processing_seconds', 'audio_duration_seconds'}
        assert job['engine'] == engine

        async def finish():
            await client.app.state.jobs.items[UUID(job['id'])].task

        client.portal.call(finish)
        result = client.get('/api/v1/jobs/' + job['id']).json()
        assert result['state'] == 'completed'
        assert result['engine'] == engine
        assert 0 <= result['processing_seconds'] <= result['total_seconds']
        assert result['audio_duration_seconds'] == 0.1
        assert result['transcript'] == TEXT if engine == 'whisper' else 'TESTE MOCK' in result['transcript']
        if engine == 'whisper':
            assert Path(calls[0][1][3]).suffix == '.wav'
            assert client.app.state.jobs.items[UUID(job['id'])].segments == SEGMENTS
        assert 'secret' not in json.dumps(result)
        assert client.delete('/api/v1/jobs/' + job['id']).status_code == 204
        assert list(client.app.state.directory.iterdir()) == []
    assert list(config.temp_dir.iterdir()) == []


def test_capabilities_describe_injected_transcriber(cli):
    config, *_ = cli
    with TestClient(create_app(config, transcriber=MockTranscriber(0))) as client:
        assert client.get('/api/v1/capabilities').json() == {'engine': 'mock'}


@pytest.mark.parametrize('values', [
    {'engine': 'unknown'}, {'whisper_threads': 0}, {'whisper_threads': -1},
    {'whisper_timeout_seconds': 0}, {'whisper_timeout_seconds': float('inf')},
    {'whisper_timeout_seconds': float('nan')}, {'whisper_language': '-m injected'},
])
def test_invalid_configuration_fails_startup(tmp_path, values):
    with pytest.raises(ValueError):
        with TestClient(create_app(replace(settings, temp_dir=tmp_path, **values))):
            pass


def test_environment_configuration():
    env = dict(os.environ, TRANSCRITOR_ENGINE='whisper', WHISPER_CLI_PATH='cli',
               WHISPER_MODEL_SMALL='small.bin', WHISPER_MODEL_MEDIUM='medium.bin',
               WHISPER_THREADS='2', WHISPER_LANGUAGE='en', WHISPER_TIMEOUT_SECONDS='9000')
    result = subprocess.run([sys.executable, '-c',
                             'from app.config import settings; import json; '
                             'print(json.dumps([settings.engine, settings.whisper_cli_path, '
                             'settings.whisper_model_small, settings.whisper_model_medium, '
                             'settings.whisper_threads, settings.whisper_language, settings.whisper_timeout_seconds]))'],
                            env=env, capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(result.stdout) == ['whisper', 'cli', 'small.bin', 'medium.bin', 2, 'en', 9000]


def test_repeated_cancellation_still_waits_for_process(cli, monkeypatch):
    config, source, calls, processes = cli
    Path(config.whisper_model_small).write_text('wait')

    async def check():
        task = asyncio.create_task(WhisperTranscriber(config).transcribe(source, 'small'))
        await wait_started(source)
        process = processes[0]
        original_wait = process.wait
        reaping, proceed = asyncio.Event(), asyncio.Event()

        async def delayed_wait():
            reaping.set()
            await proceed.wait()
            return await original_wait()

        monkeypatch.setattr(process, 'wait', delayed_wait)
        task.cancel()
        await reaping.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert list(source.parent.glob('whisper-*'))
        proceed.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(asyncio.wait_for(check(), 5))
    assert_clean(source, processes)


@pytest.mark.parametrize('invalid', [False, True])
def test_cancel_during_json_read_waits_before_cleanup(cli, monkeypatch, invalid):
    from app import transcriber as module

    config, source, calls, processes = cli
    entered, proceed = threading.Event(), threading.Event()
    read = module.read_transcription

    def delayed_read(path):
        with path.open('rb'):
            entered.set()
            assert proceed.wait(5)
        if invalid:
            raise TranscriptionError('invalid output during cancellation')
        return read(path)

    monkeypatch.setattr(module, 'read_transcription', delayed_read)

    async def check():
        task = asyncio.create_task(WhisperTranscriber(config).transcribe(source, 'small'))
        try:
            while not entered.is_set():
                await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert list(source.parent.glob('whisper-*/result.json'))
        finally:
            proceed.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(asyncio.wait_for(check(), 5))
    assert_clean(source, processes)


def test_whisper_failure_api_is_safe_and_next_job_finishes(cli, monkeypatch):
    config, source, calls, processes = cli
    Path(config.whisper_model_small).write_text('exit')
    monkeypatch.setattr(AudioProcessor, 'validate', AsyncMock())

    async def prepare(self, path):
        return path

    monkeypatch.setattr(AudioProcessor, 'prepare', prepare)
    with TestClient(create_app(config)) as client:
        def post(model):
            return client.post('/api/v1/jobs', data={'model': model}, files={'file': ('audio.wav', b'audio')}).json()

        first, second = post('small'), post('medium')

        async def finish():
            await client.app.state.jobs.items[UUID(first['id'])].task
            await client.app.state.jobs.items[UUID(second['id'])].task

        client.portal.call(finish)
        failed = client.get('/api/v1/jobs/' + first['id']).json()
        assert failed['state'] == 'failed' and failed['transcript'] is None
        assert failed['engine'] == 'whisper'
        assert failed['error'] == 'Não foi possível processar o áudio. Tente novamente.'
        assert str(source.parent) not in json.dumps(failed)
        assert 'INTERNAL LOG' not in json.dumps(failed)
        assert client.get('/api/v1/jobs/' + second['id']).json()['transcript'] == TEXT
        assert not list(client.app.state.directory.glob('whisper-*'))


def test_shutdown_cancels_whisper_without_starting_waiting_job(cli):
    config, source, calls, processes = cli
    Path(config.whisper_model_small).write_text('wait')

    async def check():
        manager = Jobs(WhisperTranscriber(config), 3600)
        assert await manager.reserve()
        await manager.submit(source, 'small')
        await wait_started(source)
        second = source.with_name('queued.wav')
        second.write_bytes(b'WAV')
        assert await manager.reserve()
        await manager.submit(second, 'medium')
        await manager.close()
        assert manager.items == {}
        assert not second.exists()
        assert len(processes) == 1 and processes[0].returncode is not None
        assert not list(source.parent.glob('whisper-*'))

    asyncio.run(asyncio.wait_for(check(), 5))
