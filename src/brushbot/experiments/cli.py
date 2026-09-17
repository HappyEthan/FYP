"""Human-confirmed client for the running experiment service."""

from __future__ import annotations

import argparse
import secrets

from brushbot.experiments.ipc import send_ipc_request
from brushbot.experiments.cartesian_return import target_pose_si


def main(argv=None, *, input_fn=input, output_fn=print) -> int:
    parser = argparse.ArgumentParser(
        description="Request a safe return through an already running experiment service")
    parser.add_argument("--socket", required=True, help="local experiment service socket")
    parser.add_argument("--x-mm", required=True, type=float)
    parser.add_argument("--y-mm", required=True, type=float)
    parser.add_argument("--z-mm", required=True, type=float)
    parser.add_argument("--rx-deg", required=True, type=float)
    parser.add_argument("--ry-deg", required=True, type=float)
    parser.add_argument("--rz-deg", required=True, type=float)
    args = parser.parse_args(argv)
    target = target_pose_si(
        args.x_mm, args.y_mm, args.z_mm,
        args.rx_deg, args.ry_deg, args.rz_deg,
    )
    status = send_ipc_request(args.socket, {
        "request_id": secrets.token_hex(8), "action": "status",
    })
    output_fn("experiment_state={}; return_state={}".format(
        (status.get("experiment") or {}).get("state"),
        (status.get("cartesian_return") or {}).get("state")))
    output_fn("frozen target [m, rad]: " + repr(target))
    answer = input_fn("Type return to submit this Cartesian target: ").strip()
    if answer != "return":
        output_fn("Cancelled; no command sent.")
        return 1
    response = send_ipc_request(args.socket, {
        "request_id": secrets.token_hex(8), "action": "return_pose",
        "target_pose_m_rad": list(target),
    })
    if response.get("status") != "accepted":
        output_fn("Return request rejected: " + response.get("error", "unknown error"))
        return 2
    output_fn("Return request accepted by the running service.")
    return 0
