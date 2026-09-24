from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware" / "mlx_s3_monitor_fixed90"


def test_frame_guard_accepts_sustained_signal_and_rejects_corrupt_frames(tmp_path):
    """A missing retry decision or bad retry resolution must fail this host test."""
    binary = tmp_path / "frame_guard_test"
    compile_result = subprocess.run(
        [
            "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
            "-I", str(FIRMWARE),
            str(ROOT / "tests" / "firmware" / "frame_guard_test.cpp"),
            "-o", str(binary),
        ],
        text=True,
        capture_output=True,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    run_result = subprocess.run([str(binary)], text=True, capture_output=True)
    assert run_result.returncode == 0, run_result.stderr
