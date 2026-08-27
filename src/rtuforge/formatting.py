from __future__ import annotations

from datetime import datetime


def parse_hex_bytes(text: str) -> bytes:
    tokens = text.replace(",", " ").split()
    if not tokens:
        raise ValueError("No HEX bytes supplied")
    values: list[int] = []
    for token in tokens:
        clean = token[2:] if token.lower().startswith("0x") else token
        if len(clean) > 2:
            raise ValueError(f"Not a byte: {token}")
        values.append(int(clean, 16))
    return bytes(values)


def hex_line(data: bytes, uppercase: bool = True) -> str:
    text = " ".join(f"{byte:02X}" for byte in data)
    return text if uppercase else text.lower()


def prefix(timestamps: bool) -> str:
    if not timestamps:
        return ""
    return datetime.now().strftime("[%H:%M:%S.%f]")[:-3] + " "
