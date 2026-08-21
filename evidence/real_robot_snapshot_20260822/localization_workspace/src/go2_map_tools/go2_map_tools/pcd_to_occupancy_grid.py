#!/usr/bin/env python3
"""Project 3D PCD map to 2D occupancy grid (.pgm + .yaml) for Nav2."""

import argparse
import os

import numpy as np
import yaml


def parse_pcd(path):
    """Parse PCD (ASCII or binary) -> Nx3 float array."""
    fields = []
    sizes = []
    types = []
    counts = []
    width = height = points = 0
    data_type = 'ascii'
    header_lines = []
    data_start = 0

    with open(path, 'rb') as f:
        while True:
            line = f.readline()
            if not line:
                break
            text = line.decode('ascii', errors='ignore').strip()
            header_lines.append(text)
            if text.startswith('FIELDS'):
                fields = text.split()[1:]
            elif text.startswith('SIZE'):
                sizes = list(map(int, text.split()[1:]))
            elif text.startswith('TYPE'):
                types = text.split()[1:]
            elif text.startswith('COUNT'):
                counts = list(map(int, text.split()[1:]))
            elif text.startswith('WIDTH'):
                width = int(text.split()[1])
            elif text.startswith('HEIGHT'):
                height = int(text.split()[1])
            elif text.startswith('POINTS'):
                points = int(text.split()[1])
            elif text.startswith('DATA'):
                data_type = text.split()[1].lower()
                data_start = f.tell()
                break

    if not counts:
        counts = [1] * len(fields)

    type_map = {('F', 4): 'f', ('F', 8): 'd', ('I', 4): 'i', ('I', 2): 'h', ('I', 1): 'b', ('U', 4): 'I'}

    if data_type == 'ascii':
        data = np.loadtxt(path, skiprows=len(header_lines))
        if data.ndim == 1:
            data = data.reshape(1, -1)
        xi = fields.index('x') if 'x' in fields else 0
        yi = fields.index('y') if 'y' in fields else 1
        zi = fields.index('z') if 'z' in fields else 2
        return np.column_stack([data[:, xi], data[:, yi], data[:, zi]]).astype(np.float32)

    # binary
    point_step = sum(s * c for s, c in zip(sizes, counts))
    dtype_fields = []
    for name, sz, tp, cnt in zip(fields, sizes, types, counts):
        key = (tp, sz)
        if key not in type_map:
            raise ValueError(f'Unsupported PCD type {tp}{sz}')
        np_type = np.dtype(type_map[key]).type
        if cnt == 1:
            dtype_fields.append((name, f'<{np.dtype(np_type).char}'))
        else:
            dtype_fields.append((name, f'<{cnt}{np.dtype(np_type).char}'))

    dt = np.dtype(dtype_fields)
    with open(path, 'rb') as f:
        f.seek(data_start)
        raw = f.read(points * dt.itemsize)
    cloud = np.frombuffer(raw, dtype=dt, count=points)
    return np.column_stack([
        cloud['x'].astype(np.float32),
        cloud['y'].astype(np.float32),
        cloud['z'].astype(np.float32),
    ])


def _thin_walls(img, erosion_cells):
    """Erode occupied cells so doorways keep passable width after inflation."""
    if erosion_cells <= 0:
        return img
    try:
        from scipy import ndimage
    except ImportError:
        return img

    occ = img == 0
    structure = ndimage.generate_binary_structure(2, 1)
    thinned = ndimage.binary_erosion(occ, structure=structure, iterations=erosion_cells)
    out = img.copy()
    out[occ] = 254
    out[thinned] = 0
    return out


def _remove_speckle(img, min_occupied_cells):
    """Drop tiny isolated occupied blobs that inflate into false purple zones."""
    if min_occupied_cells <= 1:
        return img
    try:
        from scipy import ndimage
    except ImportError:
        return img

    occ = img == 0
    labeled, n = ndimage.label(occ)
    if n == 0:
        return img
    sizes = ndimage.sum(occ, labeled, range(1, n + 1))
    keep = sizes >= min_occupied_cells
    cleaned = img.copy()
    for label_id, ok in enumerate(keep, start=1):
        if not ok:
            cleaned[labeled == label_id] = 254
    return cleaned


def estimate_ground_z(points, ground_percentile=8.0, ground_z_max=0.35):
    """Estimate floor height; FAST-LIO map z=0 is not always physical ground."""
    low = points[points[:, 2] <= ground_z_max]
    if low.size == 0:
        return float(np.percentile(points[:, 2], ground_percentile))
    return float(np.percentile(low[:, 2], ground_percentile))


