from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from voice.cpu import configure_cpu


class CpuProfileTests(TestCase):
    def test_linux_arm_reference_path_and_thread_local_limit(self):
        torch = SimpleNamespace(
            set_num_threads=Mock(),
            backends=SimpleNamespace(mkldnn=SimpleNamespace(enabled=True)),
        )
        with patch("voice.cpu.platform.system", return_value="Linux"), patch(
            "voice.cpu.platform.machine", return_value="aarch64"
        ):
            configure_cpu(torch)
        torch.set_num_threads.assert_called_once_with(2)
        self.assertFalse(torch.backends.mkldnn.enabled)
