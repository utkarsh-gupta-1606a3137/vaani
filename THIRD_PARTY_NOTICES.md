# Third-party notices

Built with Indic-Speak from Bodhan AI / AI4Bharat.

Vaani orchestrates external synthesis packages; this source release excludes their model weights and includes one required synthetic Amit conditioning WAV. Original Vaani code is licensed under MIT (see LICENSE). Dependencies, model assets and model-derived conditioning audio retain their applicable upstream terms.

- [Indic-Speak MLX conversion](https://huggingface.co/iniquitous/indic-speak-mlx-8bit), pinned revision `f5ede72229c6dc7238670066910aa0b51f69635e`. Preserved publisher license texts are under `docs/licenses/`; consult the model publisher before redistributing assets or providing hosted access.
- [Chatterbox](https://github.com/resemble-ai/chatterbox), [MLX model conversion](https://huggingface.co/mlx-community/chatterbox-multilingual-v3), and [MLX Audio](https://github.com/Blaizzy/mlx-audio). Model/package terms apply independently.
- [S3TokenizerV2](https://huggingface.co/mlx-community/S3TokenizerV2), [SNAC](https://huggingface.co/hubertsiuzdak/snac_24khz), PyTorch, Vocos, FFmpeg/libmp3lame, MLX, and other packages listed in `locks/` are external dependencies, not bundled binaries.

The tracked Amit conditioning WAV is synthetic speech previously generated locally using Indic-Speak. It is required for the Chatterbox Amit profile; it is not a recording of the ChatGPT voice or a claim to another person's voice rights. All applicable upstream model terms still apply.
