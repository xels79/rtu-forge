from rtuforge.crc import append_crc, apply_crc_mode, has_valid_crc


def test_known_pb01_read_crc():
    payload = bytes.fromhex("01 03 00 65 00 01")
    assert append_crc(payload).hex(" ").upper() == "01 03 00 65 00 01 94 15"


def test_auto_crc_keeps_valid_frame():
    frame = bytes.fromhex("01 03 00 65 00 01 94 15")
    assert has_valid_crc(frame)
    assert apply_crc_mode(frame, "auto") == frame


def test_auto_crc_appends_missing_crc():
    payload = bytes.fromhex("01 03 00 65 00 01")
    assert apply_crc_mode(payload, "auto") == bytes.fromhex("01 03 00 65 00 01 94 15")
