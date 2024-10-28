"""Bound CPU threads and avoid the pinned Linux ARM oneDNN memory failure."""
import platform


def configure_cpu(torch):
    # OpenMP settings must be repeated in the actual inference thread.
    torch.set_num_threads(2)
    if platform.system() == "Linux" and platform.machine() in ("aarch64", "arm64"):
        # Original Torch2.3 ARM optimized Qwen execution exceeded4GiB under the
        # measured bounded workload. The reference CPU path completed it.
        torch.backends.mkldnn.enabled = False
