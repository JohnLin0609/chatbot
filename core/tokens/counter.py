"""tiktoken-based token counting for window/budget decisions.

Counts are heuristic for non-OpenAI providers but fine for budgeting. Encoders
are cached per encoding name; if tiktoken can't load (e.g. offline), falls back
to a chars/4 estimate.
"""

from functools import lru_cache

# A small per-message overhead (role + framing), mirroring chat-format costs.
_PER_TURN_OVERHEAD = 4


@lru_cache(maxsize=8)
def _get_encoder(encoding_name: str):
    try:
        import tiktoken

        return tiktoken.get_encoding(encoding_name)
    except Exception:  # noqa: BLE001 — offline / missing data file
        return None


class TokenCounter:
    def __init__(self, encoding_name: str = "o200k_base") -> None:
        self._encoding_name = encoding_name
        self._encoder = _get_encoder(encoding_name)

    def count_text(self, text: str) -> int:
        if not text:
            return 0
        if self._encoder is None:
            return max(1, len(text) // 4)
        return len(self._encoder.encode(text))

    def count_turn(self, turn: dict) -> int:
        return self.count_text(turn.get("content", "")) + _PER_TURN_OVERHEAD

    def count_turns(self, turns: list[dict]) -> int:
        return sum(self.count_turn(t) for t in turns)

    # --- token-id access for chunking (falls back to char slices offline) ---
    def encode(self, text: str) -> list[int]:
        if self._encoder is None:
            return [ord(c) for c in text]  # char-based fallback
        return self._encoder.encode(text)

    def decode(self, tokens: list[int]) -> str:
        if self._encoder is None:
            return "".join(chr(t) for t in tokens)
        return self._encoder.decode(tokens)
