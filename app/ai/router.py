"""Model routing: pick the cheapest model that can handle the input shape.

An image present anywhere in the request forces the vision model; pure text (a
fresh text log or an adjustment) uses the small, cheap text model.
"""
from __future__ import annotations

from app.config import get_settings


def pick_model(*, has_image: bool) -> str:
    settings = get_settings()
    return settings.vision_model if has_image else settings.text_model
