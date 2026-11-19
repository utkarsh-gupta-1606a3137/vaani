# Vaani

**Local Hinglish narration for Apple silicon macOS 26 or newer.** Clone this repository, run the explicit setup command below, then generate speech offline. Setup installs portable Python, isolated environments, models and caches inside the cloned project; no global Python, Homebrew package, shell-profile change or cloud inference is required.

32 GB unified memory is recommended. Generation requires at least 9 GiB available memory before loading a voice. Allow about 20 GB free disk space for model files, dependencies, download caches and repair room. The pinned model files total approximately 7.28 GB; the first online setup also downloads runtime packages. macOS 26 is required by the pinned MLX wheels; Intel Macs, older macOS, Linux and Windows are unsupported by this release.
Built with Indic-Speak from Bodhan AI / AI4Bharat. Chatterbox synthesis uses Resemble AI Chatterbox through MLX Audio. See [third-party notices](THIRD_PARTY_NOTICES.md).

Local Hinglish narration for Apple silicon macOS. Give Vaani final spoken text and choose `amit` or `saba`; receive WAV or MP3. No cloud inference, global installation or running server is required.

## Install and run

Clone the repository and run:

```sh
git clone https://github.com/utkarsh-gupta-1606a3137/vaani.git
cd vaani
./bin/vaani setup --allow-download --json
./bin/vaani doctor --json
./bin/vaani voices list
./bin/vaani synthesize --input examples/audition.txt --voice amit --output narration.wav
./bin/vaani synthesize --input examples/audition.txt --voice saba --output narration.mp3 --json
```

`setup --allow-download` is the explicit permission to download pinned public artifacts. Normal synthesis does not download anything. The launcher bootstraps with macOS shell tools (`curl`, `tar`, `shasum`, `install`) and does not require a preinstalled Python or uv. Terminal Git is needed only to clone the repository. Setup logs are under `tmp/setup-*.log`; progress goes to stderr and `--json` keeps a single result on stdout.

WAV defaults to mono PCM16 at 24 kHz. An `.mp3` suffix selects real mono 24 kHz, 128 kbps MP3; `--format` can select it explicitly. A contradictory extension is rejected. Existing output is protected unless `--overwrite` is supplied.

The launcher derives its project root, so an absolute invocation works from another directory:

```sh
/absolute/path/to/vaani/bin/vaani synthesize --input /absolute/path/content.txt --voice saba --output /absolute/path/narration.wav
```

## Connect an AI chatbot through MCP

The optional adapter uses the [official MCP Python SDK](https://py.sdk.modelcontextprotocol.io/). It exposes one tool, `generate_narration`, over local stdio. The client launches Vaani when needed; no separate running server, API key, shell activation, PATH change, or project working directory is required.

After the normal Vaani setup, install the MCP dependencies once:

```sh
./bin/vaani-mcp --setup
```

This explicitly downloads pinned, hash-checked packages into `.runtime/envs/mcp`. It leaves the control and speech environments alone. Normal MCP startup and narration work offline. Rerun this command after an MCP dependency update or after repairing/relocating the main installation.

In your chatbot's **user/application-level MCP configuration**, register the absolute launcher path (replace the example with your clone's actual location):

```json
{
  "mcpServers": {
    "vaani": {
      "command": "/absolute/path/to/vaani/bin/vaani-mcp",
      "args": []
    }
  }
}
```

The outer configuration syntax depends on the client; use its local/stdio MCP server settings. Do not put `--setup` in the client configuration. User-level registration makes the tool available outside a particular project. The absolute launcher locates its own code, Python, models and caches even if the client starts in another directory. Keep that installation on disk; update the configured path and rerun setup after moving it. Each client needs its own registration.

Keep machine-specific paths in your MCP client's private settings. For a local configuration snippet, copy `config/mcp.example.json` to `config/mcp.local.json` and replace the placeholder there; `config/*.local.json` is ignored by Git. Copy/import that snippet into your client using its own configuration flow. The Vaani launcher does not read this JSON file: it derives its installation root automatically, so no personal paths belong in source code or committed configuration.

