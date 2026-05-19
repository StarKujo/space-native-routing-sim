from __future__ import annotations

import argparse
import json
import math
from collections import deque
from pathlib import Path

import grp_router


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"


def active_at(window: grp_router.ContactWindow, time_s: float) -> bool:
    return window.t_start_s <= time_s <= window.t_end_s


def build_active_adjacency(
    nodes: list[str],
    windows: list[grp_router.ContactWindow],
    time_s: float,
) -> dict[str, list[grp_router.ContactWindow]]:
    adjacency: dict[str, list[grp_router.ContactWindow]] = {node: [] for node in nodes}
    for window in windows:
        if active_at(window, time_s):
            adjacency.setdefault(window.src, []).append(window)
    for src in adjacency:
        adjacency[src].sort(key=lambda item: (item.dst, item.prop_delay_s, item.index))
    return adjacency


def reconstruct_static_path(
    previous: dict[str, tuple[str, grp_router.ContactWindow]],
    src: str,
    dst: str,
) -> list[grp_router.ContactWindow]:
    if src == dst:
        return []
    if dst not in previous:
        raise RuntimeError("No feasible baseline path found in the selected topology snapshot.")

    path: list[grp_router.ContactWindow] = []
    cursor = dst
    while cursor != src:
        prev_node, window = previous[cursor]
        path.append(window)
        cursor = prev_node
    path.reverse()
    return path


def shortest_hop_path(
    adjacency: dict[str, list[grp_router.ContactWindow]],
    src: str,
    dst: str,
) -> list[grp_router.ContactWindow]:
    visited = {src}
    previous: dict[str, tuple[str, grp_router.ContactWindow]] = {}
    queue: deque[str] = deque([src])

    while queue:
        node = queue.popleft()
        if node == dst:
            break
        for window in adjacency.get(node, []):
            if window.dst in visited:
                continue
            visited.add(window.dst)
            previous[window.dst] = (node, window)
            queue.append(window.dst)

    return reconstruct_static_path(previous, src, dst)


def shortest_delay_path(
    adjacency: dict[str, list[grp_router.ContactWindow]],
    src: str,
    dst: str,
) -> list[grp_router.ContactWindow]:
    best: dict[str, tuple[float, int]] = {src: (0.0, 0)}
    previous: dict[str, tuple[str, grp_router.ContactWindow]] = {}
    queue: list[tuple[float, int, str]] = [(0.0, 0, src)]

    while queue:
        queue.sort()
        distance_s, hop_count, node = queue.pop(0)
        if node == dst:
            break
        if best.get(node) != (distance_s, hop_count):
            continue

        for window in adjacency.get(node, []):
            candidate = (distance_s + window.prop_delay_s, hop_count + 1)
            current = best.get(window.dst)
            if current is not None and current <= candidate:
                continue
            best[window.dst] = candidate
            previous[window.dst] = (node, window)
            queue.append((candidate[0], candidate[1], window.dst))

    return reconstruct_static_path(previous, src, dst)


def rollout_path(
    path_windows: list[grp_router.ContactWindow],
    src: str,
    dst: str,
    start_time_s: float,
    route_setup_s: float,
    max_arrival_s: float | None,
) -> dict[str, object]:
    current_time_s = start_time_s + route_setup_s
    hop_records: list[dict[str, object]] = []

    for window in path_windows:
        depart_s = max(current_time_s, window.t_start_s)
        if depart_s > window.t_end_s:
            raise RuntimeError(
                f"Baseline route became infeasible at window {window.index} "
                f"({window.src}->{window.dst}) because the contact closed before forwarding."
            )

        arrive_s = depart_s + window.prop_delay_s
        if max_arrival_s is not None and arrive_s > max_arrival_s:
            raise RuntimeError("Baseline route violates the configured arrival cutoff.")

        hop_records.append(
            {
                "src": window.src,
                "dst": window.dst,
                "link_type": window.link_type,
                "window_index": window.index,
                "window_start_s": window.t_start_s,
                "window_end_s": window.t_end_s,
                "depart_s": round(depart_s, 3),
                "arrive_s": round(arrive_s, 3),
                "prop_delay_s": window.prop_delay_s,
                "risk": window.risk,
                "capacity_mbps": window.capacity_mbps,
            }
        )
        current_time_s = arrive_s

    elapsed_s = current_time_s - start_time_s
    return {
        "src": src,
        "dst": dst,
        "start_time_s": start_time_s,
        "arrival_time_s": round(current_time_s, 3),
        "total_cost": round(elapsed_s, 6),
        "hop_count": len(path_windows),
        "path": hop_records,
        "setup_delay_s": round(route_setup_s, 6),
    }


def solve_aodv_like(
    nodes: list[str],
    windows: list[grp_router.ContactWindow],
    src: str,
    dst: str,
    start_time_s: float,
    max_arrival_s: float | None,
    route_setup_s: float,
) -> dict[str, object]:
    snapshot_time_s = start_time_s + route_setup_s
    adjacency = build_active_adjacency(nodes, windows, snapshot_time_s)
    path_windows = shortest_hop_path(adjacency, src, dst)
    result = rollout_path(path_windows, src, dst, start_time_s, route_setup_s, max_arrival_s)
    result["strategy"] = "aodv_like"
    result["snapshot_time_s"] = round(snapshot_time_s, 3)
    return result


