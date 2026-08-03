"""Broad catalog categories and deterministic fair selection helpers."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass

CATEGORY_TECHNOLOGY = "technology"
CATEGORY_APPLIANCES = "appliances"
CATEGORY_FASHION = "fashion"
CATEGORY_FOOTWEAR = "footwear"
CATEGORY_HOME = "home"
CATEGORY_HOME_IMPROVEMENT = "home_improvement"
CATEGORY_SUPERMARKET = "supermarket"
CATEGORY_BEAUTY_HEALTH = "beauty_health"
CATEGORY_TOYS_BABY = "toys_baby"
CATEGORY_SPORTS_OUTDOORS = "sports_outdoors"
CATEGORY_AUTOMOTIVE = "automotive"
CATEGORY_OTHER = "other"

CATEGORY_LABELS = {
    CATEGORY_TECHNOLOGY: "Tecnología",
    CATEGORY_APPLIANCES: "Electrohogar",
    CATEGORY_FASHION: "Moda",
    CATEGORY_FOOTWEAR: "Calzado",
    CATEGORY_HOME: "Hogar y decoración",
    CATEGORY_HOME_IMPROVEMENT: "Ferretería y mejoramiento",
    CATEGORY_SUPERMARKET: "Supermercado",
    CATEGORY_BEAUTY_HEALTH: "Belleza y salud",
    CATEGORY_TOYS_BABY: "Juguetes y bebé",
    CATEGORY_SPORTS_OUTDOORS: "Deportes y aire libre",
    CATEGORY_AUTOMOTIVE: "Automotriz",
    CATEGORY_OTHER: "Otros",
}

_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        CATEGORY_FOOTWEAR,
        (
            "calzado",
            "zapato",
            "zapatilla",
            "sandalia",
            "botin",
            "bota ",
            "mocasin",
            "zap ",
        ),
    ),
    (
        CATEGORY_FASHION,
        (
            "moda ",
            "ropa",
            "polo ",
            "camisa",
            "blusa",
            "vestido",
            "jean",
            "pantalon",
            "casaca",
            "buzo",
            "short",
            "basicos",
            "mochila",
        ),
    ),
    (
        CATEGORY_TECHNOLOGY,
        (
            "tecnologia",
            "comput",
            "laptop",
            "celular",
            "smartphone",
            "tablet",
            "audio",
            "audifono",
            "parlante",
            "televisor",
            "gamer",
            "camara",
            "impresora",
            "almacenamiento",
            "tecnologic",
            "usb",
            "antivirus",
            "memoria",
            "disco duro",
            "cable de red",
            "instax",
            "adaptador",
        ),
    ),
    (
        CATEGORY_APPLIANCES,
        (
            "electrohogar",
            "electrodomest",
            "refrigeradora",
            "lavadora",
            "secadora",
            "microondas",
            "licuadora",
            "cafetera",
            "freidora",
            "aspiradora",
            "ventilador",
            "lavaseca",
            "peladora de papas",
        ),
    ),
    (
        CATEGORY_BEAUTY_HEALTH,
        (
            "belleza",
            "higiene",
            "salud",
            "shampoo",
            "acondicionador",
            "cuidado personal",
            "perfume",
            "maquillaje",
            "alisador",
            "termoprotector",
        ),
    ),
    (
        CATEGORY_TOYS_BABY,
        (
            "juguete",
            "rompecabezas",
            "bebe",
            "infantil",
            "ninos",
            "lanzador",
        ),
    ),
    (
        CATEGORY_SPORTS_OUTDOORS,
        (
            "deporte",
            "fitness",
            "camping",
            "aire libre",
            "bicicleta",
            "parrilla",
            "piscina",
            "flotador",
            "deslizador",
        ),
    ),
    (
        CATEGORY_AUTOMOTIVE,
        (
            "automotriz",
            "auto ",
            "vehiculo",
            "motocic",
            "neumatic",
        ),
    ),
    (
        CATEGORY_HOME_IMPROVEMENT,
        (
            "mejoramiento del hogar",
            "ferreter",
            "herramienta",
            "electricidad",
            "iluminacion",
            "gasfiter",
            "grifer",
            "sanitario",
            "piso",
            "pared",
            "ceramic",
            "porcelanato",
            "pintura",
            "construccion",
            "lavadero",
            "ducha",
            "inversor de corriente",
            "estroboscopica",
        ),
    ),
    (
        CATEGORY_SUPERMARKET,
        (
            "supermercado",
            "abarrote",
            "bebida",
            "lacteo",
            "fruta",
            "verdura",
            "panader",
            "pasteler",
            "desayuno",
            "snack",
            "gaseosa",
            "galleta",
            "cereal",
            "licor",
            "cerveza",
            "vino",
            "alimento",
        ),
    ),
    (
        CATEGORY_HOME,
        (
            "decohogar",
            "decoracion",
            "dormitorio",
            "cocina",
            "comedor",
            "sala",
            "living",
            "mueble",
            "organizador",
            "closet",
            "bano",
            "hogar",
            "menaje",
            "terraza",
            "jardin",
            "cama",
            "ropero",
            "cojin",
            "mascota",
            "gato",
        ),
    ),
)

_STORE_FALLBACKS = {
    "casaideas": CATEGORY_HOME,
    "cassinelli": CATEGORY_HOME_IMPROVEMENT,
    "coolbox": CATEGORY_TECHNOLOGY,
    "footloose": CATEGORY_FOOTWEAR,
    "metro": CATEGORY_SUPERMARKET,
    "plazavea": CATEGORY_SUPERMARKET,
    "promart": CATEGORY_HOME_IMPROVEMENT,
    "topitop": CATEGORY_FASHION,
    "tottus": CATEGORY_SUPERMARKET,
    "vega": CATEGORY_SUPERMARKET,
    "wong": CATEGORY_SUPERMARKET,
}


def _searchable_text(values: Sequence[str]) -> str:
    joined = " ".join(value.strip().casefold() for value in values if value.strip())
    decomposed = unicodedata.normalize("NFKD", joined)
    return " ".join(
        "".join(character for character in decomposed if not unicodedata.combining(character))
        .replace("/", " ")
        .replace("-", " ")
        .split()
    )


def catalog_category(
    *,
    store_slug: str,
    label: str,
    category_path: Sequence[str] = (),
) -> str:
    """Classify one product into a deliberately broad commercial category."""

    searchable = _searchable_text((*category_path, label))
    for category, keywords in _KEYWORDS:
        if any(
            re.search(rf"\b{re.escape(keyword.strip())}", searchable)
            for keyword in keywords
        ):
            return category
    return _STORE_FALLBACKS.get(store_slug.strip().casefold(), CATEGORY_OTHER)


@dataclass(frozen=True, slots=True)
class BalanceEntry:
    """Minimal identity used by the fair interleaving algorithm."""

    store_slug: str
    category: str


def balanced_indices(
    entries: Sequence[BalanceEntry],
    *,
    limit: int,
    initial_entries: Sequence[BalanceEntry] = (),
) -> list[int]:
    """Return fair entry positions while preserving order inside each bucket.

    Broad-category representation is corrected first, then store representation
    and finally the pair of both dimensions. This prevents several stores from
    the same vertical from dominating the commercial feed. Nothing is discarded:
    callers can process remaining positions in a later batch.
    """

    if limit <= 0:
        return []

    store_counts = Counter(entry.store_slug for entry in initial_entries)
    category_counts = Counter(entry.category for entry in initial_entries)
    pair_counts = Counter(
        (entry.store_slug, entry.category) for entry in initial_entries
    )
    grouped: dict[tuple[str, str], deque[int]] = defaultdict(deque)
    first_position: dict[tuple[str, str], int] = {}
    for position, entry in enumerate(entries):
        pair = (entry.store_slug, entry.category)
        grouped[pair].append(position)
        first_position.setdefault(pair, position)

    selected: list[int] = []
    maximum = min(limit, len(entries))
    while grouped and len(selected) < maximum:
        pair = min(
            grouped,
            key=lambda candidate: (
                category_counts[candidate[1]],
                store_counts[candidate[0]],
                pair_counts[candidate],
                first_position[candidate],
            ),
        )
        position = grouped[pair].popleft()
        selected.append(position)
        store_slug, category = pair
        store_counts[store_slug] += 1
        category_counts[category] += 1
        pair_counts[pair] += 1
        if not grouped[pair]:
            del grouped[pair]
    return selected


__all__ = [
    "BalanceEntry",
    "CATEGORY_LABELS",
    "balanced_indices",
    "catalog_category",
]
