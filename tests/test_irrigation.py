import unittest

from rtuforge.irrigation import IrrigationController, Limits, Sample, State


class FakeHardware:
    def __init__(self):
        self.events = []
        self.current = Sample(1.5, 0, 0, False)

    def relay(self, channel, active):
        self.events.append(("relay", channel, active))

    def set_frequency(self, drive, percent):
        self.events.append(("frequency", drive, percent))

    def sample(self, drive):
        return self.current

    def precheck(self, drive):
        pass

    def confirm_off(self, channels):
        pass

    def drive_feedback(self, drive):
        return self.current.hz, self.current.running, self.current.fault


class TestIrrigation(unittest.TestCase):
    def setUp(self):
        self.time = [0.0]
        self.hw = FakeHardware()
        self.ctl = IrrigationController(
            self.hw, Limits(low_ready=1, low_min=.5,
                            high_ready=20, high_min=15, high_max=70),
            clock=lambda: self.time[0])

    def advance(self, sec):
        self.time[0] += sec
        return self.ctl.tick()

    def begin(self):
        self.ctl.start(1, 1, "broth", 35, drive=7, selector=19)
        for _ in range(3):
            self.ctl.tick()

    def test_start_and_stop_waits_for_zero(self):
        self.begin()
        self.assertIn(("relay", 9, True), self.hw.events)
        self.assertNotIn(("relay", 32, True), self.hw.events)
        self.advance(3)
        self.assertEqual(self.ctl.state, State.BOOST)
        self.advance(.2)
        self.advance(.2)
        self.assertIn(("relay", 32, True), self.hw.events)
        self.hw.current = Sample(1.4, 30, 16, True)
        self.advance(.5)
        self.assertEqual(self.ctl.state, State.RUNNING)
        self.ctl.stop()
        self.assertEqual(self.ctl.state, State.STOPPING)
        self.assertNotIn(("relay", 9, False), self.hw.events)
        self.advance(.5)
        self.assertNotIn(("relay", 9, False), self.hw.events)
        self.hw.current = Sample(1.4, 0, 0, False)
        self.advance(.5)
        self.assertEqual(self.ctl.state, State.IDLE)
        self.assertIn(("relay", 9, False), self.hw.events)

    def test_no_prime_pressure_fails_and_keeps_stand_valve(self):
        self.hw.current = Sample(.2, 0, 0, False)
        self.begin()
        self.advance(3)
        self.advance(11)
        self.assertEqual(self.ctl.state, State.STOPPING)
        self.assertTrue(self.ctl.fault_reason)
        self.assertNotIn(("relay", 9, False), self.hw.events)

    def test_overpressure_stops_drive(self):
        self.begin()
        self.hw.current = Sample(1.5, 75, 0, False)
        self.advance(.1)
        self.assertEqual(self.ctl.state, State.STOPPING)
        self.assertIn(("relay", 32, False), self.hw.events)

    def test_invalid_options(self):
        with self.assertRaises(ValueError):
            self.ctl.start(3, 1, "broth", 35, drive=7, selector=19)
        with self.assertRaises(ValueError):
            self.ctl.start(1, 1, "broth", 35, drive=9, selector=19)


if __name__ == "__main__":
    unittest.main()
