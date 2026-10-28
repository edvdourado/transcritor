import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from package import FILES, package


class PackageTest(unittest.TestCase):
    def test_review_checks_snapshot_imports_and_refuses_production_port(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'snapshot' / 'app'
            source = Path(__file__).resolve().parents[2]
            shutil.copytree(source / 'backend/app', root / 'backend/app',
                            ignore=shutil.ignore_patterns('__pycache__'))
            script = root / 'deploy/vps/review.py'
            script.parent.mkdir(parents=True)
            shutil.copyfile(source / 'deploy/vps/review.py', script)
            runtime = root.parent / 'run/tmp'
            runtime.mkdir(parents=True)
            model = root.parent / 'existing-model.bin'
            model.write_bytes(b'not a real model: --check never loads it')
            poison = Path(directory) / 'production'
            (poison / 'app').mkdir(parents=True)
            (poison / 'app/__init__.py').write_text("raise RuntimeError('Production imported')")
            env = dict(os.environ, PYTHONPATH=str(poison), TRANSCRITOR_ENGINE='whisper',
                       TRANSCRITOR_HOST='127.0.0.1', TRANSCRITOR_PORT='8766',
                       TRANSCRITOR_TEMP_DIR=str(runtime), WHISPER_CLI_PATH=sys.executable,
                       FFMPEG_PATH=sys.executable, FFPROBE_PATH=sys.executable,
                       WHISPER_MODEL_SMALL=str(model), WHISPER_MODEL_MEDIUM=str(model))
            command = [sys.executable, '-I', '-B', str(script), '--check']
            result = subprocess.run(command, cwd=poison, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f'IMPORT app.main: {root / "backend/app/main.py"}', result.stdout)
            self.assertIn(f'tmp={runtime}', result.stdout)
            env['TRANSCRITOR_PORT'] = '8765'
            result = subprocess.run(command, cwd=poison, env=env, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Expected Whisper on 127.0.0.1:8766', result.stderr)

    def test_snapshot_exclusions_integrity_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            included = (*FILES, 'backend/app/main.py', 'backend/test_health.py',
                        'frontend/src/App.tsx', 'frontend/src/components/Icon.tsx')
            excluded = ('.env', '.env.production', 'credentials.json', '.git/config',
                        'backend/.env', 'backend/app/__pycache__/main.pyc',
                        '.venv/secret.py', 'tmp/result.json', 'tmp/python/runtime.py',
                        'backend/.pytest_cache/cache', 'backend/app/result.json',
                        'frontend/node_modules/dep/index.ts', 'frontend/dist/app.js',
                        'frontend/src/.env.local', 'frontend/src/transcription.txt')
            for name in (*included, *excluded):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name, encoding='utf-8')
            first, second = Path(directory) / 'first.tar.gz', Path(directory) / 'second.tar.gz'
            package(root, first)
            for name in included:
                os.utime(root / name, (1234, 5678))
            package(root, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with tarfile.open(first) as archive:
                self.assertEqual(set(archive.getnames()), set(included) | {'MANIFEST.sha256'})
                for line in archive.extractfile('MANIFEST.sha256').read().decode().splitlines():
                    digest, name = line.split('  ', 1)
                    self.assertEqual(digest, hashlib.sha256(archive.extractfile(name).read()).hexdigest())
                self.assertTrue(all(member.isfile() and member.mode == 0o600 for member in archive))
            self.assertTrue(first.with_name(first.name + '.sha256').read_text().startswith(
                hashlib.sha256(first.read_bytes()).hexdigest()))
            with self.assertRaises(FileExistsError):
                package(root, first)
            (root / FILES[0]).unlink()
            with self.assertRaises(ValueError):
                package(root, Path(directory) / 'missing.tar.gz')

    def test_reject_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            for name in FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'source')
            external = Path(directory) / 'secret'
            external.write_bytes(b'secret')
            link = root / 'backend/app'
            try:
                link.symlink_to(external.parent, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f'Symlinks unavailable: {exc}')
            # Ensure the pattern matches a file through the symlinked directory.
            (external.parent / 'secret.py').write_bytes(b'secret')
            with self.assertRaises(ValueError):
                package(root, Path(directory) / 'unsafe.tar.gz')


if __name__ == '__main__':
    unittest.main()