def solve_quasi_static(
    nodes: list[str],
    windows: list[grp_router.ContactWindow],
    src: str,
    dst: str,
    start_time_s: float,
    max_arrival_s: float | None,
    ls_update_interval_s: float,
) -> dict[str, object]:
    if ls_update_interval_s <= 0:
        snapshot_time_s = start_time_s
    else:
        snapshot_time_s = math.floor(start_time_s / ls_update_interval_s) * ls_update_interval_s

    adjacency = build_active_adjacency(nodes, windows, snapshot_time_s)
    path_windows = shortest_delay_path(adjacency, src, dst)
    result = rollout_path(path_windows, src, dst, start_time_s, 0.0, max_arrival_s)
    result["strategy"] = "quasi_static"
    result["snapshot_time_s"] = round(snapshot_time_s, 3)
    result["route_age_s"] = round(start_time_s - snapshot_time_s, 6)
    result["ls_update_interval_s"] = ls_update_interval_s
    return result


def solve_cgr_like(
    nodes: list[str],
    windows: list[grp_router.ContactWindow],
    src: str,
    dst: str,
    start_time_s: float,
    max_arrival_s: float | None,
) -> dict[str, object]:
    result = grp_router.solve(
        nodes=nodes,
        windows=windows,
        src=src,
        dst=dst,
        start_time_s=start_time_s,
        max_arrival_s=max_arrival_s,
        weight_wait=1.0,
        weight_delay=1.0,
        weight_risk=0.0,
        weight_queue=0.0,
        weight_handover=0.0,
    )
    result["strategy"] = "cgr_like"
    return result


def solve(
    nodes: list[str],
    windows: list[grp_router.ContactWindow],
    src: str,
    dst: str,
    start_time_s: float,
    algorithm: str,
    max_arrival_s: float | None = None,
    route_setup_s: float = 0.03,
    ls_update_interval_s: float = 120.0,
) -> dict[str, object]:
    if src not in nodes:
        raise ValueError(f"Unknown src node: {src}")
    if dst not in nodes:
        raise ValueError(f"Unknown dst node: {dst}")

    if algorithm == "aodv_like":
        return solve_aodv_like(
            nodes=nodes,
            windows=windows,
            src=src,
            dst=dst,
            start_time_s=start_time_s,
            max_arrival_s=max_arrival_s,
            route_setup_s=route_setup_s,
        )
    if algorithm == "quasi_static":
        return solve_quasi_static(
            nodes=nodes,
            windows=windows,
            src=src,
            dst=dst,
            start_time_s=start_time_s,
            max_arrival_s=max_arrival_s,
            ls_update_interval_s=ls_update_interval_s,
        )
    if algorithm == "cgr_like":
        return solve_cgr_like(
            nodes=nodes,
            windows=windows,
            src=src,
            dst=dst,
            start_time_s=start_time_s,
            max_arrival_s=max_arrival_s,
        )
    raise ValueError(f"Unsupported baseline algorithm: {algorithm}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run simplified baseline routing on a WLT JSON.")
    parser.add_argument("--wlt", type=Path, default=OUTPUT_DIR / "wlt_demo.json", help="Input WLT JSON.")
    parser.add_argument(
        "--algorithm",
        type=str,
        choices=["aodv_like", "quasi_static", "cgr_like"],
        default="aodv_like",
        help="Baseline routing strategy.",
    )
    parser.add_argument("--src", type=str, default="P00S00", help="Source node.")
    parser.add_argument("--dst", type=str, default="", help="Destination node.")
    parser.add_argument("--start-time-s", type=float, default=0.0, help="Flow start time.")
    parser.add_argument("--max-arrival-s", type=float, default=0.0, help="Optional arrival cutoff; 0 disables it.")
    parser.add_argument("--route-setup-s", type=float, default=0.03, help="Reactive route discovery delay for AODV-like routing.")
    parser.add_argument("--ls-update-interval-s", type=float, default=120.0, help="Topology refresh period for quasi-static routing.")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "baseline_route_demo.json", help="Route JSON output.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    nodes, windows, metadata = grp_router.load_wlt(args.wlt)
    dst = args.dst or grp_router.default_destination(nodes)
    result = solve(
        nodes=nodes,
        windows=windows,
        src=args.src,
        dst=dst,
        start_time_s=args.start_time_s,
        algorithm=args.algorithm,
        max_arrival_s=args.max_arrival_s if args.max_arrival_s > 0 else None,
        route_setup_s=args.route_setup_s,
        ls_update_interval_s=args.ls_update_interval_s,
    )
    payload = {
        "metadata": {
            **metadata,
            "algorithm": args.algorithm,
        },
        "route": result,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "algorithm": args.algorithm, **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
