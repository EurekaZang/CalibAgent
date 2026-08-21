#!/usr/bin/env python3
"""在 Nav2 静态地图(.pgm)上手动绘制虚拟障碍 / 禁区。

用途: 玻璃门、镜面、悬空护栏、楼梯口等激光测不到的危险区域,
激光建图时它们不在点云里, 必须人工标成障碍, 否则导航会规划穿过去。

坐标系: 全部使用地图(map)世界坐标, 单位米。可在 RViz 里把鼠标移到
目标位置, 读取 RViz 左下角的坐标, 或用 `ros2 topic echo /clicked_point`
(RViz "Publish Point" 工具)取点。

示例:
  # 在 (1.2, 0.5) 到 (1.2, 2.0) 之间画一道宽 0.10m 的玻璃墙
  ros2 run go2_map_tools paint_virtual_obstacles \
      maps/scans.yaml --line 1.2 0.5 1.2 2.0 --thickness 0.10

  # 矩形禁区(min_x min_y max_x max_y)
  ros2 run go2_map_tools paint_virtual_obstacles \
      maps/scans.yaml --rect 3.0 1.0 3.5 2.5

  # 多段线/多禁区可重复传 --line / --rect; 默认写回原 pgm(自动 .bak 备份)
"""

import argparse
import os
import shutil

import numpy as np
import yaml

OCCUPIED = 0
FREE = 254


def load_map(yaml_path):
    with open(yaml_path) as f:
        meta = yaml.safe_load(f)
    pgm_path = os.path.join(os.path.dirname(yaml_path), meta['image'])
    img, w, h = read_pgm(pgm_path)
    return meta, pgm_path, img, w, h


def read_pgm(path):
    with open(path, 'rb') as f:
        magic = f.readline().strip()
        if magic != b'P5':
            raise ValueError(f'仅支持 P5 二进制 PGM: {path}')
        # 跳过注释, 读取宽高与最大值
        vals = []
        while len(vals) < 3:
            line = f.readline()
            if line.startswith(b'#'):
                continue
            vals += line.split()
        w, h, _maxv = int(vals[0]), int(vals[1]), int(vals[2])
        data = np.frombuffer(f.read(w * h), dtype=np.uint8).reshape(h, w)
    return data.copy(), w, h


def write_pgm(path, img):
    h, w = img.shape
    with open(path, 'wb') as f:
        f.write(f'P5\n{w} {h}\n255\n'.encode('ascii'))
        f.write(img.astype(np.uint8).tobytes())


def world_to_px(x, y, meta, w, h):
    """map 世界坐标 -> pgm 像素 (row, col)。pgm 已上下翻转(map_server 约定)。"""
    ox, oy = meta['origin'][0], meta['origin'][1]
    res = meta['resolution']
    col = int(round((x - ox) / res))
    row = int(round((y - oy) / res))
    row = h - 1 - row  # 翻转 Y
    return row, col


def paint_line(img, meta, w, h, x0, y0, x1, y1, thickness_m):
    res = meta['resolution']
    r0, c0 = world_to_px(x0, y0, meta, w, h)
    r1, c1 = world_to_px(x1, y1, meta, w, h)
    rad = max(0, int(round(thickness_m / res / 2.0)))
    n = max(abs(r1 - r0), abs(c1 - c0)) + 1
    rows = np.linspace(r0, r1, n).round().astype(int)
    cols = np.linspace(c0, c1, n).round().astype(int)
    cnt = 0
    for r, c in zip(rows, cols):
        rr0, rr1 = max(0, r - rad), min(h, r + rad + 1)
        cc0, cc1 = max(0, c - rad), min(w, c + rad + 1)
        img[rr0:rr1, cc0:cc1] = OCCUPIED
        cnt += (rr1 - rr0) * (cc1 - cc0)
    return cnt


def paint_rect(img, meta, w, h, x0, y0, x1, y1):
    r0, c0 = world_to_px(x0, y0, meta, w, h)
    r1, c1 = world_to_px(x1, y1, meta, w, h)
    rr0, rr1 = sorted((max(0, min(h - 1, r0)), max(0, min(h - 1, r1))))
    cc0, cc1 = sorted((max(0, min(w - 1, c0)), max(0, min(w - 1, c1))))
    img[rr0:rr1 + 1, cc0:cc1 + 1] = OCCUPIED
    return (rr1 - rr0 + 1) * (cc1 - cc0 + 1)


def main():
    p = argparse.ArgumentParser(description='在 Nav2 静态地图上手画虚拟障碍/禁区')
    p.add_argument('map_yaml', help='地图 yaml 路径')
    p.add_argument('--line', nargs=4, type=float, action='append',
                   metavar=('X0', 'Y0', 'X1', 'Y1'), default=[],
                   help='线段虚拟墙(map 世界坐标 m), 可多次')
    p.add_argument('--rect', nargs=4, type=float, action='append',
                   metavar=('X0', 'Y0', 'X1', 'Y1'), default=[],
                   help='矩形禁区(map 世界坐标 m), 可多次')
    p.add_argument('--thickness', type=float, default=0.10,
                   help='线段宽度 m (默认 0.10)')
    p.add_argument('-o', '--output', help='输出 pgm(默认覆盖原图)')
    p.add_argument('--no-backup', action='store_true', help='覆盖原图时不创建 .bak')
    args = p.parse_args()

    if not args.line and not args.rect:
        p.error('至少提供一个 --line 或 --rect')

    meta, pgm_path, img, w, h = load_map(args.map_yaml)
    print(f'地图 {pgm_path} ({w}x{h}) res={meta["resolution"]} '
          f'origin=[{meta["origin"][0]:.2f},{meta["origin"][1]:.2f}]')

    total = 0
    for x0, y0, x1, y1 in args.line:
        c = paint_line(img, meta, w, h, x0, y0, x1, y1, args.thickness)
        print(f'  线段 ({x0},{y0})->({x1},{y1}) 宽{args.thickness}m  +{c} 格')
        total += c
    for x0, y0, x1, y1 in args.rect:
        c = paint_rect(img, meta, w, h, x0, y0, x1, y1)
        print(f'  矩形 ({x0},{y0})-({x1},{y1})  +{c} 格')
        total += c

    out = args.output or pgm_path
    if out == pgm_path and not args.no_backup:
        bak = pgm_path + '.bak'
        if not os.path.exists(bak):
            shutil.copy2(pgm_path, bak)
            print(f'已备份原图 -> {bak}')
    write_pgm(out, img)
    print(f'已写入 {out}  (共标记 {total} 个障碍格)')
    print('提示: 重启导航或重载 map_server 后生效。')


if __name__ == '__main__':
    main()
