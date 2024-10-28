"""Original Qwen2 CPU responses with bounded context and cooperative stopping."""
import time
from .artifacts import manifest, verify_model
from .cpu import configure_cpu
from .provider_contracts import ProviderFailure

SYSTEM = (
    "You are a voice assistant in a local service-support demonstration. "
    "Reply in one short sentence of at most twenty words. "
    "Do not invent service facts or claim to perform actions. "
    "If information is missing, ask one brief question."
)


class QwenResponder:
    def __init__(self, tokenizer, model):
        self.tokenizer = tokenizer
        self.model = model

    @classmethod
    def load(cls, path):
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM

        verify_model(path, manifest("qwen"))
        configure_cpu(torch)
        tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(
            path, local_files_only=True, torch_dtype=torch.float32
        )
        model.eval()
        return cls(tokenizer, model)

    def reply(self, text, context, budget):
        budget.check()
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ProviderFailure("invalid_transcript")
        if not isinstance(context, list) or len(context) > 6:
            raise ProviderFailure("invalid_context")
        for message in context:
            if not isinstance(message, dict) or set(message) != {"role", "content"}:
                raise ProviderFailure("invalid_context")
            if (
                message["role"] not in ("user", "assistant")
                or not isinstance(message["content"], str)
                or len(message["content"]) > 1000
            ):
                raise ProviderFailure("invalid_context")
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList

        class Stop(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return budget.expired()

        # OpenMP limits must be applied in the actual inference worker thread.
        configure_cpu(torch)
        started = time.monotonic()
        prompt = self.tokenizer.apply_chat_template(
            [{"role": "system", "content": SYSTEM}]
            + context
            + [{"role": "user", "content": text}],
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self.tokenizer(prompt, return_tensors="pt", add_special_tokens=False)
        input_tokens = int(inputs["input_ids"].shape[-1])
        if input_tokens > 1024:
            raise ProviderFailure("context_limit")
        budget.check()
        with torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=48,
                do_sample=False,
                temperature=1.0,
                top_p=1.0,
                top_k=50,
                pad_token_id=self.tokenizer.eos_token_id,
                stopping_criteria=StoppingCriteriaList([Stop()])
            )
        budget.check()
        generated = output[0, input_tokens:]
        answer = self.tokenizer.decode(generated, skip_special_tokens=True).strip()
        if not answer or len(answer) > 500:
            raise ProviderFailure("invalid_model_response")
        return dict(
            text=answer,
            input_tokens=input_tokens,
            output_tokens=len(generated),
            latency_ms=(time.monotonic() - started) * 1000,
        )
