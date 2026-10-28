import hashlib
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

from package import FILES, package


class PackageTest(unittest.TestCase):
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
