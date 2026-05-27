import hashlib
import shutil
from pathlib import Path

from app import config


def stage_path(source_path: str) -> Path:
    h = hashlib.sha256(source_path.encode()).hexdigest()[:16]
    return Path(config.IMPORT_STAGE_DIR) / h


def create_stage(source_path: str) -> Path:
    """Create the staging directory and write a .name hint file."""
    stage = stage_path(source_path)
    stage.mkdir(parents=True, exist_ok=True)
    (stage / ".name").write_text(Path(source_path).name, encoding="utf-8")
    return stage


def delete_stage(source_path: str) -> None:
    """Remove the staging directory after a successful import."""
    stage = stage_path(source_path)
    if stage.exists():
        shutil.rmtree(stage)
