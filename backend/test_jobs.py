import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import settings
from app.jobs import JobResponse, Jobs
from app.main import create_app
from app.audio import AudioProcessor


@pytest.fixture(autouse=True)
def mock_audio_tools(monkeypatch):
    # Stage 2 contract tests isolate scheduling from Stage 3's external tools.
    async def validate(self, path):
        pass

    async def prepare(self, path):
        return path

    monkeypatch.setattr(AudioProcessor, 'validate', validate)
    monkeypatch.setattr(AudioProcessor, 'prepare', prepare)


@pytest.fixture
def client(tmp_path):
    config = replace(settings, temp_dir=tmp_path, max_upload_size_mb=1, mock_processing_seconds=3600)
    with TestClient(create_app(config)) as connection:
        yield connection
    assert list(tmp_path.iterdir()) == []


def post(client, name='voice.ogg', model='small', content=b'audio'):
    return client.post('/api/v1/jobs', data={'model': model}, files={'file': (name, content)})


def test_create_and_query(client):
    response = post(client)
    assert response.status_code == 202
    job = response.json()
    assert job['state'] == 'processing'
    assert job['model'] == 'small'
    assert job['segments'] == []
    queried = client.get('/api/v1/jobs/' + job['id']).json()
    assert queried.pop('total_seconds') >= job.pop('total_seconds') >= 0
    assert queried.pop('processing_seconds') is not None
    job.pop('processing_seconds')
    assert queried == job


@pytest.mark.parametrize('name,model,content,status', [
    ('a.wav', 'large', b'a', 422), ('a.exe', 'small', b'a', 422),
    ('a.mp3', 'small', b'a' * (1024 * 1024 + 1), 413), ('a.wav', 'small', b'', 422),
], ids=['model', 'extension', 'size', 'empty'])
def test_invalid_upload(client, name, model, content, status):
    assert post(client, name, model, content).status_code == status
    assert list(client.app.state.directory.iterdir()) == []
    assert client.app.state.jobs.reservations == 0


def test_capacity_and_cancel_waiting(client):
    first = post(client).json()
    second = post(client, 'voice.M4A', 'medium').json()
    assert second['state'] == 'queued'
    assert post(client).status_code == 429
    assert client.delete('/api/v1/jobs/' + second['id']).status_code == 204
    assert client.get('/api/v1/jobs/' + first['id']).json()['state'] == 'processing'
    assert len(list(client.app.state.directory.iterdir())) == 1
    assert post(client).status_code == 202


def test_cancel_processing(client):
    first = post(client).json()
    second = post(client).json()
    assert client.delete('/api/v1/jobs/' + first['id']).status_code == 204
    assert client.get('/api/v1/jobs/' + first['id']).status_code == 404
    assert client.get('/api/v1/jobs/' + second['id']).json()['state'] == 'processing'
    assert len(list(client.app.state.directory.iterdir())) == 1


def test_not_found(client):
    url = '/api/v1/jobs/' + str(uuid4())
    assert client.get(url).status_code == 404
    assert client.delete(url).status_code == 404


class ControlledTranscriber:
    def __init__(self, fail=False):
        self.started = asyncio.Queue()
        self.proceed = asyncio.Queue()
        self.fail = fail
        self.running = 0
        self.maximum = 0
        self.cancelled = False

    async def transcribe(self, path, model):
        self.running += 1
        self.maximum = max(self.maximum, self.running)
        await self.started.put(path)
        try:
            await self.proceed.get()
            if self.fail:
                raise RuntimeError('secret internal path')
            return '[TESTE MOCK] resultado'
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.running -= 1


async def add(manager, path):
    path.write_bytes(b'audio')
    assert await manager.reserve()
    return await manager.submit(path, 'small')


def test_sequential_transitions_and_retention(tmp_path):
    async def check():
        transcriber = ControlledTranscriber()
        now = [0]
        manager = Jobs(transcriber, 3600, clock=lambda: now[0])
        first = await add(manager, tmp_path / 'a')
        await transcriber.started.get()
        second = await add(manager, tmp_path / 'b')
        assert second.state == 'queued'
        assert not await manager.reserve()
        task = manager.items[first.id].task
        await transcriber.proceed.put(None)
        await task
        assert (await manager.get(first.id)).state == 'completed'
        assert '[TESTE MOCK]' in (await manager.get(first.id)).transcript
        await transcriber.started.get()
        assert (await manager.get(second.id)).state == 'processing'
        task = manager.items[second.id].task
        await transcriber.proceed.put(None)
        await task
        assert transcriber.maximum == 1
        now[0] = 3599
        await manager.expire()
        assert len(manager.items) == 2
        now[0] = 3600
        await manager.expire()
        assert manager.items == {}
        assert list(tmp_path.iterdir()) == []
    asyncio.run(asyncio.wait_for(check(), 5))


