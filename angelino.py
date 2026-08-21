"""Angelino (1964) approximate axisymmetric plug-nozzle calculation."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class AngelinoInputs:
    chamber_pressure_mpa: float
    exit_pressure_mpa: float
    spike_throat_radius_mm: float
    throat_area_mm2: float
    gamma: float
    truncation_percent: float
    contour_points: int
    lip_pipe_radius_mm: float
    plug_column_length_mm: float
    plug_column_radius_mm: float
    plug_converging_length_mm: float
    throat_gap_length_mm: float
    lip_wall_thickness_mm: float


@dataclass(frozen=True)
class ContourResult:
    aerospike: list[tuple[float, float]]
    lip: list[tuple[float, float]]
    lip_wall_thickness_mm: float
    design_pressure_ratio: float
    design_exit_mach: float
    throat_angle_deg: float
    throat_area_mm2: float
    lip_radius_mm: float
    base_radius_mm: float
    throat_gap_length_mm: float


class AngelinoCalculator:
    """Angelino's 1964 approximate axisymmetric plug-nozzle contour."""

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
        if value.exit_pressure_mpa <= 0:
            raise ValueError("Exit pressure must be positive")
        pressure_ratio = value.chamber_pressure_mpa / value.exit_pressure_mpa
        gamma = value.gamma
        exit_mach = math.sqrt(2 * (pressure_ratio ** ((gamma - 1) / gamma) - 1) / (gamma - 1))
        theta_t = self.prandtl_meyer(exit_mach, gamma)
        rt = value.spike_throat_radius_mm
        exit_area_ratio = self.area_ratio(exit_mach, gamma)
        throat_area = value.throat_area_mm2
        # Angelino Eq. (2): A_t is normal to the inclined sonic flow at AB.
        re = math.sqrt(rt * rt + throat_area * math.cos(theta_t) / math.pi)
        if value.lip_pipe_radius_mm <= re:
            raise ValueError("Lip pipe radius must exceed the calculated Lip exit radius")
        base_radius_sq = re * re - exit_area_ratio * throat_area / math.pi
        if base_radius_sq < -1e-7:
            raise ValueError("Throat area is too large for this Plug radius and design pressure ratio")
        base_radius = math.sqrt(max(0.0, base_radius_sq))

        dense_count = value.contour_points
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
        cutoff = lengths[-1] * (1 - value.truncation_percent / 100)
        contour = [point for point, length in zip(full, lengths) if length <= cutoff]
        throat_hold = value.throat_gap_length_mm
        throat_area_factor = throat_area * math.cos(theta_t) / math.pi

        def throat_point(distance: float) -> tuple[tuple[float, float], tuple[float, float]]:
            """Lip and Plug points on one constant-A_t throat station."""
            lip_point = (-distance, re + distance * math.tan(theta_t))
            plug_radius = math.sqrt(lip_point[1] ** 2 - throat_area_factor)
            plug_point = (lip_point[0] - (lip_point[1] - plug_radius) * math.tan(theta_t), plug_radius)
            return lip_point, plug_point

        lip_throat_start, plug_throat_start = throat_point(throat_hold)
        lip_turn_start_x = lip_throat_start[0] - (value.lip_pipe_radius_mm - lip_throat_start[1]) / math.tan(theta_t)
        if lip_turn_start_x > lip_throat_start[0]:
            raise ValueError("Lip pipe radius must exceed the throat-hold Lip radius")
        plug_converging_start_x = plug_throat_start[0] - value.plug_converging_length_mm
        plug_start_x = plug_converging_start_x - value.plug_column_length_mm
        if plug_start_x > lip_turn_start_x:
            raise ValueError("Plug column + converging length is shorter than the required Lip converging length")

        # l_t=0 returns the original A--B geometry and the unshifted M=1..M_e contour.
        lip = [(plug_start_x, value.lip_pipe_radius_mm), (lip_turn_start_x, value.lip_pipe_radius_mm), lip_throat_start]
        if throat_hold:
            lip.append((0.0, re))
        # ponytail: straight Plug convergence is a placeholder for the later MOC/fillet solver.
        aerospike = [
            (plug_start_x, value.plug_column_radius_mm),
            (plug_converging_start_x, value.plug_column_radius_mm),
            plug_throat_start,
        ]
        if throat_hold:
            for index in range(1, 9):
                _, plug_point = throat_point(throat_hold * (1 - index / 8))
                aerospike.append(plug_point)
        aerospike += contour[1:]
        return ContourResult(aerospike, lip, value.lip_wall_thickness_mm, pressure_ratio, exit_mach,
                             math.degrees(theta_t), throat_area, re, base_radius, value.throat_gap_length_mm)
