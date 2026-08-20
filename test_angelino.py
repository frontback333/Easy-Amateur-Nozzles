import unittest
import math

from angelino import AngelinoCalculator, AngelinoInputs


class AngelinoCalculatorTest(unittest.TestCase):
    def test_generates_lip_and_truncated_plug(self):
        result = AngelinoCalculator().calculate(AngelinoInputs(
            chamber_pressure_mpa=3.5, design_altitude_m=0, spike_throat_radius_mm=20,
            gamma=1.22, truncation_percent=80, contour_points=40, lip_pipe_length_mm=30,
            lip_pipe_radius_mm=28, plug_column_length_mm=20, plug_column_radius_mm=16,
            wall_thickness_mm=2,
        ))
        self.assertEqual(len(result.lip), 3)
        self.assertEqual(len(result.aerospike), 42)
        self.assertGreater(result.design_exit_mach, 1)
        self.assertGreater(result.throat_area_mm2, 0)
        self.assertGreater(result.lip_radius_mm, 20)
        self.assertEqual(result.lip[0][1], 28)
        self.assertEqual(result.aerospike[0][1], 16)
        dx = result.lip[2][0] - result.lip[1][0]
        dr = result.lip[2][1] - result.lip[1][1]
        self.assertAlmostEqual(math.degrees(math.atan2(abs(dr), dx)), result.throat_angle_deg, places=6)
        self.assertLess(result.aerospike[-1][1], result.aerospike[0][1])

    def test_full_plug_reaches_the_centerline(self):
        result = AngelinoCalculator().calculate(AngelinoInputs(
            chamber_pressure_mpa=3.5, design_altitude_m=0, spike_throat_radius_mm=20,
            gamma=1.22, truncation_percent=100, contour_points=40, lip_pipe_length_mm=30,
            lip_pipe_radius_mm=28, plug_column_length_mm=20, plug_column_radius_mm=16,
            wall_thickness_mm=2,
        ))
        self.assertLess(result.aerospike[-1][1], 1e-5)


if __name__ == "__main__":
    unittest.main()
