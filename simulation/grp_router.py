from __future__ import annotations

import argparse
import heapq
import json
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"


@dataclass(frozen=True)
class ContactWindow:
    index: int
    src: str
    dst: str
    t_start_s: float
    t_end_s: float
    prop_delay_s: float
    distance_km: float
    capacity_mbps: float
    risk: float
    link_type: str
    queue_penalty: float = 0.0


@dataclass
class Label:
    state_id: int
    node: str
    arrival_time_s: float
    cost: float
    prev_state_id: int | None
    via_window: ContactWindow | None
    hop_count: int


def load_wlt(path: Path) -> tuple[list[str], list[ContactWindow], dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = payload["nodes"]
    windows = [
        ContactWindow(
            index=idx,
            src=item["src"],
            dst=item["dst"],
            t_start_s=float(item["t_start_s"]),
            t_end_s=float(item["t_end_s"]),
            prop_delay_s=float(item["prop_delay_s"]),
            distance_km=float(item["distance_km"]),
            capacity_mbps=float(item["capacity_mbps"]),
            risk=float(item["risk"]),
            link_type=str(item.get("link_type", "unknown")),
            queue_penalty=float(item.get("queue_penalty", 0.0)),
        )
        for idx, item in enumerate(payload["windows"])
    ]
    return nodes, windows, payload.get("metadata", {})


def dominates(existing: tuple[float, float], candidate: tuple[float, float]) -> bool:
    return existing[0] <= candidate[0] and existing[1] <= candidate[1]


def add_label_frontier(frontier: list[tuple[float, float]], arrival_time_s: float, cost: float) -> bool:
    candidate = (arrival_time_s, cost)
    for item in frontier:
        if dominates(item, candidate):
            return False

    kept = [item for item in frontier if not dominates(candidate, item)]
    kept.append(candidate)
    frontier[:] = kept
    return True


def compute_edge_cost(
    current: Label,
    window: ContactWindow,
    wait_s: float,
    weight_wait: float,
    weight_delay: float,
    weight_risk: float,
    weight_queue: float,
    weight_handover: float,
) -> float:
    hop_cost = (
        weight_wait * wait_s
        + weight_delay * window.prop_delay_s
        + weight_risk * window.risk
        + weight_queue * window.queue_penalty
    )
    if current.via_window is not None:
        hop_cost += weight_handover
    return hop_cost


def reconstruct(labels: dict[int, Label], terminal_state_id: int) -> list[dict[str, object]]:
    path: list[dict[str, object]] = []
    cursor = labels[terminal_state_id]
    while cursor.via_window is not None:
        window = cursor.via_window
        prev_label = labels[cursor.prev_state_id] if cursor.prev_state_id is not None else None
        depart_s = max(prev_label.arrival_time_s if prev_label is not None else 0.0, window.t_start_s)
        path.append(
            {
                "src": window.src,
                "dst": window.dst,
                "link_type": window.link_type,
                "window_index": window.index,
                "window_start_s": window.t_start_s,
                "window_end_s": window.t_end_s,
                "depart_s": round(depart_s, 3),
                "arrive_s": round(cursor.arrival_time_s, 3),
                "prop_delay_s": window.prop_delay_s,
                "risk": window.risk,
                "capacity_mbps": window.capacity_mbps,
            }
        )
        cursor = labels[cursor.prev_state_id]  # type: ignore[index]
    path.reverse()
    return path


def solve(
    nodes: list[str],
    windows: list[ContactWindow],
    src: str,
    dst: str,
    start_time_s: float,
    max_arrival_s: float | None,
    weight_wait: float,
    weight_delay: float,
    weight_risk: float,
    weight_queue: float,
    weight_handover: float,
) -> dict[str, object]:
    if src not in nodes:
        raise ValueError(f"Unknown src node: {src}")
    if dst not in nodes:
        raise ValueError(f"Unknown dst node: {dst}")

    outgoing: dict[str, list[ContactWindow]] = {node: [] for node in nodes}
    for window in windows:
        outgoing.setdefault(window.src, []).append(window)
    for src_node in outgoing:
        outgoing[src_node].sort(key=lambda item: (item.t_start_s, item.t_end_s, item.dst))

    next_state_id = 0
    labels: dict[int, Label] = {}
    best_frontier: dict[str, list[tuple[float, float]]] = {node: [] for node in nodes}
    queue: list[tuple[float, int]] = []

    start_label = Label(
        state_id=next_state_id,
        node=src,
        arrival_time_s=start_time_s,
        cost=0.0,
        prev_state_id=None,
        via_window=None,
        hop_count=0,
    )
    labels[next_state_id] = start_label
    add_label_frontier(best_frontier[src], start_time_s, 0.0)
    heapq.heappush(queue, (0.0, next_state_id))
    next_state_id += 1

    best_terminal_id: int | None = None

    while queue:
        _, state_id = heapq.heappop(queue)
        current = labels[state_id]
        if current.node == dst:
            best_terminal_id = state_id
            break

        for window in outgoing.get(current.node, []):
            if window.t_end_s < current.arrival_time_s:
                continue

            depart_s = max(current.arrival_time_s, window.t_start_s)
            if depart_s > window.t_end_s:
                continue

            arrive_s = depart_s + window.prop_delay_s
            if max_arrival_s is not None and arrive_s > max_arrival_s:
                continue

            wait_s = depart_s - current.arrival_time_s
            edge_cost = compute_edge_cost(
                current=current,
                window=window,
                wait_s=wait_s,
                weight_wait=weight_wait,
                weight_delay=weight_delay,
                weight_risk=weight_risk,
                weight_queue=weight_queue,
                weight_handover=weight_handover,
            )
            total_cost = current.cost + edge_cost
            if not add_label_frontier(best_frontier[window.dst], arrive_s, total_cost):
                continue

            new_label = Label(
                state_id=next_state_id,
                node=window.dst,
                arrival_time_s=arrive_s,
                cost=total_cost,
                prev_state_id=current.state_id,
                via_window=window,
                hop_count=current.hop_count + 1,
            )
            labels[next_state_id] = new_label
            heapq.heappush(queue, (new_label.cost, new_label.state_id))
            next_state_id += 1

    if best_terminal_id is None:
        raise RuntimeError("No feasible GRP path found under the current WLT and constraints.")

    terminal = labels[best_terminal_id]
    path = reconstruct(labels, best_terminal_id)
    return {
        "src": src,
        "dst": dst,
        "start_time_s": start_time_s,
        "arrival_time_s": round(terminal.arrival_time_s, 3),
        "total_cost": round(terminal.cost, 6),
        "hop_count": terminal.hop_count,
        "path": path,
    }


def default_destination(nodes: list[str]) -> str:
    if len(nodes) < 2:
        raise ValueError("Need at least two nodes in WLT.")
    return nodes[len(nodes) // 2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a simplified GRP search on a WLT JSON.")
    parser.add_argument("--wlt", type=Path, default=OUTPUT_DIR / "wlt_demo.json", help="Input WLT JSON.")
    parser.add_argument("--src", type=str, default="P00S00", help="Source node.")
    parser.add_argument("--dst", type=str, default="", help="Destination node.")
    parser.add_argument("--start-time-s", type=float, default=0.0, help="Flow start time.")
    parser.add_argument("--max-arrival-s", type=float, default=0.0, help="Optional arrival cutoff; 0 disables it.")
    parser.add_argument("--weight-wait", type=float, default=1.0, help="Weight for waiting time.")
    parser.add_argument("--weight-delay", type=float, default=30.0, help="Weight for propagation delay.")
    parser.add_argument("--weight-risk", type=float, default=2.0, help="Weight for contact risk.")
    parser.add_argument("--weight-queue", type=float, default=1.0, help="Weight for queue penalty.")
    parser.add_argument("--weight-handover", type=float, default=0.25, help="Penalty per hop transition after the first hop.")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "grp_route_demo.json", help="Route JSON output.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    nodes, windows, metadata = load_wlt(args.wlt)
    dst = args.dst or default_destination(nodes)
    result = solve(
        nodes=nodes,
        windows=windows,
        src=args.src,
        dst=dst,
        start_time_s=args.start_time_s,
        max_arrival_s=args.max_arrival_s if args.max_arrival_s > 0 else None,
        weight_wait=args.weight_wait,
        weight_delay=args.weight_delay,
        weight_risk=args.weight_risk,
        weight_queue=args.weight_queue,
        weight_handover=args.weight_handover,
    )
    payload = {
        "metadata": metadata,
        "route": result,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
