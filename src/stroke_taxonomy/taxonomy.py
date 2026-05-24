"""Stroke taxonomy query interface.

Provides query capabilities for stroke info and character-to-stroke mappings
from the stroke taxonomy JSON file.
"""

import json
from typing import Optional


class StrokeTaxonomy:
    """Stroke taxonomy query interface."""

    def __init__(self, taxonomy_path: str):
        """Load the stroke taxonomy JSON file.

        Args:
            taxonomy_path: Path to stroke_taxonomy.json
        """
        with open(taxonomy_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._strokes = data["strokes"]
        self._char_to_strokes = data["char_to_strokes"]

        # Build indexes
        self._id_to_stroke: dict[int, dict] = {s["id"]: s for s in self._strokes}
        self._name_to_id: dict[str, int] = {s["name"]: s["id"] for s in self._strokes}
        self._type_to_ids: dict[str, list[int]] = {}
        for s in self._strokes:
            self._type_to_ids.setdefault(s["stroke_type"], []).append(s["id"])

    def num_strokes(self) -> int:
        """Return total number of stroke categories."""
        return len(self._strokes)

    def get_stroke(self, stroke_id: int) -> dict:
        """Get stroke info by ID."""
        return self._id_to_stroke[stroke_id]

    def get_stroke_name(self, stroke_id: int) -> Optional[str]:
        """Get stroke name by ID."""
        info = self._id_to_stroke.get(stroke_id)
        return info["name"] if info else None

    def get_strokes_by_type(self, stroke_type: str) -> list[dict]:
        """Get all strokes of a given type."""
        ids = self._type_to_ids.get(stroke_type, [])
        return [self._id_to_stroke[i] for i in ids]

    def get_char_strokes(self, char: str) -> Optional[list[int]]:
        """Get stroke ID sequence for a character. Returns None if not found."""
        return self._char_to_strokes.get(char)

    def get_char_strokes_with_names(self, char: str) -> Optional[list[str]]:
        """Get stroke name sequence for a character. Returns None if not found."""
        ids = self.get_char_strokes(char)
        if ids is None:
            return None
        return [self.get_stroke_name(sid) for sid in ids]

    def get_all_chars(self) -> list[str]:
        """Return all characters in the taxonomy."""
        return list(self._char_to_strokes.keys())

    def get_stroke_count(self, char: str) -> Optional[int]:
        """Get stroke count for a character. Returns None if not found."""
        strokes = self.get_char_strokes(char)
        return len(strokes) if strokes is not None else None
