from __future__ import annotations

import argparse
import json
import random
import statistics
from dataclasses import replace
from pathlib import Path

import baseline_router
import grp_router


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a lightweight multi-flow routing simulation on a WLT.")
    parser.add_argument("--wlt", type=Path, default=OUTPUT_DIR / "wlt_demo.json", help="Input WLT JSON path.")
    parser.add_argument("--output", type=Path, default=Path(), help="Simulation output JSON.")
    parser.add_argument(
        "--algorithm",
        type=str,
        choices=["grp", "aodv_like", "quasi_static", "cgr_like"],
        default="grp",
        help="Routing algorithm used for all flows.",
    )
    parser.add_argument("--flow-count", type=int, default=24, help="Number of flows to generate.")
    parser.add_argument("--flow-size-mbits", type=float, default=120.0, help="Traffic volume per flow.")
    parser.add_argument("--seed", type=int, default=7, help="Random seed.")
    parser.add_argument("--weight-wait", type=float, default=1.0, help="Weight for waiting time.")
    parser.add_argument("--weight-delay", type=float, default=30.0, help="Weight for propagation delay.")
    parser.add_argument("--weight-risk", type=float, default=2.0, help="Weight for link risk.")
    parser.add_argument("--weight-queue", type=float, default=3.0, help="Weight for queue penalty.")
    parser.add_argument("--weight-handover", type=float, default=0.25, help="Handover penalty.")
    parser.add_argument("--route-setup-s", type=float, default=0.03, help="Reactive route discovery delay for AODV-like routing.")
    parser.add_argument("--ls-update-interval-s", type=float, default=120.0, help="Topology refresh period for quasi-static routing.")
    return parser.parse_args()


def choose_pairs(nodes: list[str], flow_count: int, seed: int) -> list[tuple[str, str]]:
    rng = random.Random(seed)
    pairs: list[tuple[str, str]] = []
    for _ in range(flow_count):
        src = rng.choice(nodes)
        dst = rng.choice(nodes)
        while dst == src:
            dst = rng.choice(nodes)
        pairs.append((src, dst))
    return pairs


def choose_start_times(duration_s: float, flow_count: int, seed: int) -> list[float]:
    rng = random.Random(seed + 1)
    upper = max(duration_s * 0.75, 1.0)
    return sorted(round(rng.uniform(0.0, upper), 3) for _ in range(flow_count))


def capacity_budget_mbits(window: grp_router.ContactWindow) -> float:
    duration_s = max(window.t_end_s - window.t_start_s, 1e-6)
    return window.capacity_mbps * duration_s


def attach_queue_penalty(
    windows: list[grp_router.ContactWindow],
    load_by_window: dict[int, float],
) -> list[grp_router.ContactWindow]:
    enriched: list[grp_router.ContactWindow] = []
    for window in windows:
        reserved = load_by_window.get(window.index, 0.0)
        utilization = reserved / capacity_budget_mbits(window)
        queue_penalty = min(utilization, 2.0)
        enriched.append(replace(window, queue_penalty=queue_penalty))
    return enriched


def percentile(sorted_values: list[float], ratio: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, max(0, int(round((len(sorted_values) - 1) * ratio))))
    return sorted_values[idx]


def default_output_path(algorithm: str) -> Path:
    return OUTPUT_DIR / f"{algorithm}_sim_demo.json"


def solve_route(
    algorithm: str,
    nodes: list[str],
    windows: list[grp_router.ContactWindow],
    src: str,
    dst: str,
    start_time_s: float,
    args: argparse.Namespace,
) -> dict[str, object]:
    if algorithm == "grp":
        return grp_router.solve(
            nodes=nodes,
            windows=windows,
            src=src,
            dst=dst,
            start_time_s=start_time_s,
            max_arrival_s=None,
            weight_wait=args.weight_wait,
            weight_delay=args.weight_delay,
            weight_risk=args.weight_risk,
            weight_queue=args.weight_queue,
            weight_handover=args.weight_handover,
        )

    return baseline_router.solve(
        nodes=nodes,
        windows=windows,
        src=src,
        dst=dst,
        start_time_s=start_time_s,
        algorithm=algorithm,
        max_arrival_s=None,
        route_setup_s=args.route_setup_s,
        ls_update_interval_s=args.ls_update_interval_s,
    )


