# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2025 Thomas Krijnen <thomas@aecgeeks.com>
#
# This file is part of IfcOpenShell.
#
# IfcOpenShell is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcOpenShell is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.

# This file was generated with the assistance of an AI coding tool.

import math
from collections.abc import Sequence
from typing import NamedTuple, Optional, Union

import numpy as np

# Gauss-Legendre quadrature nodes and weights used to integrate the clothoid position functions
_gauss_legendre_points = np.polynomial.legendre.leggauss(32)


class HorizontalSegmentDefinition(NamedTuple):
    """
    Parameters of one horizontal alignment segment produced by the PI method solver.

    The fields mirror IfcAlignmentHorizontalSegment so a definition can be written to a file
    without further computation, but the definition itself is independent of any file. Directions
    are in radians, lengths and coordinates in the caller's length unit.
    """

    start_point: tuple[float, float]
    """(X, Y) of the segment start"""

    start_direction: float
    """direction of the tangent at the segment start, in radians"""

    start_radius_of_curvature: float
    """radius at the segment start; 0.0 for straight, positive curving left, negative curving right"""

    end_radius_of_curvature: float
    """radius at the segment end, with the same sign convention as start_radius_of_curvature"""

    segment_length: float
    """length of the segment along the curve"""

    predefined_type: str
    """IfcAlignmentHorizontalSegmentTypeEnum value: LINE, CLOTHOID, or CIRCULARARC"""

    start_dist_along: float = 0.0
    """distance along the alignment at the segment start"""

    start_cant: float = 0.0
    """cant at the segment start, applied to the rail on the outside of the curve"""

    end_cant: float = 0.0
    """cant at the segment end, applied to the rail on the outside of the curve"""

    raise_left_rail: bool = False
    """True when the outside of the curve is the left rail (a curve to the right)"""


def compute_clothoid_end(length: float, start_curvature: float, end_curvature: float) -> tuple[float, float, float]:
    """
    Computes the end point of a clothoid transition whose curvature varies linearly from
    start_curvature to end_curvature over length.

    The result (dx, dy, dtheta) is relative to the start of the transition, with the x-axis in the
    direction of the tangent at the start. Curvatures are signed: positive curving left, negative
    curving right. The position is computed with 32 point Gauss-Legendre quadrature of the clothoid
    integrals.

    :param length: length of the transition, measured along the curve
    :param start_curvature: curvature at the start (1/R, 0.0 for a straight)
    :param end_curvature: curvature at the end (1/R, 0.0 for a straight)
    :return: (dx, dy, dtheta) displacement and change in tangent direction over the transition
    """
    u, w = _gauss_legendre_points
    l = 0.5 * length * (u + 1.0)  # map quadrature points from (-1,1) onto (0,length)
    theta = start_curvature * l + (end_curvature - start_curvature) * l * l / (2.0 * length)
    dx = 0.5 * length * float(np.sum(w * np.cos(theta)))
    dy = 0.5 * length * float(np.sum(w * np.sin(theta)))
    dtheta = 0.5 * (start_curvature + end_curvature) * length
    return dx, dy, dtheta


def compute_horizontal_segment_end(segment: HorizontalSegmentDefinition) -> tuple[float, float, float]:
    """
    Computes the end point and end direction of a horizontal segment definition.

    Useful for checking position and direction continuity between consecutive segments: the result
    for one segment should match the start_point and start_direction of the next.

    :param segment: the segment definition
    :return: (x, y, direction) at the end of the segment, direction in radians
    """
    x, y = segment.start_point
    direction = segment.start_direction
    length = segment.segment_length

    if segment.predefined_type == "LINE":
        return (x + length * math.cos(direction), y + length * math.sin(direction), direction)

    start_curvature = 1.0 / segment.start_radius_of_curvature if segment.start_radius_of_curvature != 0.0 else 0.0
    end_curvature = 1.0 / segment.end_radius_of_curvature if segment.end_radius_of_curvature != 0.0 else 0.0

    if segment.predefined_type == "CIRCULARARC":
        dtheta = start_curvature * length
        dx = math.sin(dtheta) / start_curvature
        dy = (1.0 - math.cos(dtheta)) / start_curvature
    elif segment.predefined_type == "CLOTHOID":
        dx, dy, dtheta = compute_clothoid_end(length, start_curvature, end_curvature)
    else:
        raise NotImplementedError(f"unsupported predefined type '{segment.predefined_type}'")

    return (
        x + dx * math.cos(direction) - dy * math.sin(direction),
        y + dx * math.sin(direction) + dy * math.cos(direction),
        direction + dtheta,
    )


