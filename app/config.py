from dataclasses import dataclass
import os
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text().splitlines():
        clean_line = line.strip()
        if not clean_line or clean_line.startswith("#") or "=" not in clean_line:
            continue

        key, value = clean_line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    dgx_flux_api_url: str = os.getenv("DGX_FLUX_API_URL", "http://100.104.174.12:8001").rstrip("/")
    cors_origins: list[str] = None
    dgx_start_timeout: float = float(os.getenv("DGX_START_TIMEOUT", "20"))
    dgx_request_timeout: float = float(os.getenv("DGX_REQUEST_TIMEOUT", "260"))
    dgx_poll_interval: float = float(os.getenv("DGX_POLL_INTERVAL", "2"))
    dgx_poll_timeout: float = float(os.getenv("DGX_POLL_TIMEOUT", "240"))

    def __post_init__(self):
        if self.cors_origins is None:
            origins = os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            )
            object.__setattr__(self, "cors_origins", _split_csv(origins))


settings = Settings()
