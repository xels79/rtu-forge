from rtuforge.crc import append_crc
from rtuforge.modbus import decode_response


def test_decode_fc03_register_response():
    decoded = decode_response(append_crc(bytes.fromhex("01 03 02 00 05")))
    assert decoded.slave == 1
    assert decoded.function == 3
    assert decoded.crc_valid is True
    assert decoded.byte_count == 2
    assert decoded.registers == (5,)


def test_decode_fc04_multiple_registers():
    decoded = decode_response(append_crc(bytes.fromhex("01 04 06 00 05 00 02 01 F4")))
    assert decoded.function == 4
    assert decoded.registers == (5, 2, 500)


def test_decode_fc06_echo_response():
    decoded = decode_response(append_crc(bytes.fromhex("01 06 00 65 00 05")))
    assert decoded.crc_valid is True
    assert decoded.address == 0x0065
    assert decoded.value == 5


def test_decode_exception_response():
    decoded = decode_response(append_crc(bytes.fromhex("01 83 02")))
    assert decoded.function == 3
    assert decoded.exception_code == 2
    assert decoded.exception_name == "Illegal Data Address"
    assert decoded.crc_valid is True


def test_decode_bad_crc():
    frame = bytearray(append_crc(bytes.fromhex("01 03 02 00 05")))
    frame[-1] ^= 0xFF
    assert decode_response(bytes(frame)).crc_valid is False


def test_decode_short_frame_never_raises():
    decoded = decode_response(b"\x01")
    assert decoded.slave == 1
    assert decoded.crc_valid is None
    assert decoded.too_short is True


def test_decode_four_byte_fragment_is_too_short():
    decoded = decode_response(bytes.fromhex("01 03 00 12"))
    assert decoded.slave == 1
    assert decoded.function == 3
    assert decoded.crc_valid is None
    assert decoded.too_short is True
