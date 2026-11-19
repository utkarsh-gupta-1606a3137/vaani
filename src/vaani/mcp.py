"""Local stdio MCP adapter; narration remains owned by the existing CLI."""

import json
import signal
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from .config import project_root


server = MCPServer("Vaani")


def absolute_path(value: str) -> Path:
    """Paths must have the same meaning regardless of the client's directory."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ToolError("Use an absolute path (or ~/...) for local files.")
    return path.resolve()


async def run_cli(arguments: list[str], content: str | None) -> dict:
    root = project_root()
    process = await anyio.open_process(
        [str(root / "bin/vaani"), "synthesize", "--json", *arguments],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,  # Progress must never enter the MCP stdout transport.
        cwd=root,
    )
    try:
        assert process.stdin is not None and process.stdout is not None
        if content is not None:
            await process.stdin.send(content.encode("utf-8"))
        await process.stdin.aclose()
        chunks = []
        async for chunk in process.stdout:
            chunks.append(chunk)
        code = await process.wait()
        try:
            result = json.loads(b"".join(chunks))
        except (ValueError, UnicodeError) as exc:
            raise ToolError(f"Vaani exited with code {code} without a JSON result; inspect stderr.") from exc
        if code:
            # Raising makes the SDK mark this as an MCP tool error. Preserve the
            # CLI's error code and recovery paths for the caller.
            raise ToolError(json.dumps(result, ensure_ascii=False))
        return result
    finally:
        # SIGINT lets the CLI stop its separate worker group and save chunks.
        # Shield cleanup so MCP cancellation/disconnection cannot orphan it.
        with anyio.CancelScope(shield=True):
            if process.returncode is None:
                try:
                    process.send_signal(signal.SIGINT)
                except ProcessLookupError:
                    pass
                with anyio.move_on_after(15):
                    await process.wait()
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            await process.aclose()


@server.tool()
async def generate_narration(
    content: Annotated[str | None, Field(max_length=100000)] = None,
    content_file: str | None = None,
    output_path: str | None = None,
    voice: Literal["amit", "saba"] | None = None,
    output_format: Literal["wav", "mp3"] | None = None,
    input_format: Literal["auto", "text", "markdown"] = "auto",
    normalization: Literal["audition-rms-v1", "none"] | None = None,
    seed: Annotated[int | None, Field(ge=0, lt=2**32)] = None,
    overwrite: bool = False,
    resume_job_dir: str | None = None,
    chunk_timeout_seconds: Annotated[float, Field(ge=1, le=7200)] = 900,
    job_timeout_seconds: Annotated[float, Field(ge=1, le=86400)] = 7200,
) -> dict[str, Any]:
    """Generate local speech, primarily for Hinglish (Hindi mixed with English).

    Provide exactly one of content (final spoken text) or content_file (absolute
    UTF-8 .txt/.md path on this Mac). Hindi in Devanagari with English terms is
    the tested format; other text is accepted but pronunciation can vary.
    This tool narrates supplied content; it does not write or rewrite it.

    output_path is an absolute destination filename, including .wav or .mp3.
    If omitted, save a unique file under this installation's outputs/ directory.
    voice defaults to amit; saba is also available. output_format is inferred
    from the filename, otherwise wav. input_format defaults to auto (inline
    content is plain text). normalization defaults to audition-rms-v1. seed
    uses the selected voice's default. Existing files require overwrite=true.

    resume_job_dir is an absolute Vaani job directory; when resuming, content
    may be omitted and saved voice/seed/normalization are retained. Timeouts
    are seconds. Generation can take several minutes; allow a long tool timeout.
    Returns the absolute output_file and job/manifest paths, format, voice,
    duration and audio metadata. Audio stays on this Mac, not in the response.
    """
    if content is not None and content_file is not None:
        raise ToolError("Provide exactly one of content or content_file.")
    if content is None and content_file is None and resume_job_dir is None:
        raise ToolError("Provide content or content_file (or resume_job_dir for recovery).")
    if content is not None and not content.strip():
        raise ToolError("content must contain spoken text.")
    output = (
        absolute_path(output_path) if output_path is not None
        else project_root() / "outputs" / f"narration-{uuid4().hex}.{output_format or 'wav'}"
    )
    arguments = ["--output", str(output), "--input-format", input_format,
                 "--chunk-timeout", str(chunk_timeout_seconds),
                 "--job-timeout", str(job_timeout_seconds)]
    if content is not None:
        arguments.append("--stdin")
    if content_file is not None:
        arguments.extend(["--input", str(absolute_path(content_file))])
    if resume_job_dir is not None:
        arguments.extend(["--resume", str(absolute_path(resume_job_dir))])
    for flag, value in (("--voice", voice), ("--format", output_format),
                        ("--normalization", normalization), ("--seed", seed)):
        if value is not None:
            arguments.extend([flag, str(value)])
    if overwrite:
        arguments.append("--overwrite")
    return await run_cli(arguments, content)


def main():
    if sys.argv[1:]:
        raise SystemExit("Usage: vaani-mcp (stdio server); vaani-mcp --setup (one-time dependency setup)")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
