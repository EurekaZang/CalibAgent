#!/usr/bin/env python3
"""Generate deterministic frozen command tables and balanced P8 schedules."""

import csv
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "configs" / "p8"
COMMANDS = OUT / "commands"
SCHEDULES = OUT / "schedules"
BOUNDS = np.asarray([[-0.60, 0.60], [-0.30, 0.30], [-0.80, 0.80]], dtype=np.float64)


def valid(command):
    return bool(
        np.all(command >= BOUNDS[:, 0])
        and np.all(command <= BOUNDS[:, 1])
        and np.linalg.norm(command[:2]) <= 0.65
    )


def unique(commands, count):
    output = []
    seen = set()
    for command in commands:
        value = np.asarray(command, dtype=np.float64)
        key = tuple(np.round(value, 6))
        if valid(value) and key not in seen:
            seen.add(key)
            output.append(value)
        if len(output) == count:
            break
    if len(output) != count:
        raise RuntimeError(f"could not generate {count:d} unique commands")
    return np.asarray(output)


def random_valid(count, seed):
    rng = np.random.RandomState(seed)
    values = []
    while len(values) < count:
        candidate = rng.uniform(BOUNDS[:, 0], BOUNDS[:, 1])
        if valid(candidate):
            values.append(candidate)
    return unique(values, count)


def lhs(count, seed):
    rng = np.random.RandomState(seed)
    unit = np.empty((count, 3))
    for axis in range(3):
        unit[:, axis] = (rng.permutation(count) + rng.uniform(size=count)) / count
    proposals = BOUNDS[:, 0] + unit * (BOUNDS[:, 1] - BOUNDS[:, 0])
    return unique(list(proposals) + list(random_valid(count * 4, seed + 1)), count)


def halton(count, start=1):
    def radical(index, base):
        value, factor = 0.0, 1.0 / base
        while index:
            value += factor * (index % base)
            index //= base
            factor /= base
        return value

    values = []
    index = start
    while len(values) < count:
        unit = np.asarray([radical(index, base) for base in (2, 3, 5)])
        candidate = BOUNDS[:, 0] + unit * (BOUNDS[:, 1] - BOUNDS[:, 0])
        if valid(candidate):
            values.append(candidate)
        index += 1
    return unique(values, count)


def write_commands(name, commands, prefix, weights=None):
    path = COMMANDS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        fields = ["command_id", "cmd_vx", "cmd_vy", "cmd_wz"] + (
            ["weight"] if weights is not None else []
        )
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index, command in enumerate(commands):
            row = {
                "command_id": f"{prefix}_{index + 1:03d}",
                "cmd_vx": f"{command[0]:.6f}",
                "cmd_vy": f"{command[1]:.6f}",
                "cmd_wz": f"{command[2]:.6f}",
            }
            if weights is not None:
                row["weight"] = f"{weights[index]:.9f}"
            writer.writerow(row)


def write_schedules():
    methods = [
        "B0_raw",
        "B1_dense",
        "B2_lhs",
        "B3_sobol",
        "B4_d_opt",
        "B5_active_no_task",
        "B6_random",
        "B8_full",
    ]
    with (SCHEDULES / "nav_blocks.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["planned_unit_id", "block_id", "position", "method_id", "route_order"],
        )
        writer.writeheader()
        for block in range(30):
            order = methods[block % 8 :] + methods[: block % 8]
            for position, method in enumerate(order, start=1):
                method_index = methods.index(method)
                route_order = "AB" if (block + method_index) % 2 == 0 else "BA"
                block_id = f"NAV_BLOCK_{block + 1:02d}"
                writer.writerow(
                    {
                        "planned_unit_id": f"{block_id}_{method}",
                        "block_id": block_id,
                        "position": position,
                        "method_id": method,
                        "route_order": route_order,
                    }
                )
    shift_ids = [
        "R1_command_gain_coupling",
        "R2_payload_com",
        "R3_surface_friction",
        "R4_mixed_context",
    ]
    shift_methods = ["frozen", "passive", "full"]
    with (SCHEDULES / "shift_blocks.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["planned_unit_id", "shift_id", "block_id", "position", "method_id"]
        )
        writer.writeheader()
        for shift_id in shift_ids:
            for block in range(3):
                order = shift_methods[block % 3 :] + shift_methods[: block % 3]
                block_id = f"SHIFT_BLOCK_{block + 1:02d}"
                for position, method in enumerate(order, start=1):
                    writer.writerow(
                        {
                            "planned_unit_id": f"{shift_id}_{block_id}_{method}",
                            "shift_id": shift_id,
                            "block_id": block_id,
                            "position": position,
                            "method_id": method,
                        }
                    )


