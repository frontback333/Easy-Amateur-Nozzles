import math
import unittest
from angelino import AngelinoCalculator, AngelinoInputs


class AngelinoCalculatorTest(unittest.TestCase):
    def test_generates_lip_and_truncated_plug(self):
        result = AngelinoCalculator().calculate(AngelinoInputs(
            chamber_pressure_mpa=3.5, exit_pressure_mpa=0.101325, spike_throat_radius_mm=20, throat_area_mm2=269.32157,
            gamma=1.22, truncation_percent=0, contour_points=40,
            lip_pipe_radius_mm=28, plug_column_length_mm=20, plug_column_radius_mm=16,
            plug_converging_length_mm=10, throat_gap_length_mm=2, lip_wall_thickness_mm=2,
        ))
        self.assertEqual(len(result.lip), 4)
        self.assertEqual(len(result.aerospike), 50)
        self.assertAlmostEqual(result.design_pressure_ratio, 3.5 / 0.101325)
        self.assertGreater(result.design_exit_mach, 1)
        self.assertGreater(result.throat_area_mm2, 0)
        self.assertGreater(result.lip_radius_mm, 20)
        self.assertEqual(result.lip[0][1], 28)
        self.assertEqual(result.aerospike[0][1], 16)
        self.assertGreater(result.throat_gap_length_mm, 0)
        self.assertNotEqual(result.lip[-1], result.aerospike[2])
        self.assertEqual(result.lip[0][0], result.aerospike[0][0])
        self.assertEqual(result.throat_gap_length_mm, 2)
        self.assertLess(result.aerospike[2][0], result.lip[2][0])
        self.assertAlmostEqual(result.aerospike[2][0] - result.aerospike[1][0], 10)
        self.assertAlmostEqual(math.degrees(math.atan2(result.lip[2][1] - result.lip[1][1], result.lip[2][0] - result.lip[1][0])), -result.throat_angle_deg)
        self.assertAlmostEqual(math.degrees(math.atan2(result.lip[3][1] - result.lip[2][1], result.lip[3][0] - result.lip[2][0])), -result.throat_angle_deg)
        self.assertLess(result.aerospike[-1][1], result.aerospike[0][1])

    def test_full_plug_reaches_the_centerline(self):
        result = AngelinoCalculator().calculate(AngelinoInputs(
            chamber_pressure_mpa=3.5, exit_pressure_mpa=0.101325, spike_throat_radius_mm=20, throat_area_mm2=269.32157,
            gamma=1.22, truncation_percent=0, contour_points=40,
            lip_pipe_radius_mm=28, plug_column_length_mm=20, plug_column_radius_mm=16,
            plug_converging_length_mm=10, throat_gap_length_mm=2, lip_wall_thickness_mm=2,
        ))
        self.assertLess(result.aerospike[-1][1], 0.002)

    def test_throat_length_does_not_change_lip_angle(self):
        calculator = AngelinoCalculator()
        common = dict(chamber_pressure_mpa=3.5, exit_pressure_mpa=0.101325, spike_throat_radius_mm=20,
                      throat_area_mm2=269.32157, gamma=1.22, truncation_percent=0, contour_points=40,
                      lip_pipe_radius_mm=28, plug_column_length_mm=20,
                      plug_column_radius_mm=16, lip_wall_thickness_mm=2)
        zero = calculator.calculate(AngelinoInputs(**common, plug_converging_length_mm=10, throat_gap_length_mm=0))
        short = calculator.calculate(AngelinoInputs(**common, plug_converging_length_mm=25, throat_gap_length_mm=2))
        self.assertEqual(zero.throat_gap_length_mm, 0)
        self.assertEqual(zero.lip[-1][0], 0)
        self.assertNotEqual(zero.lip[-1], zero.aerospike[2])
        self.assertAlmostEqual(zero.aerospike[2][1], 20)
        self.assertAlmostEqual(
            zero.aerospike[2][0],
            -(zero.lip[-1][1] - zero.aerospike[2][1]) * math.tan(math.radians(zero.throat_angle_deg)),
        )
        self.assertAlmostEqual(
            math.pi * (zero.lip[-1][1] ** 2 - zero.aerospike[2][1] ** 2) / math.cos(math.radians(zero.throat_angle_deg)),
            269.32157,
        )
        self.assertEqual(short.aerospike[10:], zero.aerospike[2:])
        self.assertAlmostEqual(math.degrees(math.atan2(short.lip[-1][1] - short.lip[-2][1], short.lip[-1][0] - short.lip[-2][0])), -short.throat_angle_deg)
        theta = math.radians(short.throat_angle_deg)
        for index, (_, plug_radius) in enumerate(short.aerospike[2:11]):
            lip_radius = short.lip[-1][1] + 2 * (1 - index / 8) * math.tan(theta)
            self.assertAlmostEqual(math.pi * (lip_radius ** 2 - plug_radius ** 2) / math.cos(theta), 269.32157)

    def test_truncation_percent_removes_the_contour_tail(self):
        common = dict(chamber_pressure_mpa=3.5, exit_pressure_mpa=0.101325, spike_throat_radius_mm=20,
                      throat_area_mm2=269.32157, gamma=1.22, contour_points=40, lip_pipe_radius_mm=28,
                      plug_column_length_mm=20, plug_column_radius_mm=16, plug_converging_length_mm=10,
                      throat_gap_length_mm=0, lip_wall_thickness_mm=2)
        calculator = AngelinoCalculator()
        full = calculator.calculate(AngelinoInputs(**common, truncation_percent=0))
        cut = calculator.calculate(AngelinoInputs(**common, truncation_percent=80))
        all_cut = calculator.calculate(AngelinoInputs(**common, truncation_percent=100))
        self.assertEqual(len(full.aerospike), 42)
        self.assertLess(len(cut.aerospike), len(full.aerospike))
        self.assertGreater(cut.aerospike[-1][1], full.aerospike[-1][1])
        self.assertEqual(len(all_cut.aerospike), 3)


if __name__ == "__main__":
    unittest.main()
