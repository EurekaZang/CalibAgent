#!/usr/bin/env python3
"""命令行管理虚拟障碍记录(无需图形界面)。

子命令:
  list                      列出所有障碍
  add  X0 Y0 X1 Y1 [--thickness T]   新增一条线段虚拟墙
  rect X0 Y0 X1 Y1          新增一个矩形禁区(刷成障碍)
  erase X0 Y0 X1 Y1         新增一个矩形擦除区(刷成可通行, 去人影/鬼影)
  rm   INDEX                删除第 INDEX 条(从 1 开始)
  clear                     清空全部
  rebuild                   仅按记录重新合成 scans.pgm(改了底图后用)

所有操作都会立即重写 <name>.obstacles.json 与 <name>.pgm。
重启导航后生效。
"""

import argparse
import sys

from go2_map_tools import vobstacles as vo


def _print_list(obstacles):
    if not obstacles:
        print('(无虚拟障碍)')
        return
    label = {'line': '线段墙', 'rect': '矩形禁区', 'erase': '擦除区'}
    for i, ob in enumerate(obstacles, 1):
        t = ob.get('type', 'line')
        print(f'  {i}. [{label.get(t, t)}] ({ob["x0"]:+.2f},{ob["y0"]:+.2f})->'
              f'({ob["x1"]:+.2f},{ob["y1"]:+.2f}) thickness={ob.get("thickness", "-")}')


def main():
    p = argparse.ArgumentParser(description='命令行管理虚拟障碍')
    p.add_argument('--map',
                   default='/home/unitree/ws_localization/src/go2_loc_bringup/maps/scans.yaml')
    sub = p.add_subparsers(dest='cmd', required=True)

    sub.add_parser('list')
    pa = sub.add_parser('add')
    pa.add_argument('coords', nargs=4, type=float, metavar=('X0', 'Y0', 'X1', 'Y1'))
    pa.add_argument('--thickness', type=float, default=0.10)
    pr = sub.add_parser('rect')
    pr.add_argument('coords', nargs=4, type=float, metavar=('X0', 'Y0', 'X1', 'Y1'))
    pe = sub.add_parser('erase')
    pe.add_argument('coords', nargs=4, type=float, metavar=('X0', 'Y0', 'X1', 'Y1'))
    prm = sub.add_parser('rm')
    prm.add_argument('index', type=int)
    sub.add_parser('clear')
    sub.add_parser('rebuild')

    args = p.parse_args()
    paths = vo.map_paths(args.map)
    vo.ensure_base(paths)
    obstacles = vo.load_obstacles(paths)

    if args.cmd == 'list':
        _print_list(obstacles)
        return

    if args.cmd == 'rebuild':
        n = vo.rebuild(args.map)
        print(f'已按 {n} 条记录重建 {paths["pgm"]}')
        return

    if args.cmd == 'add':
        x0, y0, x1, y1 = args.coords
        obstacles.append({'type': 'line', 'x0': round(x0, 3), 'y0': round(y0, 3),
                          'x1': round(x1, 3), 'y1': round(y1, 3),
                          'thickness': args.thickness})
        print(f'已新增线段 #{len(obstacles)}')
    elif args.cmd == 'rect':
        x0, y0, x1, y1 = args.coords
        obstacles.append({'type': 'rect', 'x0': round(x0, 3), 'y0': round(y0, 3),
                          'x1': round(x1, 3), 'y1': round(y1, 3)})
        print(f'已新增矩形禁区 #{len(obstacles)}')
    elif args.cmd == 'erase':
        x0, y0, x1, y1 = args.coords
        obstacles.append({'type': 'erase', 'x0': round(x0, 3), 'y0': round(y0, 3),
                          'x1': round(x1, 3), 'y1': round(y1, 3)})
        print(f'已新增擦除区 #{len(obstacles)}')
    elif args.cmd == 'rm':
        i = args.index - 1
        if i < 0 or i >= len(obstacles):
            print(f'索引超范围: {args.index} (共 {len(obstacles)} 条)')
            sys.exit(1)
        ob = obstacles.pop(i)
        print(f'已删除 #{args.index}: ({ob["x0"]:+.2f},{ob["y0"]:+.2f})->'
              f'({ob["x1"]:+.2f},{ob["y1"]:+.2f})')
    elif args.cmd == 'clear':
        n = len(obstacles)
        obstacles.clear()
        print(f'已清空 {n} 条')

    vo.save_obstacles(paths, obstacles)
    out = vo.compose(paths, obstacles)
    vo.write_pgm(paths['pgm'], out)
    print(f'已重写 {paths["pgm"]} (当前 {len(obstacles)} 条)')
    _print_list(obstacles)


if __name__ == '__main__':
    main()
