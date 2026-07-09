import os


def _env_enabled(name):
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


try:
    from extensions import EXTENSION_REGISTRY_MD, EXTENSION_REGISTRY_TD
    if _env_enabled("GZ_MOCK_MD_NATIVE"):
        from .kfext_mock_native import MD as MockMd
    else:
        from .md_mock import MockMd
    if _env_enabled("GZ_MOCK_TD_NATIVE"):
        from .kfext_mock_native import TD as MockTd
    else:
        from .td_mock import MockTd
except ImportError:
    EXTENSION_REGISTRY_MD = None
    EXTENSION_REGISTRY_TD = None
else:
    EXTENSION_REGISTRY_MD.register_extension("mock", MockMd)
    EXTENSION_REGISTRY_TD.register_extension("mock", MockTd)
