#!/usr/bin/env python3
"""虚拟障碍(玻璃/禁区)的非破坏式管理。

设计: 不把障碍直接烤进地图, 而是:
  <name>.base.pgm     干净底图(从点云生成, 永不涂改)
  <name>.obstacles.json  虚拟障碍记录(线段/矩形, 世界坐标 m, 可随时增删)
  <name>.pgm          由 底图 + 记录 自动合成, Nav2 实际加载这张

这样可随时撤销/删除某条障碍, 并保留完整添加历史。
"""

import json
import os

import numpy as np
import yaml

OCCUPIED = 0
FREE = 254


def read_pgm(path):
    with open(path, 'rb') as f:
        if f.readline().strip() != b'P5':
            raise ValueError(f'仅支持 P5 PGM: {path}')
        vals = []
        while len(vals) < 3:
            line = f.readline()
            if line.startswith(b'#'):
                continue
            vals += line.split()
        w, h, _ = map(int, vals[:3])
        data = np.frombuffer(f.read(w * h), dtype=np.uint8).reshape(h, w)
    return data.copy(), w, h


def write_pgm(path, img):
    h, w = img.shape
    with open(path, 'wb') as f:
        f.write(f'P5\n{w} {h}\n255\n'.encode('ascii'))
        f.write(img.astype(np.uint8).tobytes())


def load_meta(yaml_path):
    with open(yaml_path) as f:
        return yaml.safe_load(f)


def map_paths(yaml_path):
    """根据地图 yaml 推导各关联文件路径。"""
    meta = load_meta(yaml_path)
    d = os.path.dirname(os.path.abspath(yaml_path))
    pgm = os.path.join(d, meta['image'])
    stem = os.path.splitext(meta['image'])[0]
    return {
        'meta': meta,
        'pgm': pgm,
        'base': os.path.join(d, stem + '.base.pgm'),
        'obstacles': os.path.join(d, stem + '.obstacles.json'),
    }


def ensure_base(paths):
    """若无 base.pgm, 用当前 pgm 作为干净底图建立之。"""
    if not os.path.isfile(paths['base']):
        img, _, _ = read_pgm(paths['pgm'])
        write_pgm(paths['base'], img)
    return paths['base']


def load_obstacles(paths):
    if os.path.isfile(paths['obstacles']):
        with open(paths['obstacles']) as f:
            return json.load(f)
    return []


def save_obstacles(paths, obstacles):
    with open(paths['obstacles'], 'w') as f:
        json.dump(obstacles, f, indent=2, ensure_ascii=False)


def line_length(ob):
    """线段/矩形对角长度(m), 用于过滤误点。"""
    return ((ob['x1'] - ob['x0']) ** 2 + (ob['y1'] - ob['y0']) ** 2) ** 0.5


def filter_degenerate(obstacles, min_len=0.15):
    """去掉零长度或极短的误点线段。"""
    return [ob for ob in obstacles if line_length(ob) >= min_len]


# ---- 世界坐标 <-> 像素 ----
def world_to_px(x, y, meta, h):
    ox, oy = meta['origin'][0], meta['origin'][1]
    res = meta['resolution']
    col = int(round((x - ox) / res))
    row = h - 1 - int(round((y - oy) / res))
    return row, col


def px_to_world(col, row, meta, h):
    ox, oy = meta['origin'][0], meta['origin'][1]
    res = meta['resolution']
    x = ox + col * res
    y = oy + (h - 1 - row) * res
    return x, y


# ---- 绘制 ----
def _paint_line(img, meta, ob):
    h, w = img.shape
    res = meta['resolution']
    r0, c0 = world_to_px(ob['x0'], ob['y0'], meta, h)
    r1, c1 = world_to_px(ob['x1'], ob['y1'], meta, h)
    rad = max(0, int(round(ob.get('thickness', 0.10) / res / 2.0)))
    n = max(abs(r1 - r0), abs(c1 - c0)) + 1
    rows = np.linspace(r0, r1, n).round().astype(int)
    cols = np.linspace(c0, c1, n).round().astype(int)
    for r, c in zip(rows, cols):
        rr0, rr1 = max(0, r - rad), min(h, r + rad + 1)
        cc0, cc1 = max(0, c - rad), min(w, c + rad + 1)
        img[rr0:rr1, cc0:cc1] = OCCUPIED


def _paint_rect(img, meta, ob):
    h, w = img.shape
    r0, c0 = world_to_px(ob['x0'], ob['y0'], meta, h)
    r1, c1 = world_to_px(ob['x1'], ob['y1'], meta, h)
    rr0, rr1 = sorted((max(0, min(h - 1, r0)), max(0, min(h - 1, r1))))
    cc0, cc1 = sorted((max(0, min(w - 1, c0)), max(0, min(w - 1, c1))))
    img[rr0:rr1 + 1, cc0:cc1 + 1] = OCCUPIED


def _erase_rect(img, meta, ob):
    """擦除区: 把矩形内刷成 FREE(去掉建图人影/动态鬼影), 与 rect 禁区对称。"""
    h, w = img.shape
    r0, c0 = world_to_px(ob['x0'], ob['y0'], meta, h)
    r1, c1 = world_to_px(ob['x1'], ob['y1'], meta, h)
    rr0, rr1 = sorted((max(0, min(h - 1, r0)), max(0, min(h - 1, r1))))
    cc0, cc1 = sorted((max(0, min(w - 1, c0)), max(0, min(w - 1, c1))))
    img[rr0:rr1 + 1, cc0:cc1 + 1] = FREE


def compose(paths, obstacles):
    """干净底图 + 障碍列表 -> 合成图(numpy 数组)。"""
    base, _, _ = read_pgm(paths['base'])
    out = base.copy()
    meta = paths['meta']
    for ob in obstacles:
        t = ob.get('type', 'line')
        if t == 'rect':
            _paint_rect(out, meta, ob)
        elif t == 'erase':
            _erase_rect(out, meta, ob)
        else:
            _paint_line(out, meta, ob)
    return out


def rebuild(yaml_path):
    """根据记录重建 scans.pgm, 返回(障碍数量)。"""
    paths = map_paths(yaml_path)
    ensure_base(paths)
    obstacles = load_obstacles(paths)
    out = compose(paths, obstacles)
    write_pgm(paths['pgm'], out)
    return len(obstacles)
