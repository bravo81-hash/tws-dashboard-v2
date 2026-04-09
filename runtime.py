import os
import sys

EXPECTED_PYTHON_MAJOR_MINOR = (3, 11)


def apply_runtime_compat_env():
    if sys.version_info >= (3, 13) and "NUMBA_DISABLE_JIT" not in os.environ:
        os.environ["NUMBA_DISABLE_JIT"] = "1"


def get_runtime_diagnostics(expected_python=EXPECTED_PYTHON_MAJOR_MINOR):
    py_major_minor = (sys.version_info.major, sys.version_info.minor)
    warnings = []
    if py_major_minor != expected_python:
        warnings.append(
            f"Expected Python {expected_python[0]}.{expected_python[1]} for stable runtime; "
            f"running {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}."
        )
    if sys.version_info >= (3, 13):
        warnings.append(
            "Python >=3.13 detected. NUMBA_DISABLE_JIT=1 fallback is enabled for py_vollib compatibility."
        )

    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "expected_python": f"{expected_python[0]}.{expected_python[1]}",
        "numba_disable_jit": os.environ.get("NUMBA_DISABLE_JIT", ""),
        "warnings": warnings,
    }


def log_startup_diagnostics():
    runtime = get_runtime_diagnostics()
    print("\n--- Startup Diagnostics ---")
    print(f"Runtime Python: {runtime['python']} (target {runtime['expected_python']})")
    if runtime["numba_disable_jit"]:
        print(f"NUMBA_DISABLE_JIT={runtime['numba_disable_jit']}")
    if runtime["warnings"]:
        for warning in runtime["warnings"]:
            print(f"⚠️ {warning}")
    else:
        print("Runtime compatibility checks passed.")