def test_failure_safe_error_and_cleanup(tmp_path):
    async def check():
        transcriber = ControlledTranscriber(fail=True)
        manager = Jobs(transcriber, 3600)
        job = await add(manager, tmp_path / 'a')
        await transcriber.started.get()
        task = manager.items[job.id].task
        await transcriber.proceed.put(None)
        await task
        result = await manager.get(job.id)
        assert result.state == 'failed'
        assert 'secret' not in result.error
        await manager.delete(job.id)
        assert not (tmp_path / 'a').exists()
    asyncio.run(asyncio.wait_for(check(), 5))


def test_cancellation_waits_for_transcriber(tmp_path):
    async def check():
        transcriber = ControlledTranscriber()
        manager = Jobs(transcriber, 3600)
        job = await add(manager, tmp_path / 'a')
        await transcriber.started.get()
        await manager.delete(job.id)
        assert transcriber.cancelled
        assert transcriber.running == 0
        assert manager.active is None
        assert not (tmp_path / 'a').exists()
    asyncio.run(asyncio.wait_for(check(), 5))


def test_cancel_before_task_starts(tmp_path):
    async def check():
        manager = Jobs(ControlledTranscriber(), 3600)
        job = await add(manager, tmp_path / 'a')
        await manager.delete(job.id)
        assert manager.active is None
        assert manager.items == {}
    asyncio.run(asyncio.wait_for(check(), 5))


def test_concurrent_admission():
    async def check():
        manager = Jobs(ControlledTranscriber(), 3600)
        results = await asyncio.gather(*(manager.reserve() for _ in range(10)))
        assert sum(results) == 2
    asyncio.run(check())

def test_actual_mock_completion(tmp_path):
    config = replace(settings, temp_dir=tmp_path, mock_processing_seconds=0)
    with TestClient(create_app(config)) as client:
        response = post(client, model='medium')
        assert response.status_code == 202
        job_id = response.json()['id']

        async def wait_finished():
            from uuid import UUID
            await client.app.state.jobs.items[UUID(job_id)].task

        client.portal.call(wait_finished)
        result = client.get('/api/v1/jobs/' + job_id).json()
        assert result['state'] == 'completed'
        assert 'TESTE MOCK' in result['transcript']
        assert 'medium' in result['transcript']
        assert result['segments'] == []
        assert client.delete('/api/v1/jobs/' + job_id).status_code == 204
        assert list(client.app.state.directory.iterdir()) == []


@pytest.mark.parametrize('segment', [
    {'text': '', 'start': 0, 'end': 1}, {'text': ' \n', 'start': 0, 'end': 1},
    {'text': 42, 'start': 0, 'end': 1}, {'text': 'a', 'start': -1, 'end': 1},
    {'text': 'a', 'start': 1, 'end': 1}, {'text': 'a', 'start': 2, 'end': 1},
    {'text': 'a', 'start': False, 'end': 1}, {'text': 'a', 'start': '0', 'end': 1},
    {'text': 'a', 'start': 0, 'end': float('inf')}, {'text': 'a', 'start': float('nan'), 'end': 1},
    {'text': 'a', 'start': 0},
])
def test_segment_response_contract_validates_creation_and_assignment(segment):
    values = dict(id=uuid4(), model='small', state='completed', transcript='Texto')
    with pytest.raises(ValidationError):
        JobResponse(**values, segments=[segment])
    response = JobResponse(**values)
    assert response.segments == []
    with pytest.raises(ValidationError):
        response.segments = [segment]
    response.segments = [{'text': ' Texto ', 'start': 0, 'end': 1.25}]
    assert response.model_dump(mode='json')['segments'] == [{'text': ' Texto ', 'start': 0.0, 'end': 1.25}]


@pytest.mark.parametrize('failure', [None, RuntimeError, TimeoutError])
@pytest.mark.parametrize('model', ['small', 'medium'])
def test_monotonic_metrics_include_preparation_and_queue(tmp_path, failure, model):
    async def check():
        now = [100.0]
        transcriber = ControlledTranscriber()

        class Audio:
            async def prepare(self, path):
                now[0] += 3
                if failure:
                    raise failure('preparation stopped')
                return path

        manager = Jobs(transcriber, 3600, clock=lambda: now[0], audio=Audio())
        first = await add(manager, tmp_path / 'a')
        path = tmp_path / 'b'
        path.write_bytes(b'audio')
        assert await manager.reserve()
        second = await manager.submit(path, model, 61.5)
        assert second.processing_seconds is None
        assert second.total_seconds == 0
        now[0] = 110
        first_task = manager.items[first.id].task
        if not failure:
            await transcriber.started.get()
            now[0] = 120
            await transcriber.proceed.put(None)
        await first_task
        second_task = manager.items[second.id].task
        if not failure:
            await transcriber.started.get()
            live = await manager.get(second.id)
            assert live.processing_seconds == 3
            assert live.total_seconds == 23
            now[0] = 130
            await transcriber.proceed.put(None)
        await second_task
        result = await manager.get(second.id)
        assert result.audio_duration_seconds == 61.5
        assert result.model == model
        assert result.state == ('failed' if failure else 'completed')
        assert result.processing_seconds == (3 if failure else 10)
        assert result.total_seconds == (16 if failure else 30)
        now[0] += 100
        assert await manager.get(second.id) == result
        await manager.close()
    asyncio.run(asyncio.wait_for(check(), 5))
