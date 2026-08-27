import pytest

from rtuforge.formatting import parse_hex_bytes


def test_parse_hex_bytes_accepts_0x_and_plain():
    assert parse_hex_bytes("01 0x03 00 65") == bytes.fromhex("01 03 00 65")


def test_parse_hex_rejects_non_byte():
    with pytest.raises(ValueError):
        parse_hex_bytes("0103")
