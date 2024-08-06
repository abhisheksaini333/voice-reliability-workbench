"""Actual local Whisper transcription of bounded mono 16kHz PCM."""
import time
from .artifacts import manifest, verify_model
from .provider_contracts import ProviderFailure


class WhisperRecognizer:
    def __init__(self, processor, model):
        self.processor = processor
        self.model = model

    @classmethod
    def load(cls, path):
        import torch
        from transformers import AutoProcessor, AutoModelForSpeechSeq2Seq

        verify_model(path, manifest("whisper"))
        torch.set_num_threads(2)
        processor = AutoProcessor.from_pretrained(path, local_files_only=True)
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            path, local_files_only=True, torch_dtype=torch.float32
        )
        model.eval()
        return cls(processor, model)

    def transcribe(self, pcm, budget):
        budget.check()
        if (
            not isinstance(pcm, bytes)
            or len(pcm) % 2
            or not 640 <= len(pcm) <= 16000 * 2 * 12
        ):
            raise ProviderFailure("invalid_audio")
        import numpy as np
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList

        class Stop(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return budget.expired()

        started = time.monotonic()
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        features = self.processor(
            samples, sampling_rate=16000, return_tensors="pt"
        ).input_features
        budget.check()
        with torch.inference_mode():
            output = self.model.generate(
                features,
                max_new_tokens=128,
                do_sample=False,
                stopping_criteria=StoppingCriteriaList([Stop()]),
            )
        budget.check()
        text = self.processor.batch_decode(output, skip_special_tokens=True)[0].strip()
        if len(text) > 2000:
            raise ProviderFailure("transcription_too_long")
        return dict(
            text=text,
            generated_tokens=int(output.shape[-1]),
            latency_ms=(time.monotonic() - started) * 1000,
        )
