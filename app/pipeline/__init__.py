"""Shared constants for the import pipeline."""
import re

# Single source of truth for audio file extensions used by detector, runner, and probe.
AUDIO_EXTS: frozenset[str] = frozenset({
    ".flac", ".ape", ".wv", ".mp3", ".m4a", ".ogg", ".opus",
    ".wav", ".aiff", ".dsf", ".dff",
})

# Matches disc subdirectory names: "CD1", "Disc 2", "disk3", etc.
DISC_PATTERN: re.Pattern[str] = re.compile(r"^(?:cd|disc|disk)\s*\d+$", re.IGNORECASE)
