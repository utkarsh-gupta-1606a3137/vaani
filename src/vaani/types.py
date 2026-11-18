from __future__ import annotations
from dataclasses import dataclass, asdict, field
from pathlib import Path

class VaaniError(Exception):
    def __init__(self, code, message, *, stage=None, job_directory=None, details=None):
        super().__init__(message)
        self.code=int(code);self.message=message;self.stage=stage
        self.job_directory=str(job_directory) if job_directory else None
        self.details=details or {}
    def to_dict(self):
        return dict(status="failed",code=self.code,message=self.message,stage=self.stage,
                    job_directory=self.job_directory,details=self.details)

@dataclass
class SynthesisRequest:
    output_path: Path
    input_path: Path | None = None
    text: str | None = None
    input_format: str = "auto"
    voice_id: str | None = None
    output_format: str | None = None
    normalization: str | None = None
    seed: int | None = None
    overwrite: bool = False
    resume_job_dir: Path | None = None
    chunk_timeout_seconds: float = 900
    job_timeout_seconds: float = 7200

@dataclass
class SynthesisResult:
    status: str
    job_directory: Path
    output_file: Path
    format: str
    voice_id: str
    duration_seconds: float
    sample_rate: int
    channels: int
    manifest_file: Path
    cache_reused: bool
    warnings: list[str] = field(default_factory=list)
    def to_dict(self):
        return {k:str(v) if isinstance(v,Path) else v for k,v in asdict(self).items()}