def _normalize_pi_curve(
    curve: Union[float, Sequence[float], dict[str, Union[float, bool]]],
) -> tuple[float, float, float, bool]:
    """
    Normalizes one element of the PI method solver's radii sequence into
    (radius, entry_length, exit_length, join_next).

    Accepted forms:

        R - radius of a circular curve

        (R, Lin, Lout) - radius with entry/exit clothoid spiral transition lengths

        {"radius": R, "lin": Lin, "lout": Lout, "join_next": bool} - the same R, Lin, Lout (lin and
        lout default to 0.0) plus an optional flag joining this curve directly to the curve at the
        next PI at a shared tangency point (a compound or reverse curve junction). See
        solve_horizontal_alignment_by_pi_method for the join_next semantics.

    :param curve: one element of radii
    :return: (radius, entry_length, exit_length, join_next)
    """
    if isinstance(curve, dict):
        unknown_keys = set(curve) - {"radius", "lin", "lout", "join_next"}
        if unknown_keys:
            raise ValueError(f"unrecognized keys in a radii dict element: {sorted(unknown_keys)}")
        if "radius" not in curve:
            raise ValueError("a radii dict element must include 'radius'")
        radius = float(curve["radius"])
        entry_length = float(curve.get("lin", 0.0))
        exit_length = float(curve.get("lout", 0.0))
        join_next = bool(curve.get("join_next", False))
    elif isinstance(curve, (int, float)):
        radius = float(curve)
        entry_length = 0.0
        exit_length = 0.0
        join_next = False
    else:
        if len(curve) != 3:
            raise ValueError(
                "each radii element should be a radius R, a (R, Lin, Lout) sequence, or a "
                "{'radius', 'lin', 'lout', 'join_next'} dict"
            )
        radius, entry_length, exit_length = (float(v) for v in curve)
        join_next = False

    if radius == 0.0 and (entry_length != 0.0 or exit_length != 0.0):
        raise ValueError("spiral transition lengths require a non-zero radius")

    return radius, entry_length, exit_length, join_next


def _check_pi_join_closure(
    previous_tangent_out: float, tangent_in: float, pi_to_pi_distance: float, pi_number: int
) -> None:
    """
    Validates that the tangent length claimed by a join_next curve on its shared leg, plus the
    tangent length claimed by the curve at the next PI, sum to exactly the PI-to-PI distance so the
    two curves meet at a single shared tangency point (a PCC or PRC) with no intermediate tangent
    run. Raises ValueError, stating the computed excess or shortfall and the PIs involved, when the
    curves cannot close this way.

    :param previous_tangent_out: tangent length the join_next curve claims on the shared leg
    :param tangent_in: tangent length the curve at the next PI claims on the shared leg
    :param pi_to_pi_distance: distance between the two PIs
    :param pi_number: 1-based number of the PI whose curve is the join target (the second of the pair)
    """
    total_tangent = previous_tangent_out + tangent_in
    tolerance = 1.0e-9 * pi_to_pi_distance
    excess = total_tangent - pi_to_pi_distance
    if abs(excess) <= tolerance:
        return
    if excess > 0.0:
        raise ValueError(
            f"compound/reverse curves at PI {pi_number - 1}-{pi_number} cannot close: tangent runs "
            f"T1+T2 = {total_tangent:.6g} exceed the {pi_to_pi_distance:.6g} PI-to-PI distance by "
            f"{excess:.6g}; reduce the radius or spiral lengths at PI {pi_number - 1} or PI {pi_number}"
        )
    raise ValueError(
        f"compound/reverse curves at PI {pi_number - 1}-{pi_number} cannot close: tangent runs "
        f"T1+T2 = {total_tangent:.6g} fall short of the {pi_to_pi_distance:.6g} PI-to-PI distance "
        f"by {-excess:.6g}; increase the radius or spiral lengths at PI {pi_number - 1} or PI {pi_number}"
    )