def main() -> None:
    args = parse_args()
    if args.output == Path():
        args.output = default_output_path(args.algorithm)
    nodes, windows, metadata = grp_router.load_wlt(args.wlt)
    duration_s = float(metadata.get("duration_s", 0.0))
    pairs = choose_pairs(nodes, args.flow_count, args.seed)
    start_times = choose_start_times(duration_s, args.flow_count, args.seed)

    load_by_window: dict[int, float] = {}
    flow_records: list[dict[str, object]] = []
    delivered_delays: list[float] = []
    delivered_costs: list[float] = []
    delivered_hops: list[int] = []
    overload_events = 0

    for flow_id, ((src, dst), start_time_s) in enumerate(zip(pairs, start_times), start=1):
        windows_with_queue = attach_queue_penalty(windows, load_by_window)
        try:
            route = solve_route(
                algorithm=args.algorithm,
                nodes=nodes,
                windows=windows_with_queue,
                src=src,
                dst=dst,
                start_time_s=start_time_s,
                args=args,
            )
        except RuntimeError as exc:
            flow_records.append(
                {
                    "flow_id": flow_id,
                    "src": src,
                    "dst": dst,
                    "start_time_s": start_time_s,
                    "status": "blocked",
                    "reason": str(exc),
                }
            )
            continue

        for hop in route["path"]:
            window_idx = int(hop["window_index"])
            load_by_window[window_idx] = load_by_window.get(window_idx, 0.0) + args.flow_size_mbits
            base_window = windows[window_idx]
            if load_by_window[window_idx] > capacity_budget_mbits(base_window):
                overload_events += 1

        delay_s = float(route["arrival_time_s"]) - start_time_s
        delivered_delays.append(delay_s)
        delivered_costs.append(float(route["total_cost"]))
        delivered_hops.append(int(route["hop_count"]))
        flow_records.append(
            {
                "flow_id": flow_id,
                "src": src,
                "dst": dst,
                "start_time_s": start_time_s,
                "status": "delivered",
                "delay_s": round(delay_s, 6),
                "hop_count": route["hop_count"],
                "total_cost": route["total_cost"],
                "path": route["path"],
            }
        )

    delivered = len(delivered_delays)
    blocked = args.flow_count - delivered
    sorted_delays = sorted(delivered_delays)
    result = {
        "metadata": {
            **metadata,
            "simulator": "lightweight_multiflow_satnet_sim",
            "algorithm": args.algorithm,
            "flow_count": args.flow_count,
            "flow_size_mbits": args.flow_size_mbits,
            "seed": args.seed,
            "route_setup_s": args.route_setup_s,
            "ls_update_interval_s": args.ls_update_interval_s,
        },
        "summary": {
            "delivered_flows": delivered,
            "blocked_flows": blocked,
            "delivery_ratio": round(delivered / args.flow_count if args.flow_count else 0.0, 6),
            "avg_delay_s": round(statistics.fmean(delivered_delays), 6) if delivered_delays else 0.0,
            "p95_delay_s": round(percentile(sorted_delays, 0.95), 6) if sorted_delays else 0.0,
            "avg_hop_count": round(statistics.fmean(delivered_hops), 6) if delivered_hops else 0.0,
            "avg_objective_value": round(statistics.fmean(delivered_costs), 6) if delivered_costs else 0.0,
            "window_reservations": sum(len(record.get("path", [])) for record in flow_records if record["status"] == "delivered"),
            "overload_events": overload_events,
        },
        "flows": flow_records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), **result["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
