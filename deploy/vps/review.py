"""Run the transferred v1.1 backend with existing dependencies; no installation."""
import os
from pathlib import Path
import sys


def main():
    # -I ignores PYTHONPATH/user site; explicitly prefer this snapshot over any
    # production editable install in the interpreter's site-packages.
    root = Path(__file__).resolve().parents[2]
    backend = root / 'backend'
    runtime = root.parent / 'run' / 'tmp'
    production = Path('/data/transcritor/app').resolve()
    if root.is_relative_to(production) or runtime.is_relative_to(production):
        raise RuntimeError('Test source/runtime must be separate from production')
    if 'app' in sys.modules or (root / '.env').exists():
        raise RuntimeError('Unexpected preloaded app or snapshot .env')
    sys.path.insert(0, str(backend))

    from app import config, jobs, main as application

    for name, module in list(sys.modules.items()):
        if name == 'app' or name.startswith('app.'):
            source = Path(module.__file__).resolve()
            if not source.is_relative_to(backend / 'app'):
                raise RuntimeError(f'Wrong import: {name}: {source}')
            print(f'IMPORT {name}: {source}', flush=True)
    if 'segments' not in jobs.JobResponse.model_fields:
        raise RuntimeError('Missing v1.1 response contract')

    settings = config.settings
    if (settings.host, settings.port, settings.engine) != ('127.0.0.1', 8766, 'whisper'):
        raise RuntimeError('Expected Whisper on 127.0.0.1:8766')
    if settings.temp_dir.resolve() != runtime or not runtime.is_dir():
        raise RuntimeError(f'Expected private temporary directory: {runtime}')
    for executable in (settings.whisper_cli_path, settings.ffmpeg_path, settings.ffprobe_path):
        if not Path(executable).is_absolute() or not os.access(executable, os.X_OK):
            raise RuntimeError(f'Executable unavailable: {executable}')
    for model in (settings.whisper_model_small, settings.whisper_model_medium):
        if not Path(model).is_absolute() or not Path(model).is_file() or not os.access(model, os.R_OK):
            raise RuntimeError(f'Existing model unreadable: {model}')
    print(f'REVIEW pid={os.getpid()} root={root} tmp={runtime}', flush=True)
    if sys.argv[1:] == ['--check']:
        return
    if sys.argv[1:]:
        raise RuntimeError('Only --check is supported')
    import uvicorn
    uvicorn.run(application.app, host='127.0.0.1', port=8766, workers=1)


if __name__ == '__main__':
    main()