Example tool arguments:

```json
{
  "content": "नमस्ते! आज हम एक छोटा example समझेंगे।",
  "output_path": "/absolute/path/to/narration.wav"
}
```

Use this tool primarily for Hinglish: Devanagari Hindi mixed with English terms is the tested input. Other text is accepted, but pronunciation can vary. Supply final narration text; the tool does not generate or rewrite content.

| Argument | Default / behavior |
|---|---|
| `content` / `content_file` | Exactly one required for a new job: inline text or an absolute UTF-8 `.txt`/`.md` file path. |
| `output_path` | Optional absolute destination filename. If omitted, a unique `outputs/narration-<id>.wav` in the installation. `~/...` paths are also supported. |
| `voice` | `amit`; optionally `saba`. |
| `output_format` | Inferred from `.wav`/`.mp3` filename; otherwise `wav`. Contradictory extensions are rejected. |
| `input_format` | `auto`; optionally `text` or `markdown`. Inline content defaults to text. |
| `normalization` | `audition-rms-v1`; optionally `none`. |
| `seed` | Voice default; optionally an integer from 0 through 4,294,967,295. |
| `overwrite` | `false`; existing output files are protected. |
| `resume_job_dir` | Optional absolute job directory from a prior result. Content may be omitted for recovery; saved voice, seed and normalization are reused. |
| `chunk_timeout_seconds` | 900; allowed range 1–7,200. |
| `job_timeout_seconds` | 7,200; allowed range 1–86,400. |

File paths refer to files on the Mac running Vaani. Relative paths are rejected so their meaning cannot depend on the chatbot's working directory. Results contain an absolute `output_file`, job and manifest paths, voice, format, duration and audio metadata; the audio remains on disk. Failures are MCP tool errors with the CLI error details and recovery paths. Progress goes to stderr, keeping protocol stdout clean. Cancellation interrupts the CLI so it can stop its worker and retain completed chunks. The existing single-worker lease also applies across clients.

Configure the client's tool timeout to allow the requested job duration (normally at least 7,200 seconds plus some cleanup time). A client that times out sooner may cancel generation. This adapter is for trusted local clients that can read and write files on your Mac.

Run the adapter checks after setup:

```sh
PYTHONPATH=src .runtime/envs/mcp/bin/python -m unittest discover -s tests -p test_mcp.py -v
```

## Voices

| ID | Backend | Approved identity |
|---|---|---|
| `amit` (default) | Chatterbox Multilingual V3 / MLX | Specific accepted synthetic Amit reference, preserved under `voices/references/` |
| `saba` | Indic-Speak / 8-bit MLX, CPU SNAC/Vocos decoder | Named Saba speaker and the accepted settings |

The repository includes the one required synthetic Amit conditioning WAV, verified by SHA-256. It excludes other generated recordings, personal history and installed models. `amit` is not replaced with direct Indic-Speak Amit. Default gain matching follows the accepted audition; `--normalization none` retains the assembled unnormalized track. It does not apply pitch or speed changes.

## Input

Use UTF-8 `.txt` or `.md`, or `--stdin`. The engine preserves content instead of rewriting it. Hindi in Devanagari mixed with English terms is the auditioned format; Roman Hindi pronunciation is not guaranteed.

```sh
cat content.txt | ./bin/vaani synthesize --stdin --voice amit --output narration.wav
./bin/vaani synthesize --input speech.md --input-format markdown --output narration.wav
```

Markdown headings, frontmatter, comments, fenced code and images are excluded. List words, link labels and inline-code text remain. Tables, embedded HTML and ambiguous inputs are rejected. Provide final speech, not a complete video production prompt.

Coherent paragraphs are kept whole when bounded. Long paragraphs split at sentence/clause boundaries with exact word order retained. The golden paragraph remains one generation. Joins add only missing quiet time; they do not overlap speech or normalize each sentence separately.

## Setup, repair and relocation