def solve_horizontal_alignment_by_pi_method(
    hpoints: Sequence[Sequence[float]],
    radii: Sequence[Union[float, Sequence[float], dict[str, Union[float, bool]]]],
    cants: Optional[Sequence[float]] = None,
) -> list[HorizontalSegmentDefinition]:
    """
    Solves a horizontal alignment defined by the PI layout method into a continuous sequence of
    segment definitions.

    This is a pure geometric computation: no file is read or written. Use
    layout_horizontal_alignment_by_pi_method to write the solution to an IfcAlignmentHorizontal
    layout, or consume the returned definitions directly, for example to preview an alignment in
    an interactive editor before committing it to a file.

    Each element of radii defines the transition at the corresponding PI and is one of:

        R - radius of a circular curve (tangent runs connect directly to the circular curve), or

        (R, Lin, Lout) - radius of a circular curve with clothoid spiral transition curves of length
        Lin ahead of the curve and Lout following the curve. When spiral transitions are used the
        circular curve shifts inward relative to the tangent runs so the tangent runs, spirals, and
        circular curve are continuous in position and direction. Lin and Lout can be 0.0 for a
        spiral-less connection on that end of the curve.

        {"radius": R, "lin": Lin, "lout": Lout, "join_next": bool} - a dict accepting the same R,
        Lin, Lout as above (lin and lout default to 0.0), plus an optional join_next flag. When
        join_next is True, the curve at this PI connects directly to the curve at the NEXT PI at a
        shared tangency point, with no intermediate tangent run: a PCC (point of compound curvature)
        when the two curves turn the same direction, a PRC (point of reverse curvature) when they
        turn opposite directions. The shared tangent line is the chord between the two PIs; each
        curve is solved against its own PI deflection as usual, and the solver additionally requires
        that the two curves' tangent lengths on the shared leg sum to exactly the PI-to-PI distance
        (within 1e-9 relative). Inputs that cannot close this way are refused with a ValueError
        stating the excess or shortfall and the PIs involved, so the caller knows what to adjust.
        Spiral transitions are not supported on the joined side of a join_next curve (the exit
        spiral of the joining curve and the entry spiral of the joined-into curve must both be
        0.0); spirals remain allowed on the outer, non-joined side of either curve. This is a
        documented limitation of the v1 implementation: a true spiral-to-spiral transition at a
        PCC/PRC junction is not supported.

    If cants is provided, each definition also carries the cant at the segment start and end,
    applied to the rail on the outside of the curve: zero cant on tangent runs, linearly varying
    cant over spiral transitions, and constant cant over circular curves. Because every horizontal
    segment carries its own cant values, a cant layout built from the definitions is one-for-one
    with the horizontal layout. Curves with a non-zero cant require entry and exit spiral
    transition curves so the cant profile is continuous.

    :param hpoints: (X, Y) pairs denoting the location of the horizontal PIs, including start (POB) and end (POE).
    :param radii: radius values to use for transition, optionally with spiral transition lengths and/or join_next
    :param cants: cant values, one per PI curve, applied to the outer rail
    :return: list of segment definitions, in order, continuous in position and direction
    """
    if not (len(hpoints) - 2 == len(radii)):
        raise ValueError("radii should have two fewer elements that hpoints")

    if cants is not None and not (len(cants) == len(radii)):
        raise ValueError("cants should have the same number of elements as radii")

    segments: list[HorizontalSegmentDefinition] = []

    xBT, yBT = hpoints[0]
    xPI, yPI = hpoints[1]

    i = 1
    dist_along = 0.0  # distance along the horizontal alignment at the start of the next segment

    previous_join_next = False  # True when the previous PI's curve joins directly into this one (PCC/PRC)
    previous_tangent_out = 0.0  # that previous curve's tangent length claim on the shared leg

    for curve_index, curve in enumerate(radii):
        radius, entry_length, exit_length, join_next = _normalize_pi_curve(curve)
        pi_number = curve_index + 1  # 1-based PI number, matching hpoints[pi_number]

        if join_next and curve_index == len(radii) - 1:
            raise ValueError(
                f"PI {pi_number} has join_next=True but is the last PI curve; there is no next " "curve to join it to"
            )
        if previous_join_next and entry_length != 0.0:
            raise ValueError(
                f"PI {pi_number - 1}-{pi_number} is a compound/reverse curve junction (join_next); "
                f"spiral transitions are not supported on the joined side of the curve at PI "
                f"{pi_number} (its entry spiral length must be 0.0); use a spiral only on its "
                "outer, non-joined side"
            )
        if join_next and exit_length != 0.0:
            raise ValueError(
                f"PI {pi_number} has join_next=True; spiral transitions are not supported on the "
                "joined side of a compound/reverse curve junction (its exit spiral length must be "
                "0.0); use a spiral only on its outer, non-joined side"
            )

        cant = float(cants[curve_index]) if cants is not None else 0.0
        if cant != 0.0 and (entry_length == 0.0 or exit_length == 0.0):
            raise ValueError(
                "curves with a non-zero cant require entry and exit spiral transition curves; "
                "otherwise the cant profile is discontinuous"
            )

        # back tangent
        dxBT = xPI - xBT
        dyBT = yPI - yBT
        angleBT = math.atan2(dyBT, dxBT)
        lengthBT = math.sqrt(dxBT * dxBT + dyBT * dyBT)

        # forward tangent
        i += 1
        xFT, yFT = hpoints[i]
        dxFT = xFT - xPI
        dyFT = yFT - yPI
        angleFT = math.atan2(dyFT, dxFT)

        delta = angleFT - angleBT

        # true PI-to-PI distance for the leg shared with a join_next curve; distinct from lengthBT,
        # which is measured from the previous curve's end point rather than from the previous PI
        if previous_join_next:
            prev_pi_x, prev_pi_y = hpoints[curve_index]
            cur_pi_x, cur_pi_y = hpoints[curve_index + 1]
            pi_to_pi_distance = math.hypot(cur_pi_x - prev_pi_x, cur_pi_y - prev_pi_y)

        if entry_length == 0.0 and exit_length == 0.0:
            # tangent runs connect directly to the circular curve
            tangent = abs(radius * math.tan(delta / 2))
            tangent_out_this_curve = tangent  # symmetric: PI-to-PC equals PI-to-PT for a plain arc
            if previous_join_next:
                _check_pi_join_closure(previous_tangent_out, tangent, pi_to_pi_distance, pi_number)

            lc = abs(radius * delta)

            radius *= delta / abs(delta)

            xPC = xPI - tangent * math.cos(angleBT)
            yPC = yPI - tangent * math.sin(angleBT)

            xPT = xPI + tangent * math.cos(angleFT)
            yPT = yPI + tangent * math.sin(angleFT)

            tangent_run = lengthBT - tangent

            # back tangent run; suppressed at a validated join_next junction, which places this
            # curve's PC exactly at the previous curve's PT with no intermediate tangent run
            if 1.0e-03 < tangent_run and not previous_join_next:
                segments.append(
                    HorizontalSegmentDefinition(
                        start_point=(xBT, yBT),
                        start_direction=angleBT,
                        start_radius_of_curvature=0.0,
                        end_radius_of_curvature=0.0,
                        segment_length=tangent_run,
                        predefined_type="LINE",
                        start_dist_along=dist_along,
                        raise_left_rail=delta < 0.0,
                    )
                )
                dist_along += tangent_run

            # circular curve
            if radius != 0.0:
                segments.append(
                    HorizontalSegmentDefinition(
                        start_point=(xPC, yPC),
                        start_direction=angleBT,
                        start_radius_of_curvature=float(radius),
                        end_radius_of_curvature=float(radius),
                        segment_length=lc,
                        predefined_type="CIRCULARARC",
                        start_dist_along=dist_along,
                        start_cant=cant,
                        end_cant=cant,
                        raise_left_rail=delta < 0.0,
                    )
                )
                dist_along += lc
        else:
            # tangent runs connect to the circular curve with clothoid spiral transition curves.
            # normalize the deflection angle onto (-pi, pi)
            delta = math.atan2(math.sin(delta), math.cos(delta))
            if delta == 0.0:
                raise ValueError("PI deflection angle is zero; spiral transitions cannot be created")

            R = abs(radius)
            s = 1.0 if 0.0 < delta else -1.0  # +1 curve to the left, -1 curve to the right
            theta1 = entry_length / (2.0 * R)  # deflection of the entry spiral
            theta2 = exit_length / (2.0 * R)  # deflection of the exit spiral
            theta_c = abs(delta) - theta1 - theta2  # deflection of the circular curve
            if theta_c < 0.0:
                raise ValueError(
                    "spiral transition curves are too long; their combined deflection exceeds the PI deflection angle"
                )
            lc = R * theta_c

            # compose the displacement from the start of the entry spiral (TS) to the end of the
            # exit spiral (ST), in a frame with the x-axis along the back tangent.
            # pieces are computed for a curve to the left and mirrored by s.
            pieces = []
            if 0.0 < entry_length:
                pieces.append(compute_clothoid_end(entry_length, 0.0, 1.0 / R))
            pieces.append((R * math.sin(theta_c), R * (1.0 - math.cos(theta_c)), theta_c))
            if 0.0 < exit_length:
                pieces.append(compute_clothoid_end(exit_length, 1.0 / R, 0.0))

            x = 0.0
            y = 0.0
            direction = 0.0
            for dx_, dy_, dtheta_ in pieces:
                x += dx_ * math.cos(direction) - s * dy_ * math.sin(direction)
                y += dx_ * math.sin(direction) + s * dy_ * math.cos(direction)
                direction += s * dtheta_

            # locate TS on the back tangent and ST on the forward tangent so that the curve ends on
            # the forward tangent. this accounts for the inward shift of the circular curve.
            ts_to_pi = x - y / math.tan(delta)  # distance from TS to the PI, along the back tangent
            pi_to_st = y / math.sin(delta)  # distance from the PI to ST, along the forward tangent
            tangent_out_this_curve = pi_to_st
            if previous_join_next:
                _check_pi_join_closure(previous_tangent_out, ts_to_pi, pi_to_pi_distance, pi_number)

            tangent_run = lengthBT - ts_to_pi

            # back tangent run; suppressed at a validated join_next junction, which places this
            # curve's TS/PC exactly at the previous curve's PT with no intermediate tangent run
            if 1.0e-03 < tangent_run and not previous_join_next:
                segments.append(
                    HorizontalSegmentDefinition(
                        start_point=(xBT, yBT),
                        start_direction=angleBT,
                        start_radius_of_curvature=0.0,
                        end_radius_of_curvature=0.0,
                        segment_length=tangent_run,
                        predefined_type="LINE",
                        start_dist_along=dist_along,
                        raise_left_rail=delta < 0.0,
                    )
                )
                dist_along += tangent_run

            signed_radius = s * R
            cur_x = xPI - ts_to_pi * math.cos(angleBT)
            cur_y = yPI - ts_to_pi * math.sin(angleBT)
            cur_direction = angleBT

            # entry spiral
            if 0.0 < entry_length:
                segments.append(
                    HorizontalSegmentDefinition(
                        start_point=(cur_x, cur_y),
                        start_direction=cur_direction,
                        start_radius_of_curvature=0.0,
                        end_radius_of_curvature=signed_radius,
                        segment_length=entry_length,
                        predefined_type="CLOTHOID",
                        start_dist_along=dist_along,
                        start_cant=0.0,
                        end_cant=cant,
                        raise_left_rail=delta < 0.0,
                    )
                )
                dist_along += entry_length

                dx_, dy_, dtheta_ = compute_clothoid_end(entry_length, 0.0, 1.0 / R)
                cur_x += dx_ * math.cos(cur_direction) - s * dy_ * math.sin(cur_direction)
                cur_y += dx_ * math.sin(cur_direction) + s * dy_ * math.cos(cur_direction)
                cur_direction += s * dtheta_

            # circular curve
            if 1.0e-03 < lc:
                segments.append(
                    HorizontalSegmentDefinition(
                        start_point=(cur_x, cur_y),
                        start_direction=cur_direction,
                        start_radius_of_curvature=signed_radius,
                        end_radius_of_curvature=signed_radius,
                        segment_length=lc,
                        predefined_type="CIRCULARARC",
                        start_dist_along=dist_along,
                        start_cant=cant,
                        end_cant=cant,
                        raise_left_rail=delta < 0.0,
                    )
                )
                dist_along += lc

            cur_x += R * math.sin(theta_c) * math.cos(cur_direction) - s * R * (1.0 - math.cos(theta_c)) * math.sin(
                cur_direction
            )
            cur_y += R * math.sin(theta_c) * math.sin(cur_direction) + s * R * (1.0 - math.cos(theta_c)) * math.cos(
                cur_direction
            )
            cur_direction += s * theta_c

            # exit spiral
            if 0.0 < exit_length:
                segments.append(
                    HorizontalSegmentDefinition(
                        start_point=(cur_x, cur_y),
                        start_direction=cur_direction,
                        start_radius_of_curvature=signed_radius,
                        end_radius_of_curvature=0.0,
                        segment_length=exit_length,
                        predefined_type="CLOTHOID",
                        start_dist_along=dist_along,
                        start_cant=cant,
                        end_cant=0.0,
                        raise_left_rail=delta < 0.0,
                    )
                )
                dist_along += exit_length

            xPT = xPI + pi_to_st * math.cos(angleFT)
            yPT = yPI + pi_to_st * math.sin(angleFT)

        xBT = xPT
        yBT = yPT
        xPI = xFT
        yPI = yFT

        previous_join_next = join_next
        previous_tangent_out = tangent_out_this_curve

    # done processing radii
    # last tangent run
    dx = xPI - xBT
    dy = yPI - yBT
    angleBT = math.atan2(dy, dx)
    tangent_run = math.sqrt(dx * dx + dy * dy)

    if 1.0e-03 < tangent_run:
        segments.append(
            HorizontalSegmentDefinition(
                start_point=(xBT, yBT),
                start_direction=angleBT,
                start_radius_of_curvature=0.0,
                end_radius_of_curvature=0.0,
                segment_length=tangent_run,
                predefined_type="LINE",
                start_dist_along=dist_along,
            )
        )

    return segments
