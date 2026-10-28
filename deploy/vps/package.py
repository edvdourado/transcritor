"""Build a source-only snapshot locally. Never connects to a server."""
import argparse
import gzip
import hashlib
import io
import tarfile
from pathlib import Path


FILES = (
    '.env.example', '.gitignore', 'README.md', 'backend/pyproject.toml',
    'docs/DEPLOY.md', 'docs/PUBLICACAO.md', 'docs/TESTE_V11_ORACLE.md',
    'frontend/package.json', 'frontend/package-lock.json', 'frontend/index.html',
    'frontend/vite.config.ts', 'frontend/vite.review.config.ts', 'frontend/tsconfig.json',
    'frontend/tsconfig.app.json', 'frontend/tsconfig.node.json',
    'deploy/vps/README.md', 'deploy/vps/.env.vps.example',
    'deploy/vps/transcritor.service', 'deploy/vps/nginx.conf.example',
    'deploy/vps/requirements-py310-arm64.txt',
    'deploy/vps/package.py', 'deploy/vps/test_package.py', 'deploy/vps/review.py',
)
PATTERNS = ('backend/app/*.py', 'backend/test_*.py',
            'frontend/src/**/*.ts', 'frontend/src/**/*.tsx', 'frontend/src/**/*.css')


def package(root: Path, output: Path):
    root = root.resolve()
    checksum = output.with_name(output.name + '.sha256')
    if output.exists() or checksum.exists():
        raise FileExistsError(f'Choose a new artifact path: {output}')
    paths = {root / name for name in FILES}
    for pattern in PATTERNS:
        paths.update(root.glob(pattern))
    # Check every ancestor too: a directory symlink could otherwise import secrets.
    for path in paths:
        if (not path.is_file() or not path.resolve().is_relative_to(root)
                or any(p.is_symlink() for p in (path, *path.parents) if p != root)):
            raise ValueError(f'Not a regular source file: {path}')
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    # Exclusive creation preserves any earlier artifact. Stable metadata makes
    # repeated snapshots of the same bytes identical, independent of Windows mtimes.
    with output.open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for path in sorted(paths):
                name = path.relative_to(root).as_posix()
                data = path.read_bytes()
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), 0o600
                archive.addfile(info, io.BytesIO(data))
                manifest.append(f'{hashlib.sha256(data).hexdigest()}  {name}\n')
            data = ''.join(manifest).encode('utf-8')
            info = tarfile.TarInfo('MANIFEST.sha256')
            info.size, info.mode = len(data), 0o600
            archive.addfile(info, io.BytesIO(data))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    with checksum.open('x', encoding='ascii', newline='\n') as check:
        check.write(f'{digest}  {output.name}\n')
    return digest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New .tar.gz path; never overwritten')
    args = parser.parse_args()
    print(package(Path(__file__).resolve().parents[2], args.output))
    print(args.output.resolve())
