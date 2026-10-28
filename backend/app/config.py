import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("TRANSCRITOR_HOST", "127.0.0.1")
    port: int = int(os.getenv("TRANSCRITOR_PORT", "8765"))
    engine: str = os.getenv("TRANSCRITOR_ENGINE", "mock")
    whisper_cli_path: str = os.getenv("WHISPER_CLI_PATH", "")
    whisper_model_small: str = os.getenv("WHISPER_MODEL_SMALL", "")
    whisper_model_medium: str = os.getenv("WHISPER_MODEL_MEDIUM", "")
    whisper_threads: int = int(os.getenv("WHISPER_THREADS", "3"))
    whisper_language: str = os.getenv("WHISPER_LANGUAGE", "pt")
    whisper_timeout_seconds: float = float(os.getenv("WHISPER_TIMEOUT_SECONDS", "7200"))
    ffmpeg_path: str = os.getenv("FFMPEG_PATH", "ffmpeg")
    ffprobe_path: str = os.getenv("FFPROBE_PATH", "ffprobe")
    temp_dir: Path = Path(os.getenv("TRANSCRITOR_TEMP_DIR", "./tmp"))
    max_upload_size_mb: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
    max_audio_duration_seconds: int = int(os.getenv("MAX_AUDIO_DURATION_SECONDS", "1800"))
    ffprobe_timeout_seconds: float = float(os.getenv("FFPROBE_TIMEOUT_SECONDS", "15"))
    ffmpeg_timeout_seconds: float = float(os.getenv("FFMPEG_TIMEOUT_SECONDS", "120"))
    upload_timeout_seconds: float = float(os.getenv("UPLOAD_TIMEOUT_SECONDS", "120"))
    file_retention_seconds: int = int(os.getenv("FILE_RETENTION_SECONDS", "3600"))
    mock_processing_seconds: float = float(os.getenv("MOCK_PROCESSING_SECONDS", "2"))


settings = Settings()
