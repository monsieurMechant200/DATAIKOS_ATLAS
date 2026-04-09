"""
main.py
~~~~~~~
Point d'entrée de Dataikos Atlas.

Usages :
    python main.py            # Lance l'application graphique
    python main.py --test     # Lance la suite de tests unitaires
"""
from __future__ import annotations
import os
import sys

# ── Patches de compatibilité (doivent être appliqués EN PREMIER) ──────────────
from utils.patches import apply_patches, suppress_warnings
apply_patches()
suppress_warnings()
# ─────────────────────────────────────────────────────────────────────────────

from config   import AtlasConfig
from gui.app  import DataikosAtlasApp


def main() -> None:
    os.makedirs(AtlasConfig.DATA_DIR,    exist_ok=True)
    os.makedirs(AtlasConfig.REPORTS_DIR, exist_ok=True)

    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        import unittest
        sys.argv.pop(1)
        from tests.test_atlas import TestAtlas
        unittest.main(module="tests.test_atlas", verbosity=2)
    else:
        app = DataikosAtlasApp()
        app.mainloop()


if __name__ == "__main__":
    main()
