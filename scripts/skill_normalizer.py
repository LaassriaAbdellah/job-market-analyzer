
import json
import re
import unicodedata
from functools import lru_cache

from scripts.common import CONFIG_DIR


ALIASES_PATH = CONFIG_DIR / "skill_aliases.json"


def normalize_text(text: str) -> str:
    """
    Normalise un nom de compétence :
    - minuscules ;
    - suppression des accents ;
    - uniformisation des espaces.
    """

    text = unicodedata.normalize("NFKD", str(text))

    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )

    text = text.casefold()
    text = re.sub(r"\s+", " ", text)

    return text.strip()


@lru_cache(maxsize=1)
def load_alias_mapping() -> dict[str, str]:
    """
    Charge skill_aliases.json et construit :
    variante normalisée -> nom canonique.
    """

    with ALIASES_PATH.open("r", encoding="utf-8") as f:
        aliases = json.load(f)

    mapping = {}

    for canonical, variants in aliases.items():

        canonical = str(canonical).strip()

        if not canonical:
            continue

        for variant in [canonical, *variants]:
            normalized = normalize_text(variant)

            if normalized:
                mapping[normalized] = canonical

    return mapping


def canonicalize_skill(skill: str) -> str:
    """
    Retourne le nom canonique d'une compétence.

    Exemple :
    'sklearn' -> 'Scikit-learn'
    """

    normalized = normalize_text(skill)

    if not normalized:
        return ""

    mapping = load_alias_mapping()

    return mapping.get(normalized, normalized)


def canonicalize_skills(skills) -> set[str]:
    """
    Normalise une collection de compétences
    et supprime les doublons.
    """

    result = set()

    for skill in skills or []:

        canonical = canonicalize_skill(skill)

        if canonical:
            result.add(canonical.casefold())

    return result