Portable uv **0.13.9** and CPython **3.12.16** (standalone build **20261110**) are pinned in `scripts/bootstrap.sh`; their archives are checked against literal SHA-256 digests before extraction. Bootstrap stages and tests Python before publishing its tree. See the [official uv release](https://github.com/astral-sh/uv/releases/tag/0.13.9) and [pinned Python metadata](https://github.com/astral-sh/uv/blob/0.13.9/crates/uv-python-managed/download-metadata.json).

All runtime packages are pinned under `locks/`; the `*.hashed.lock` files additionally require approved package artifact hashes. Setup creates separate `control`, `chatterbox` and `indic` environments and verifies installed versions. Model downloads use exact repository revisions and per-file size/SHA-256 checks in `config/downloads.json`. This includes executable model helper code and all local Vocos loader files. Existing validated files are reused, and missing/corrupt model files are repaired individually. Failed downloads do not replace a prior file.

```sh
# Recheck/repair, allowing downloads only when needed:
./bin/vaani setup --allow-download --json
# Validate/rebase using only already cached artifacts:
./bin/vaani setup --json
# Install just portable tools and the lightweight control environment:
./bin/vaani setup --allow-download --bootstrap-only --json
# Avoid downloading model weights by explicitly importing verified files
# from a separate Vaani installation; runtimes are still created locally:
./bin/vaani setup --allow-download --import-from /absolute/path/to/existing-vaani --json
```

There is no default import source and no dependency on a private audition bundle. Import never modifies its source and copies only checksum-matching manifest-listed assets. A missing/corrupt tracked `voices/references/amit-conditioning.wav` must be restored from this repository; setup does not substitute another voice. If an interrupted bootstrap leaves `.state/bootstrap.lock`, verify that the bootstrap is no longer running before removing the abandoned lock directory and rerunning setup. Model downloads restart an interrupted individual file; completed files are retained.

Runtime state lives under `.runtime/`, `models/`, `cache/`, `.state/`, `runs/` and `tmp/`. `voices/references/amit-conditioning.wav` is a necessary tracked input, not disposable cache. Deleting the project removes its local installation; explicitly selected output files elsewhere remain. After moving the project, run setup again to rebase its environments. Cached offline setup works while the required archives and package wheels remain available; otherwise use `--allow-download`.

Setup and warm bootstrap acquire the same project lease as synthesis, so they cannot replace interpreter/model files while a voice job runs. The control process stays lightweight. Voice workers use separate pinned Python environments and terminate when finished. `doctor` checks readiness without initializing Metal or loading a model.

## Jobs, reuse and recovery

Each run has a `runs/<job>/manifest.json`, original/prepared text, worker log, measured chunk cues and resource telemetry. `--json` emits one final JSON result on stdout; progress is stderr.

```sh
./bin/vaani status --job /absolute/path/to/vaani/runs/JOB --json
./bin/vaani synthesize --resume /absolute/path/to/vaani/runs/JOB --output recovered.wav --json
```

Resume restores the saved voice, seed, prepared content and normalization unless explicitly changed incompatibly. Valid raw chunks are reused across output destinations/formats; corrupt chunks are regenerated. Ctrl-C stops only the job's worker group and preserves completed chunks. A failure during final output/manifest publication rolls back the prior output.

## Resource limits

One heavyweight worker or setup/repair operation can own the project lease at a time. Initial preflight requires 9 GiB available; MLX allocation is capped at 8 GiB, cache at 256 MiB, worker RSS at 10 GiB, and minimum system availability at 1.5 GiB. Per-chunk timeout defaults to 900 seconds and job timeout to 7,200 seconds. CLI options `--chunk-timeout` and `--job-timeout` can set bounded limits.

If another application has loaded a large model, Vaani refuses safely. Close/unload that model yourself before retrying. Vaani does not terminate unrelated applications or promise that resource caps prevent an OS/driver fault.

## Python API

Use the project control interpreter with the source directory on `PYTHONPATH`, or install the package into a caller-owned environment. No model is loaded on import.

```python
from pathlib import Path
from vaani import SynthesisRequest, synthesize

result = synthesize(
    SynthesisRequest(text="नमस्ते, आज हम एक छोटा example समझेंगे।", voice_id="saba", output_path=Path("speech.wav")),
    root=Path("/absolute/path/to/vaani"),
)
print(result.output_file)
```

Unspecified voice/normalization resolve to the normal defaults for new jobs and the saved values for resumed jobs. Typed `VaaniError` carries the documented exit/error code.

## Verification

```sh
PYTHONPATH=src .runtime/envs/control/bin/python -m unittest discover -s tests -v
```

See [VALIDATION.md](VALIDATION.md) for measured development-machine results and limitations. Raw private run reports are not included. Technical stream checks do not prove pronunciation or pleasantness. Full long-form listening remains a user review gate.

No video, content-writing LLM, hosted API, scheduler, extra voices or publishing is included. The optional local MCP adapter delegates narration to the existing CLI.

## Source checks without model downloads

With Python 3.12 and `psutil` installed in your chosen environment:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The tests exercise contracts with synthetic test audio and mocked model workers; they do not load models. Real inference measurements are documented separately. Original Vaani code is licensed under MIT; dependencies, downloaded models and the model-derived conditioning reference retain their applicable upstream terms.

## Optional word timestamps

Add `--word-timestamps` to create a sidecar with recognized text and estimated
word timings after speech generation. The speech worker exits before the local
Whisper worker starts. Ordinary synthesis remains audio-only.

Whisper settings reuse `config/voices.json`. Keep machine-specific paths in
`config/voices.local.json`, which is ignored by Git. Only the `whisper` section
is overridden; voice profiles and their cache identities are unchanged.

```json
{
  "whisper": {
    "model_path": "/absolute/path/to/downloaded/whisper-large-v3-turbo",
    "language": "hi"
  }
}
```

A relative model path resolves against the Vaani project. The shared default is
`models/whisper-large-v3-turbo`; `language: "auto"` enables language detection.
An optional short `initial_prompt` can supply vocabulary hints. No model is
downloaded during synthesis or optional-runtime setup.

Install the separate, checksum-pinned Whisper Python runtime once:

```sh
./bin/vaani setup --word-timestamps --allow-download --json
./bin/vaani doctor --word-timestamps --json
./bin/vaani synthesize --input speech.txt --output narration.wav --word-timestamps
```

The setup download permission applies to Python packages only. Omit
`--allow-download` when the package cache is already populated. A normal Vaani
installation and local MLX Whisper weights must exist first.

The command writes `narration.wav` and `narration.timestamps.json`; MP3 output
uses the same sidecar naming rule. CLI/Python/MCP results include
`timestamps_file` and `timestamps_cache_reused` only when enabled. The MCP
option is `word_timestamps: true`. New jobs default to false; resume preserves
the saved choice when omitted. Use `--no-word-timestamps` or the explicit MCP
false value to disable it on a resumed job.

The sidecar uses `vaani-word-timestamps/1`, with `text`, `segments[].words[]`
(`word`, `start`, `end`, `probability`), audio hash/duration and model fingerprint.
All word times are seconds from the final audio recording's beginning,
including when generation used multiple chunks. Its metadata contains only the
audio basename, not installation/model/input paths. ASR timings and probability
scores require review; they are not word-perfect alignment or pronunciation
certification. Visual cue selection remains the narration analyzer's job.

Generated sidecars, runtime caches, job manifests and local configuration are
ignored by Git. CLI/MCP results and private job metadata intentionally retain
absolute paths for locating files and recovering jobs; those paths are visible
to the connected client. Review local artifacts before sharing them.

If recognition fails, the command reports failure and retains generated audio
in the reported job directory; completed speech chunks remain reusable. Resume
with the same job to retry without resynthesizing valid speech. Existing audio
and sidecar destinations are protected unless `--overwrite` is supplied. A
publication/manifest failure rolls back both destinations when possible.
Timestamp caches are bound to audio/model/settings/code identities and validated
before reuse. If audio is overwritten with timestamp generation disabled, an
older sidecar is not refreshed; consumers must check its audio hash.
