"""Angelino (1964) approximate axisymmetric plug-nozzle calculation."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class AngelinoInputs:
    chamber_pressure_mpa: float
    design_altitude_m: float
    spike_throat_radius_mm: float
    gamma: float
    truncation_percent: float
    contour_points: int
    lip_pipe_length_mm: float
    lip_pipe_radius_mm: float
    plug_column_length_mm: float
    plug_column_radius_mm: float
    wall_thickness_mm: float


@dataclass(frozen=True)
class ContourResult:
    aerospike: list[tuple[float, float]]
    lip: list[tuple[float, float]]
    wall_thickness_mm: float
    design_pressure_ratio: float
    design_exit_mach: float
    throat_angle_deg: float
    throat_area_mm2: float
    lip_radius_mm: float


class AngelinoCalculator:
    """Angelino's 1964 approximate axisymmetric plug-nozzle contour."""

    @staticmethod
    def atmosphere_pressure_mpa(altitude_m: float) -> float:
        """1976 standard atmosphere, sufficient for a design-altitude pressure."""
        layers = ((0, 288.15, 101325.0, -0.0065), (11000, 216.65, 22632.06, 0.0),
                  (20000, 216.65, 5474.889, 0.001), (32000, 228.65, 868.0187, 0.0028),
                  (47000, 270.65, 110.9063, 0.0), (51000, 270.65, 66.93887, -0.0028),
                  (71000, 214.65, 3.956420, -0.002))
        h = min(max(altitude_m, 0.0), 84852.0)
        base_h, base_t, base_p, lapse = layers[-1]
        for candidate in layers:
            if h >= candidate[0]:
                base_h, base_t, base_p, lapse = candidate
            else:
                break
        g0, gas_constant = 9.80665, 287.05287
        if lapse:
            pressure = base_p * (1 + lapse * (h - base_h) / base_t) ** (-g0 / (gas_constant * lapse))
        else:
            pressure = base_p * math.exp(-g0 * (h - base_h) / (gas_constant * base_t))
        return pressure / 1_000_000

    @staticmethod
    def prandtl_meyer(mach: float, gamma: float) -> float:
        if mach <= 1:
            return 0.0
        return (math.sqrt((gamma + 1) / (gamma - 1)) * math.atan(
            math.sqrt((gamma - 1) * (mach * mach - 1) / (gamma + 1))
        ) - math.atan(math.sqrt(mach * mach - 1)))

    @staticmethod
    def area_ratio(mach: float, gamma: float) -> float:
        return (1 / mach) * ((1 + (gamma - 1) * mach * mach / 2) / ((gamma + 1) / 2)) ** (
            (gamma + 1) / (2 * (gamma - 1))
        )

    def calculate(self, value: AngelinoInputs) -> ContourResult:
        ambient_mpa = self.atmosphere_pressure_mpa(value.design_altitude_m)
        pressure_ratio = value.chamber_pressure_mpa / ambient_mpa
        gamma = value.gamma
        exit_mach = math.sqrt(2 * (pressure_ratio ** ((gamma - 1) / gamma) - 1) / (gamma - 1))
        theta_t = self.prandtl_meyer(exit_mach, gamma)
        rt = value.spike_throat_radius_mm
        exit_area_ratio = self.area_ratio(exit_mach, gamma)
        re = rt / math.sqrt(1 - math.cos(theta_t) / exit_area_ratio)
        if value.lip_pipe_radius_mm <= re:
            raise ValueError("Lip pipe radius must exceed the calculated Lip exit radius")
        throat_area = math.pi * (re * re - rt * rt) / math.cos(theta_t)

        dense_count = max(value.contour_points * 4, 80)
        full = []
        for index in range(dense_count):
            mach = 1 + (exit_mach - 1) * index / (dense_count - 1)
            theta = theta_t - self.prandtl_meyer(mach, gamma)
            mu = math.asin(1 / mach)
            epsilon = self.area_ratio(mach, gamma)
            radius_sq = re * re - (re * re - rt * rt) * epsilon * math.sin(mu + theta) / (
                math.sin(mu) * math.cos(theta_t)
            )
            radius = math.sqrt(max(radius_sq, 0.0))
            x = (re - radius) / math.tan(mu + theta)
            full.append((x, radius))

        lengths = [0.0]
        for first, second in zip(full, full[1:]):
            lengths.append(lengths[-1] + math.dist(first, second))
        cutoff = lengths[-1] * value.truncation_percent / 100
        kept = [point for point, length in zip(full, lengths) if length <= cutoff]
        if len(kept) < 2:
            kept = full[:2]
        indexes = [round(i * (len(kept) - 1) / (value.contour_points - 1)) for i in range(value.contour_points)]
        contour = [kept[index] for index in indexes]
        lip_turn_length = (value.lip_pipe_radius_mm - re) / math.tan(theta_t)
        lip = [
            (-(value.lip_pipe_length_mm + lip_turn_length), value.lip_pipe_radius_mm),
            (-lip_turn_length, value.lip_pipe_radius_mm),
            (0.0, re),
        ]
        contour_start_x, contour_start_r = contour[0]
        column_end_x = contour_start_x - value.plug_column_length_mm
        aerospike = [
            (column_end_x, value.plug_column_radius_mm),
            (contour_start_x, value.plug_column_radius_mm),
            (contour_start_x, contour_start_r),
            *contour[1:],
        ]
        return ContourResult(aerospike, lip, value.wall_thickness_mm, pressure_ratio, exit_mach,
                             math.degrees(theta_t), throat_area, re)
