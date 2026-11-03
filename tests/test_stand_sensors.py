import unittest
from rtuforge.stand_sensors import low_pressure, high_pressure, ma_to_bar

class TestPressure(unittest.TestCase):
    def test_scale(self):
        self.assertEqual(low_pressure(4), 0)
        self.assertEqual(low_pressure(20), 6)
        self.assertEqual(high_pressure(12), 50)
        self.assertEqual(high_pressure(20), 100)

    def test_bad_signal(self):
        for ma in (0, 3, 21, float("nan")):
            with self.assertRaises(ValueError):
                ma_to_bar(ma, 100)

if __name__ == "__main__":
    unittest.main()