def main():
    COMMANDS.mkdir(parents=True, exist_ok=True)
    SCHEDULES.mkdir(parents=True, exist_ok=True)
    axes = []
    for axis, levels in enumerate((11, 7, 13)):
        for value in np.linspace(BOUNDS[axis, 0], BOUNDS[axis, 1], levels):
            command = np.zeros(3)
            command[axis] = value
            axes.append(command)
    pool = unique(axes + list(halton(700, 7)), 512)
    write_commands("candidate_pool.csv", pool, "POOL")
    write_commands("dense_design.csv", unique(list(halton(30, 71)), 30), "DENSE")
    write_commands("lhs_design.csv", lhs(12, 88101), "LHS")
    write_commands("sobol_design.csv", halton(12, 131), "SOBOL")
    write_commands("random_design.csv", random_valid(12, 88103), "RANDOM")
    seed = np.asarray(
        [
            [-0.50, 0.0, 0.0],
            [0.50, 0.0, 0.0],
            [0.0, -0.25, 0.0],
            [0.0, 0.25, 0.0],
            [0.0, 0.0, -0.70],
            [0.0, 0.0, 0.70],
        ]
    )
    write_commands("active_seed.csv", seed, "SEED")
    validation = np.asarray(
        [
            [0.30, 0.0, 0.0],
            [-0.30, 0.0, 0.0],
            [0.20, 0.15, 0.35],
            [0.20, -0.15, -0.35],
            [-0.20, 0.12, -0.45],
            [-0.20, -0.12, 0.45],
            [0.10, 0.0, 0.60],
            [0.10, 0.0, -0.60],
        ]
    )
    write_commands("validation_commands.csv", validation, "VAL")
    task = np.asarray(
        [[vx, 0.0, wz] for vx in np.linspace(0.0, 0.60, 9) for wz in np.linspace(-0.80, 0.80, 9)]
    )
    weights = np.exp(-(((task[:, 0] - 0.35) / 0.25) ** 2) - (task[:, 2] / 0.65) ** 2)
    write_commands("task_distribution.csv", task, "TASK", weights / weights.sum())
    write_commands("pre_calibration.csv", halton(12, 211), "PRE")
    monitor = np.asarray(
        [
            [0.30, 0.0, 0.0],
            [0.20, 0.0, 0.40],
            [0.20, 0.0, -0.40],
            [-0.25, 0.0, 0.0],
            [0.35, 0.0, 0.25],
            [0.35, 0.0, -0.25],
            [0.15, 0.15, 0.30],
            [0.15, -0.15, -0.30],
            [0.0, 0.0, 0.60],
        ]
    )
    write_commands("monitor_commands.csv", monitor, "MON")
    write_commands("passive_recovery.csv", lhs(12, 88201), "REC")
    write_commands(
        "recovery_validation.csv", unique(list(validation) + list(halton(12, 311)), 12), "RVAL"
    )
    write_commands(
        "restore_checks.csv", np.asarray([[0.30, 0.0, 0.0], [0.20, 0.0, -0.40]]), "CHECK"
    )
    write_schedules()


if __name__ == "__main__":
    main()