def _local_ground_grid(points, resolution, obstacle_band, obstacle_dz=0.25):
    """高度差判据(策略二: ΔH = z_max - z_min):
    对每个 5cm 栅格统计格内点的最高/最低 z, 若高度差 ΔH >= obstacle_dz
    则判为竖直障碍(墙/柱/桌腿)。地面与斜坡因格内点都贴地, ΔH≈0 被放行。
    该判据格内自相对, 不依赖准确地面高度, 抗建图漂移/地面不平;
    且不靠点数门槛, 稀疏远墙也能完整保留。
    obstacle_band=(min_height, overhead): min_height 为格内最高点相对全局
    地面的最小高度(滤纯贴地噪声团); overhead 为悬空限高(剔除吊顶/管线)。"""
    min_height, overhead = obstacle_band
    ground_z = estimate_ground_z(points)

    # 悬空剔除: 只用地面到 overhead 之间的点参与判障(吊顶/高空管线不投影)
    keep = points[:, 2] <= ground_z + overhead
    pts = points[keep]

    xmin, ymin = pts[:, 0].min(), pts[:, 1].min()
    xmax, ymax = pts[:, 0].max(), pts[:, 1].max()
    width = int(np.ceil((xmax - xmin) / resolution)) + 1
    height = int(np.ceil((ymax - ymin) / resolution)) + 1

    ix = np.clip(((pts[:, 0] - xmin) / resolution).astype(np.int32), 0, width - 1)
    iy = np.clip(((pts[:, 1] - ymin) / resolution).astype(np.int32), 0, height - 1)
    flat = iy.astype(np.int64) * width + ix

    n = width * height
    zmax = np.full(n, -np.inf, dtype=np.float64)
    zmin = np.full(n, np.inf, dtype=np.float64)
    cnt = np.zeros(n, dtype=np.int32)
    np.maximum.at(zmax, flat, pts[:, 2])
    np.minimum.at(zmin, flat, pts[:, 2])
    np.add.at(cnt, flat, 1)

    dz = zmax - zmin
    zmax_rel = zmax - ground_z
    # 障碍: 格内竖直立起(ΔH 够大) 且 最高点够高(滤贴地噪声) 且 非单点
    is_obs = (cnt >= 2) & (dz >= obstacle_dz) & (zmax_rel >= min_height)

    grid = np.zeros(n, dtype=np.int32)
    grid[is_obs] = cnt[is_obs]
    grid = grid.reshape(height, width)
    print(f'  height-diff dz>={obstacle_dz:.2f} min_h={min_height:.2f} '
          f'overhead={overhead:.2f} obstacle_cells={int(is_obs.sum())}')
    return grid, xmin, ymin, width, height


def project_to_grid(points, z_min, z_max, resolution, occupied_thresh, free_thresh,
                    min_occupied_cells=1, min_points_per_cell=10,
                    wall_erosion_cells=0,
                    ground_relative=False, ground_band=(0.35, 1.60),
                    local_ground=False, obstacle_band=(0.20, 1.60),
                    obstacle_dz=0.25):
    if local_ground:
        grid, xmin, ymin, width, height = _local_ground_grid(
            points, resolution, obstacle_band, obstacle_dz)
    else:
        if ground_relative:
            ground_z = estimate_ground_z(points)
            z_min = ground_z + ground_band[0]
            z_max = ground_z + ground_band[1]
            print(f'  ground_z={ground_z:.3f} -> slice [{z_min:.3f}, {z_max:.3f}]')

        mask = (points[:, 2] >= z_min) & (points[:, 2] <= z_max)
        pts = points[mask]
        if pts.size == 0:
            raise RuntimeError(f'No points in height band [{z_min:.3f}, {z_max:.3f}]')

        xmin, ymin = pts[:, 0].min(), pts[:, 1].min()
        xmax, ymax = pts[:, 0].max(), pts[:, 1].max()
        width = int(np.ceil((xmax - xmin) / resolution)) + 1
        height = int(np.ceil((ymax - ymin) / resolution)) + 1

        grid = np.zeros((height, width), dtype=np.int32)
        ix = ((pts[:, 0] - xmin) / resolution).astype(np.int32)
        iy = ((pts[:, 1] - ymin) / resolution).astype(np.int32)
        ix = np.clip(ix, 0, width - 1)
        iy = np.clip(iy, 0, height - 1)
        np.add.at(grid, (iy, ix), 1)

    # Nav2 PGM: 0=occupied, 254=free. yaml occupied_thresh is for map_server, not point count.
    img = np.full((height, width), 254, dtype=np.uint8)
    img[grid >= min_points_per_cell] = 0
    img = _remove_speckle(img, min_occupied_cells)
    img = _thin_walls(img, wall_erosion_cells)

    meta = {
        'image': os.path.basename('PLACEHOLDER'),
        'resolution': float(resolution),
        'origin': [float(xmin), float(ymin), 0.0],
        'negate': 0,
        'occupied_thresh': float(occupied_thresh),
        'free_thresh': float(free_thresh),
    }
    return img, meta


