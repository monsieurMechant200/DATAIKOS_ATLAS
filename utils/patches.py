"""
utils/patches.py
~~~~~~~~~~~~~~~~
Patches de compatibilité appliqués au démarrage de l'application.
  - hashlib.md5 : corrige l'argument usedforsecurity absent sur Python < 3.9
    (requis par ReportLab)
  - Suppression des UserWarning / RuntimeWarning de statsmodels
"""
import hashlib
import warnings

_original_md5 = hashlib.md5


def _patched_md5(arg=None, **kwargs):
    kwargs.pop("usedforsecurity", None)
    if arg is not None:
        return _original_md5(arg, **kwargs)
    return _original_md5(**kwargs)


def apply_patches() -> None:
    """Applique tous les patches de compatibilité."""
    hashlib.md5 = _patched_md5


def suppress_warnings() -> None:
    """Supprime les avertissements non critiques de statsmodels."""
    warnings.filterwarnings("ignore", category=UserWarning,   module="statsmodels")
    warnings.filterwarnings("ignore", category=RuntimeWarning, module="statsmodels")
    warnings.filterwarnings("ignore", category=FutureWarning)
