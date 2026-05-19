from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"


def sat_id(plane_idx: int, sat_idx: int) -> str:
    return f"P{plane_idx:02d}S{sat_idx:02d}"


def ring_distance(a: int, b: int, modulo: int) -> int:
    direct = abs(a - b)
    return min(direct, modulo - direct)


def add_window(
    windows: list[dict[str, object]],
    src: str,
    dst: str,
    link_type: str,
    t_start_s: float,
    t_end_s: float,
    distance_km: float,
    capacity_mbps: float,
    risk: float,
) -> None:
    if t_end_s <= t_start_s:
        return

    windows.append(
        {
            "src": src,
            "dst": dst,
            "link_type": link_type,
            "t_start_s": round(t_start_s, 3),
            "t_end_s": round(t_end_s, 3),
            "prop_delay_s": round(distance_km / 299792.458, 6),
            "distance_km": round(distance_km, 3),
            "capacity_mbps": round(capacity_mbps, 3),
            "risk": round(max(0.0, min(risk, 0.999999)), 6),
        }
    )


def generate_wlt(
    planes: int,
    sats_per_plane: int,
    duration_s: float,
    step_s: float,
    altitude_km: float,
    inclination_deg: float,
    intra_plane_range_km: float,
    inter_plane_range_km: float,
    walker_phase: int,
) -> dict[str, object]:
    nodes = [sat_id(plane_idx, sat_idx) for plane_idx in range(planes) for sat_idx in range(sats_per_plane)]
    windows: list[dict[str, object]] = []

    phase_fraction = walker_phase / max(1, sats_per_plane)
    base_radius_km = 6371.0 + altitude_km

    for plane_idx in range(planes):
        for sat_idx in range(sats_per_plane):
            src = sat_id(plane_idx, sat_idx)

            for offset in (-1, 1):
                dst_sat_idx = (sat_idx + offset) % sats_per_plane
                dst = sat_id(plane_idx, dst_sat_idx)
                angular_sep = 2.0 * math.pi / sats_per_plane
                chord_km = 2.0 * base_radius_km * math.sin(angular_sep / 2.0)
                if chord_km <= intra_plane_range_km:
                    risk = 0.72 + 0.08 * (abs(offset) / 1.0) + 0.02 * abs(math.sin((sat_idx + 1) * angular_sep))
                    add_window(
                        windows=windows,
                        src=src,
                        dst=dst,
                        link_type="intra_plane",
                        t_start_s=0.0,
                        t_end_s=duration_s,
                        distance_km=chord_km,
                        capacity_mbps=1800.0,
                        risk=risk,
                    )

            for plane_offset in (-1, 1):
                neighbor_plane = (plane_idx + plane_offset) % planes
                phase_shift = phase_fraction * (neighbor_plane - plane_idx)
                aligned_sat = (sat_idx + round(phase_shift)) % sats_per_plane
                candidates = [aligned_sat]
                if ring_distance(sat_idx, aligned_sat, sats_per_plane) > 0:
                    candidates.append((aligned_sat + 1) % sats_per_plane)

                for dst_sat_idx in candidates:
                    dst = sat_id(neighbor_plane, dst_sat_idx)
                    cross_track_factor = 0.42 + 0.58 * abs(math.sin((sat_idx - dst_sat_idx) * math.pi / sats_per_plane))
                    plane_factor = abs(math.sin((plane_idx - neighbor_plane) * math.pi / planes))
                    distance_km = 1200.0 + 5200.0 * (0.35 * cross_track_factor + 0.65 * plane_factor)
                    if distance_km > inter_plane_range_km:
                        continue

                    visibility_bias = 1.0 - min(1.0, distance_km / inter_plane_range_km)
                    if visibility_bias >= 0.58:
                        t_start_s = 0.0
                    else:
                        t_start_s = round((0.58 - visibility_bias) * duration_s * 0.85, 3)
                    t_end_s = round(duration_s - max(0.0, t_start_s * 0.6667), 3)

                    risk = 0.32 + 0.68 * (distance_km / inter_plane_range_km)
                    add_window(
                        windows=windows,
                        src=src,
                        dst=dst,
                        link_type="inter_plane",
                        t_start_s=t_start_s,
                        t_end_s=t_end_s,
                        distance_km=distance_km,
                        capacity_mbps=1200.0,
                        risk=risk,
                    )

    windows.sort(key=lambda item: (item["t_start_s"], item["src"], item["dst"]))
    payload = {
        "metadata": {
            "model": "simplified_walker_delta_wlt",
            "altitude_km": altitude_km,
            "inclination_deg": inclination_deg,
            "walker_phase": walker_phase,
            "planes": planes,
            "sats_per_plane": sats_per_plane,
            "duration_s": duration_s,
            "step_s": step_s,
            "intra_plane_range_km": intra_plane_range_km,
            "inter_plane_range_km": inter_plane_range_km,
            "node_count": len(nodes),
            "directed_link_templates": planes * sats_per_plane * 4,
            "window_count": len(windows),
        },
        "nodes": nodes,
        "windows": windows,
    }
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a simplified Window Link Table for GRP prototyping.")
    parser.add_argument("--planes", type=int, default=6, help="Number of orbital planes.")
    parser.add_argument("--sats-per-plane", type=int, default=8, help="Satellites per orbital plane.")
    parser.add_argument("--duration-s", type=float, default=1200.0, help="Simulation horizon.")
    parser.add_argument("--step-s", type=float, default=30.0, help="Nominal discretization step retained in metadata.")
    parser.add_argument("--altitude-km", type=float, default=550.0, help="Nominal orbit altitude.")
    parser.add_argument("--inclination-deg", type=float, default=53.0, help="Nominal orbit inclination.")
    parser.add_argument("--intra-plane-range-km", type=float, default=6500.0, help="Max intra-plane contact range.")
    parser.add_argument("--inter-plane-range-km", type=float, default=7000.0, help="Max inter-plane contact range.")
    parser.add_argument("--walker-phase", type=int, default=1, help="Walker phase parameter.")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "wlt_demo.json", help="Output WLT JSON.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = generate_wlt(
        planes=args.planes,
        sats_per_plane=args.sats_per_plane,
        duration_s=args.duration_s,
        step_s=args.step_s,
        altitude_km=args.altitude_km,
        inclination_deg=args.inclination_deg,
        intra_plane_range_km=args.intra_plane_range_km,
        inter_plane_range_km=args.inter_plane_range_km,
        walker_phase=args.walker_phase,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "nodes": len(payload["nodes"]),
                "windows": len(payload["windows"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
