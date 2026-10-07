"""Food ontology shared by dish and user vectors (Recommendation_System_Design_Ver1.1 §2.2).

The order of DIMENSIONS is the order inside every vector(12) column. Changing it, or the number
of dimensions, invalidates every stored vector: bump ONTOLOGY_VERSION and regenerate them.
"""

ONTOLOGY_VERSION = 1

DIMENSIONS: tuple[str, ...] = (
    "sweet",
    "sour",
    "salty",
    "bitter",
    "umami",
    "spicy",
    "cooling",
    "astringent",
    "fatty",
    "fresh",
    "rich",
    "aromatic",
)

DIMENSION_COUNT = len(DIMENSIONS)

# Discrete intensity scale the AI uses when scoring a dish on each dimension.
SCALE: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)
