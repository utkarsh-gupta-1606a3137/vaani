# Development-machine validation

Verified November 18, 2026 on an Apple silicon Mac with 32 GB unified memory. The following measurements describe the original development installation; public bootstrap validation is recorded separately below.

- 20 contract/regression tests passed.
- Fresh Amit WAV: 19.32 seconds, generated in 38.87 seconds including worker startup.
- Fresh Saba WAV: 22.95 seconds, generated in 76.14 seconds.
- Four-paragraph / 212-word input: Amit 71.88 seconds audio in 70.15 seconds; Saba 87.89 seconds audio in 233.61 seconds.
- Both voices' MP3 conversions decoded successfully, retained canonical duration and reused cached raw speech without fresh model inference.
- All chunks completed on first attempt, without split recovery or warnings.
- Maximum observed worker RSS 4.84 GiB. Minimum system availability during these tests 14.19 GiB. Model allocation and process RSS are different measurements.

Saba's fresh raw audition matched the approved raw recording byte for byte. Amit used the approved conditioning reference and settings, but differed slightly from its earlier audition (19.32 vs 19.92 seconds), with different seed timing around model loading. Fresh listening approval remains pending for that delivery and both long tracks. Automated stream checks do not establish pronunciation, semantic completeness or pleasantness.

Large unrelated models were unloaded with user permission for serial inference tests. Vaani itself does not unload other applications. It requires 9 GiB available before model loading, with further worker and allocation guards.

Private raw manifests and audio remain in the development installation and are not published. The public installer has no personal legacy default or private asset-bundle dependency.

## Standalone public installer verification

The public source was installed into its own empty runtime/model/cache directories on the supported development Mac. This is an isolated installation test on the same physical host, not a second physical machine.

- Actual network bootstrap downloaded official uv 0.13.9 and portable CPython 3.12.16 build 20261110; both archives matched pinned SHA-256 digests. No system Python was needed by the bootstrap shell.
- All three runtime environments were created fresh; pinned dependencies came from PyPI, not copied environments. Installed distribution versions were verified against the lockfiles. Package artifact hash locks were generated from PyPI metadata. All three runtimes were then reinstalled with `--require-hashes` successfully, and an entirely offline setup rerun reported both voices ready.
- Models were imported explicitly from a separate working installation to avoid repeating approximately 7.28 GB of downloads. Only manifest-listed files were imported, with per-file size and SHA-256 verification. No extra donor-directory files or private handoff assets were copied.
- Pinned Indic support files, including Vocos load/init helpers, were also fetched directly from upstream and compared to working assets. Their bytes matched; no unpublished local patch is required. The actual model downloader additionally fetched and SHA-verified the pinned S3 configuration over the network.
- 31 contract tests passed, including download checksum rejection with prior-file preservation, successful verified publication, host restriction, complete runtime asset inventory, tracked conditioning hash and warm-bootstrap lease exclusion.

Full multi-gigabyte model downloads through the public installer have not been repeated end to end. The pinned URLs and all target checksums are supplied; this distinction is separate from testing imported files and fresh runtime creation. Human listening approval remains separate from stream validation. Exact sampled waveforms can vary by hardware/runtime; profile, model, seed and conditioning identity are preserved.

### Fresh public-runtime speech verification

With unrelated model memory temporarily released with user permission, both voices ran serially using the newly installed public runtime environments and exactly the manifest-listed model files:

| Voice / format | Audio duration | Job time | Fresh chunks / reused chunks |
|---|---:|---:|---:|
| Amit WAV | 19.32 s | 39.13 s | 1 / 0 |
| Saba WAV | 22.9547 s | 76.17 s | 1 / 0 |
| Amit MP3 | 19.32 s | 0.10 s | 0 / 1 |
| Saba MP3 | 22.9547 s | 0.11 s | 0 / 1 |

All four jobs completed without warnings or recovery. Both MP3 files decoded and matched canonical duration. The original model application was restored after testing. These are actual fresh-environment synthesis results; they do not claim every future host produces identical samples or replace human listening review.

### Clean tracked-source clone check

A fresh local Git clone of the committed files independently downloaded the pinned uv/Python archives and installed its control environment with `setup --allow-download --bootstrap-only --json`. All 31 tests then passed inside that clone. This checks tracked-file completeness and bootstrap portability to a new directory; it does not claim full model downloads or testing on a second physical host. All five public weight URLs also returned HTTP 200 with their expected file sizes without credentials.