def main():
    parser = argparse.ArgumentParser(description='PCD -> Nav2 occupancy grid')
    parser.add_argument('pcd', help='Input PCD path')
    parser.add_argument('-o', '--output', required=True, help='Output prefix (no extension)')
    parser.add_argument('--z-min', type=float, default=-0.3)
    parser.add_argument('--z-max', type=float, default=0.5)
    parser.add_argument('--resolution', type=float, default=0.05)
    parser.add_argument('--occupied-thresh', type=float, default=0.65)
    parser.add_argument('--free-thresh', type=float, default=0.25)
    parser.add_argument('--min-occupied-cells', type=int, default=1)
    parser.add_argument('--min-points-per-cell', type=int, default=10)
    parser.add_argument('--ground-relative', action='store_true')
    parser.add_argument('--ground-band-min', type=float, default=0.15)
    parser.add_argument('--ground-band-max', type=float, default=0.50)
    parser.add_argument('--local-ground', action='store_true',
                        help='逐格本地地面去除(推荐, 抗建图漂移)')
    parser.add_argument('--obstacle-band-min', type=float, default=0.20,
                        help='相对本地地面的障碍下沿(m)')
    parser.add_argument('--obstacle-band-max', type=float, default=1.60,
                        help='悬空限高: 高于地面此值的点不投影(吊顶/管线)')
    parser.add_argument('--obstacle-dz', type=float, default=0.25,
                        help='高度差判障阈值 ΔH=z_max-z_min(策略二)')
    parser.add_argument('--wall-erosion-cells', type=int, default=0)
    parser.add_argument('--config', help='YAML config file (overrides defaults)')
    args = parser.parse_args()

    if args.config:
        with open(args.config) as f:
            cfg = yaml.safe_load(f)
        proj = cfg.get('projection', cfg)
        args.z_min = proj.get('z_min', args.z_min)
        args.z_max = proj.get('z_max', args.z_max)
        args.resolution = proj.get('resolution', args.resolution)
        args.occupied_thresh = proj.get('occupied_thresh', args.occupied_thresh)
        args.free_thresh = proj.get('free_thresh', args.free_thresh)
        args.min_occupied_cells = proj.get('min_occupied_cells', args.min_occupied_cells)
        args.min_points_per_cell = proj.get('min_points_per_cell', args.min_points_per_cell)
        args.ground_relative = proj.get('ground_relative', args.ground_relative)
        args.ground_band_min = proj.get('ground_band_min', args.ground_band_min)
        args.ground_band_max = proj.get('ground_band_max', args.ground_band_max)
        args.local_ground = proj.get('local_ground', args.local_ground)
        args.obstacle_band_min = proj.get('obstacle_band_min', args.obstacle_band_min)
        args.obstacle_band_max = proj.get('obstacle_band_max', args.obstacle_band_max)
        args.obstacle_dz = proj.get('obstacle_dz', args.obstacle_dz)
        args.wall_erosion_cells = proj.get('wall_erosion_cells', args.wall_erosion_cells)

    print(f'Loading {args.pcd} ...')
    pts = parse_pcd(args.pcd)
    print(f'  {len(pts)} points')

    img, meta = project_to_grid(
        pts, args.z_min, args.z_max, args.resolution,
        args.occupied_thresh, args.free_thresh, args.min_occupied_cells,
        args.min_points_per_cell, args.wall_erosion_cells,
        args.ground_relative, (args.ground_band_min, args.ground_band_max),
        args.local_ground, (args.obstacle_band_min, args.obstacle_band_max),
        args.obstacle_dz)

    pgm_path = args.output + '.pgm'
    yaml_path = args.output + '.yaml'
    meta['image'] = os.path.basename(pgm_path)

    # PGM: flip Y for image coordinates
    with open(pgm_path, 'wb') as f:
        f.write(f'P5\n{img.shape[1]} {img.shape[0]}\n255\n'.encode('ascii'))
        f.write(np.flipud(img).astype(np.uint8).tobytes())

    with open(yaml_path, 'w') as f:
        yaml.dump(meta, f, default_flow_style=False)

    print(f'Wrote {pgm_path} ({img.shape[1]}x{img.shape[0]})')
    print(f'Wrote {yaml_path}')
    print(f'  origin=[{meta["origin"][0]:.2f}, {meta["origin"][1]:.2f}] res={meta["resolution"]}')


if __name__ == '__main__':
    main()
