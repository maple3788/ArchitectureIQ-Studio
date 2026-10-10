"""Execution authorization configured privately by the deployment operator."""

import os
import platform


def execution_host_enabled() -> bool:
    authorized = os.environ.get("ARCHITECTURE_IQ_KB_AUTHORIZED_HOST", "")
    declared = os.environ.get("ARCHITECTURE_IQ_KB_EXECUTION_HOST", "")
    return bool(authorized.strip()) and declared == authorized and platform.system() == "Linux"
