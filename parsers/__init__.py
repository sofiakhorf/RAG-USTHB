"""
Initialisation du paquet 'parsers'.

L'importation explicite de tous les modules de parseurs ici est INDISPENSABLE :
elle déclenche l'exécution des décorateurs `@ParserRegistry.register(...)` de chaque famille,
garantissant l'auto-enregistrement de tous les parseurs dans le Registre au démarrage.
"""

from parsers.fallback import FallbackParser
from parsers.family_a import FamilyAParser
from parsers.family_b import FamilyBParser
from parsers.family_c_d import ExcelWorkbookParser
from parsers.family_e import FamilyEParser
from parsers.family_f import FamilyFParser
from parsers.family_g import FamilyGParser
from parsers.family_h import FamilyHParser
from parsers.family_i import FamilyIParser
from parsers.family_j import FamilyJParser

__all__ = [
    "FallbackParser",
    "FamilyAParser",
    "FamilyBParser",
    "ExcelWorkbookParser",
    "FamilyEParser",
    "FamilyFParser",
    "FamilyGParser",
    "FamilyHParser",
    "FamilyIParser",
    "FamilyJParser",
]