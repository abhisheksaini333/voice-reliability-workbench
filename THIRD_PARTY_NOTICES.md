# Third-party components

The runtime integrates Pipecat, aiohttp, PyTorch, Transformers, NumPy and SciPy through installed distributions, preserving their upstream licenses. Exact runtime versions are pinned in `requirements.lock`.

The local model is [Qwen2-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2-0.5B-Instruct/tree/c291d6fce4804a1d39305f388dd32897d1f7acc4), Apache-2.0. Transcription uses [Whisper tiny.en](https://huggingface.co/openai/whisper-tiny.en/tree/87c7102498dcde7456f24cfd30239ca606ed9063), Apache-2.0. Product manifests retain original file hashes, upstream locations and revisions. Weights are downloaded separately; Qwen's original license and both model cards are included in the download manifests.

Speech synthesis invokes the separate [eSpeak NG 1.51](https://github.com/espeak-ng/espeak-ng/releases/tag/1.51) program, GPL-3.0-or-later, with its upstream source, data and license obligations. It is not relabeled as this project's code. Container setup must retain the complete corresponding original source and license. Project-owned synthetic fixtures identify their synthesis method and are not represented as human recordings.
