#!/usr/bin/env python3
"""不依赖 RViz: 在静态地图上可视化编辑地图, 增加禁区 / 擦除动态障碍。

非破坏式: 原始干净底图永久保存在 <name>.base.pgm(永不涂改); 所有改动以
记录形式存在 <name>.obstacles.json; Nav2 加载的 <name>.pgm 由 底图 + 记录
实时合成。因此任何改动都能撤销/删除/清空, 随时可一键复原到最初地图。

三种编辑模式(工具栏按钮或数字键切换):
  [1] 线墙禁区   左键点两端 = 一道虚拟墙(玻璃/护栏等, 染橙)
  [2] 矩形禁区   左键点对角两点 = 一块禁止进入区域(染橙)
  [3] 擦除动障   左键点对角两点 = 把建图人影/动态鬼影刷成可通行(染蓝)

通用操作:
  中键/右键拖动 平移      滚轮 / +/-  缩放
  u 撤销最后一条          Delete / Shift+左键  删除离光标最近的一条
  c 清空全部             复原原图按钮 = 回到最初未处理地图
  r 取消当前未完成的点选   s 打印保存路径    Esc 退出

橙色 = 新增的虚拟障碍/禁区; 蓝色 = 被擦除(还原为可通行)的区域; 黑色 = 真实地图障碍。
"""

import argparse
import os
import sys

import numpy as np

try:
    import tkinter as tk
    from PIL import Image, ImageTk
except ImportError as e:
    print(f'缺少依赖: {e}\n需要: sudo apt install -y python3-tk python3-pil.imagetk')
    sys.exit(1)

from go2_map_tools import vobstacles as vo


class MapPicker:
    def __init__(self, map_yaml, thickness, margin_m=2.0):
        self.map_yaml = map_yaml
        self.thickness = thickness
        self.paths = vo.map_paths(map_yaml)
        vo.ensure_base(self.paths)
        self.meta = self.paths['meta']
        self.base, self.w, self.h = vo.read_pgm(self.paths['base'])
        self.obstacles = vo.filter_degenerate(vo.load_obstacles(self.paths))
        self.pending = []  # 当前正在点选的点
        self.mode = 'line'  # line=线墙禁区  rect=矩形禁区  erase=擦除动障

        res = self.meta['resolution']
        self.margin_px = max(1, int(round(margin_m / res)))
        self._compute_crop()

        self.root = tk.Tk()
        self.root.title('地图编辑器: 加禁区 / 擦动障  中键拖动  滚轮缩放  u撤销  Esc退出')

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.view_w = min(int(sw * 0.9), 1600)
        self.view_h = min(int(sh * 0.82), 950)
        self.zoom = max(1.0, min(self.view_w / self.bw, self.view_h / self.bh))

        # ---- 顶部工具栏 ----
        bar = tk.Frame(self.root, bg='gray85')
        bar.pack(fill='x')
        self.mode_btns = {}
        for key, label in (('line', '① 线墙禁区'), ('rect', '② 矩形禁区'),
                           ('erase', '③ 擦除动障')):
            b = tk.Button(bar, text=label, width=11,
                          command=lambda k=key: self.set_mode(k))
            b.pack(side='left', padx=2, pady=3)
            self.mode_btns[key] = b
        self._btn_bg = self.mode_btns['line'].cget('bg')
        tk.Frame(bar, width=16, bg='gray85').pack(side='left')
        tk.Button(bar, text='撤销(u)', width=8,
                  command=self.undo).pack(side='left', padx=2)
        tk.Button(bar, text='删最近(Del)', width=10,
                  command=self.on_delete_near).pack(side='left', padx=2)
        tk.Button(bar, text='清空(c)', width=8,
                  command=self.clear_all).pack(side='left', padx=2)
        tk.Button(bar, text='复原原图', width=9, fg='#a00',
                  command=self.restore_original).pack(side='left', padx=2)

        top = tk.Frame(self.root)
        top.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(top, width=self.view_w, height=self.view_h,
                                bg='gray70', highlightthickness=0)
        hbar = tk.Scrollbar(top, orient='horizontal', command=self._xscroll)
        vbar = tk.Scrollbar(top, orient='vertical', command=self._yscroll)
        self.canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        vbar.grid(row=0, column=1, sticky='ns')
        hbar.grid(row=1, column=0, sticky='ew')
        top.rowconfigure(0, weight=1)
        top.columnconfigure(0, weight=1)

        self.status = tk.Label(self.root, justify='left', anchor='w',
                               font=('monospace', 11))
        self.status.pack(fill='x', padx=8, pady=4)

        c = self.canvas
        c.bind('<Button-1>', self.on_left)
        c.bind('<Shift-Button-1>', self.on_delete_near)
        c.bind('<Button-2>', self._pan_start)
        c.bind('<B2-Motion>', self._pan_move)
        c.bind('<ButtonRelease-2>', self._pan_end)
        c.bind('<Button-3>', self._pan_start)
        c.bind('<B3-Motion>', self._pan_move)
        c.bind('<ButtonRelease-3>', self._pan_end)
        c.bind('<Configure>', lambda _e: self._schedule_redraw())
        c.bind('<Button-4>', lambda e: self.on_wheel(e, 1.25))
        c.bind('<Button-5>', lambda e: self.on_wheel(e, 0.8))
        c.bind('<MouseWheel>', lambda e: self.on_wheel(e, 1.25 if e.delta > 0 else 0.8))
        c.bind('<Motion>', self.on_motion)
        self.root.bind('<Escape>', lambda _e: self.root.destroy())
        self.root.bind('1', lambda _e: self.set_mode('line'))
        self.root.bind('2', lambda _e: self.set_mode('rect'))
        self.root.bind('3', lambda _e: self.set_mode('erase'))
        self.root.bind('r', lambda _e: self.cancel_pending())
        self.root.bind('u', lambda _e: self.undo())
        self.root.bind('c', lambda _e: self.clear_all())
        self.root.bind('s', lambda _e: self.print_saved())
        self.root.bind('<Delete>', self.on_delete_near)
        self.root.bind('<plus>', lambda _e: self.zoom_center(1.25))
        self.root.bind('<equal>', lambda _e: self.zoom_center(1.25))
        self.root.bind('<minus>', lambda _e: self.zoom_center(0.8))

        self.tkimg = None
        self._redraw_pending = False
        self._pan_last = None
        self.min_line_len = 0.15
        self.refresh_image()
        self.redraw()
        self.center_view()
        self.set_mode('line')
        self.set_status('就绪。工具栏选模式: ①线墙禁区 ②矩形禁区 ③擦除动障; '
                        '左键点两点, 中键/右键拖动平移')

    # ---- 底图(含障碍橙色叠加) ----
    def _compute_crop(self):
        occ = np.argwhere(self.base == vo.OCCUPIED)
        if occ.size:
            r0, c0 = occ.min(0)
            r1, c1 = occ.max(0)
            self.cy0 = max(0, r0 - self.margin_px)
            self.cx0 = max(0, c0 - self.margin_px)
            self.cy1 = min(self.h, r1 + self.margin_px)
            self.cx1 = min(self.w, c1 + self.margin_px)
        else:
            self.cy0, self.cx0, self.cy1, self.cx1 = 0, 0, self.h, self.w
        self.bw = self.cx1 - self.cx0
        self.bh = self.cy1 - self.cy0

    def refresh_image(self):
        """合成 RGB: 真实障碍黑, 虚拟障碍橙。并持久化(json + pgm)。"""
        composed = vo.compose(self.paths, self.obstacles)  # 0=occ,254=free
        vo.write_pgm(self.paths['pgm'], composed)
        vo.save_obstacles(self.paths, self.obstacles)

        crop = composed[self.cy0:self.cy1, self.cx0:self.cx1]
        rgb = np.stack([crop, crop, crop], axis=-1).astype(np.uint8)
        base_crop = self.base[self.cy0:self.cy1, self.cx0:self.cx1]
        # 合成为障碍但底图非障碍 = 新增禁区/虚拟墙, 染橙
        added_mask = (crop == vo.OCCUPIED) & (base_crop != vo.OCCUPIED)
        rgb[added_mask] = (255, 140, 0)
        # 底图为障碍但合成已变可通行 = 被擦除的动态障碍, 染蓝
        erased_mask = (crop != vo.OCCUPIED) & (base_crop == vo.OCCUPIED)
        rgb[erased_mask] = (40, 130, 255)
        self.base_rgb = Image.fromarray(rgb)

    # ---- 视图(只渲染当前可见区域, 避免大图缩放导致 MemoryError) ----
    def _schedule_redraw(self):
        if self._redraw_pending:
            return
        self._redraw_pending = True
        self.root.after_idle(self._do_redraw)

    def _do_redraw(self):
        self._redraw_pending = False
        self.redraw()

    def _xscroll(self, *args):
        self.canvas.xview(*args)
        self._schedule_redraw()

    def _yscroll(self, *args):
        self.canvas.yview(*args)
        self._schedule_redraw()

    def _pan_start(self, event):
        self._pan_last = (event.x, event.y)

    def _pan_move(self, event):
        if self._pan_last is None:
            return
        dx = event.x - self._pan_last[0]
        dy = event.y - self._pan_last[1]
        self._pan_last = (event.x, event.y)
        dw = max(1, self.bw * self.zoom)
        dh = max(1, self.bh * self.zoom)
        x0, _ = self.canvas.xview()
        y0, _ = self.canvas.yview()
        self.canvas.xview_moveto(max(0.0, min(1.0, x0 - dx / dw)))
        self.canvas.yview_moveto(max(0.0, min(1.0, y0 - dy / dh)))
        self.redraw()

    def _pan_end(self, _event):
        self._pan_last = None

    def center_view(self):
        dw = max(1, self.bw * self.zoom)
        dh = max(1, self.bh * self.zoom)
        fx = max(0.0, (dw - self.view_w) / dw / 2) if dw > self.view_w else 0.0
        fy = max(0.0, (dh - self.view_h) / dh / 2) if dh > self.view_h else 0.0
        self.canvas.xview_moveto(fx)
        self.canvas.yview_moveto(fy)
        self.redraw()

    def redraw(self):
        dw = max(1, int(self.bw * self.zoom))
        dh = max(1, int(self.bh * self.zoom))
        self.canvas.configure(scrollregion=(0, 0, dw, dh))

        # 可见区域(画布坐标)
        vx0 = self.canvas.canvasx(0)
        vy0 = self.canvas.canvasy(0)
        vx1 = self.canvas.canvasx(self.view_w)
        vy1 = self.canvas.canvasy(self.view_h)

        # 对应源图像像素(裁剪区内)
        sx0 = max(0, int(np.floor(vx0 / self.zoom)))
        sy0 = max(0, int(np.floor(vy0 / self.zoom)))
        sx1 = min(self.bw, int(np.ceil(vx1 / self.zoom)) + 1)
        sy1 = min(self.bh, int(np.ceil(vy1 / self.zoom)) + 1)

        self.canvas.delete('img')
        if sx1 > sx0 and sy1 > sy0:
            crop = self.base_rgb.crop((sx0, sy0, sx1, sy1))
            disp_w = max(1, int(round((sx1 - sx0) * self.zoom)))
            disp_h = max(1, int(round((sy1 - sy0) * self.zoom)))
            # 安全上限: 显示图不超过视窗 2 倍(防极端情况)
            max_w, max_h = self.view_w * 2, self.view_h * 2
            if disp_w > max_w or disp_h > max_h:
                s = min(max_w / disp_w, max_h / disp_h)
                disp_w = max(1, int(disp_w * s))
                disp_h = max(1, int(disp_h * s))
            resample = Image.NEAREST if self.zoom >= 2 else Image.BILINEAR
            disp = crop.resize((disp_w, disp_h), resample)
            self.tkimg = ImageTk.PhotoImage(disp)
            self.canvas.create_image(sx0 * self.zoom, sy0 * self.zoom, anchor='nw',
                                     image=self.tkimg, tags='img')
            self.canvas.tag_lower('img')
        self.draw_marks()

    def draw_marks(self):
        self.canvas.delete('mark')
        for (x, y) in self.pending:
            cx, cy = self.world_to_disp(x, y)
            r = 6
            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                    fill='red', outline='yellow', width=2, tags='mark')

    # ---- 坐标变换 ----
    def canvas_to_orig(self, ex, ey):
        dx = self.canvas.canvasx(ex)
        dy = self.canvas.canvasy(ey)
        col = int(round(dx / self.zoom)) + self.cx0
        row = int(round(dy / self.zoom)) + self.cy0
        col = max(0, min(self.w - 1, col))
        row = max(0, min(self.h - 1, row))
        return col, row

    def world_to_disp(self, x, y):
        ox, oy = self.meta['origin'][0], self.meta['origin'][1]
        res = self.meta['resolution']
        col = (x - ox) / res
        row = self.h - 1 - (y - oy) / res
        return (col - self.cx0) * self.zoom, (row - self.cy0) * self.zoom

    # ---- 缩放/平移 ----
    def on_wheel(self, event, factor):
        before = self.canvas_to_orig(event.x, event.y)
        self.zoom = max(0.5, min(80.0, self.zoom * factor))
        col, row = before
        target_dx = (col - self.cx0) * self.zoom
        target_dy = (row - self.cy0) * self.zoom
        dw = max(1, self.bw * self.zoom)
        dh = max(1, self.bh * self.zoom)
        self.canvas.xview_moveto(max(0.0, min(1.0, (target_dx - event.x) / dw)))
        self.canvas.yview_moveto(max(0.0, min(1.0, (target_dy - event.y) / dh)))
        self.redraw()

    def zoom_center(self, factor):
        self.zoom = max(0.5, min(80.0, self.zoom * factor))
        self.redraw()

    # ---- 状态 ----
    def on_motion(self, event):
        col, row = self.canvas_to_orig(event.x, event.y)
        x, y = vo.px_to_world(col, row, self.meta, self.h)
        self.set_status(f'光标 ({x:+.2f}, {y:+.2f})  缩放x{self.zoom:.1f}  '
                        f'障碍 {len(self.obstacles)} 条'
                        + ('  [选第二端]' if len(self.pending) == 1 else ''))

    def set_status(self, msg):
        self.status.config(text=msg)

    # ---- 编辑 ----
    def on_left(self, event):
        col, row = self.canvas_to_orig(event.x, event.y)
        x, y = vo.px_to_world(col, row, self.meta, self.h)
        self.pending.append((x, y))
        self.draw_marks()
        if len(self.pending) == 1:
            hint = {'line': '再点第二端', 'rect': '再点对角点',
                    'erase': '再点对角点'}[self.mode]
            self.set_status(f'第一点 ({x:+.2f}, {y:+.2f}); {hint} (r取消)')
            return
        (x0, y0), (x1, y1) = self.pending[0], self.pending[1]
        diag = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        if diag < self.min_line_len:
            self.pending.clear()
            self.draw_marks()
            self.set_status(f'两点太近({diag:.2f}m<{self.min_line_len}m), 请重新点')
            return
        if self.mode == 'line':
            ob = {'type': 'line', 'x0': round(x0, 3), 'y0': round(y0, 3),
                  'x1': round(x1, 3), 'y1': round(y1, 3),
                  'thickness': self.thickness}
            word = '线墙禁区'
        elif self.mode == 'rect':
            ob = {'type': 'rect', 'x0': round(x0, 3), 'y0': round(y0, 3),
                  'x1': round(x1, 3), 'y1': round(y1, 3)}
            word = '矩形禁区'
        else:
            ob = {'type': 'erase', 'x0': round(x0, 3), 'y0': round(y0, 3),
                  'x1': round(x1, 3), 'y1': round(y1, 3)}
            word = '擦除区'
        self.obstacles.append(ob)
        self.pending.clear()
        self.refresh_image()
        self.redraw()
        self.set_status(f'已加{word} #{len(self.obstacles)} '
                        f'({x0:+.2f},{y0:+.2f})->({x1:+.2f},{y1:+.2f})  已保存')

    def cancel_pending(self):
        self.pending.clear()
        self.draw_marks()
        self.set_status('已取消当前点选')

    def undo(self):
        if self.pending:
            self.cancel_pending()
            return
        if not self.obstacles:
            self.set_status('没有可撤销的障碍')
            return
        ob = self.obstacles.pop()
        self.refresh_image()
        self.redraw()
        self.set_status(f'已撤销最后一条 ({ob["x0"]:+.2f},{ob["y0"]:+.2f})->'
                        f'({ob["x1"]:+.2f},{ob["y1"]:+.2f})  剩 {len(self.obstacles)} 条')

    def on_delete_near(self, event=None):
        if not self.obstacles:
            self.set_status('没有障碍可删除')
            return
        if event is not None and hasattr(event, 'x'):
            col, row = self.canvas_to_orig(event.x, event.y)
        else:
            return
        px, py = vo.px_to_world(col, row, self.meta, self.h)
        # 找离点击点最近的一条记录(线=点到线段距离; 矩形/擦除=点到矩形距离)
        best_i, best_d = -1, 1e18
        for i, ob in enumerate(self.obstacles):
            if ob.get('type', 'line') in ('rect', 'erase'):
                d = _point_rect_dist(px, py, ob['x0'], ob['y0'], ob['x1'], ob['y1'])
            else:
                d = _point_seg_dist(px, py, ob['x0'], ob['y0'], ob['x1'], ob['y1'])
            if d < best_d:
                best_d, best_i = d, i
        if best_i < 0 or best_d > 0.6:  # 0.6m 内才算选中
            self.set_status(f'附近无障碍可删 (最近 {best_d:.2f}m)')
            return
        ob = self.obstacles.pop(best_i)
        self.refresh_image()
        self.redraw()
        self.set_status(f'已删除 #{best_i+1} ({ob["x0"]:+.2f},{ob["y0"]:+.2f})->'
                        f'({ob["x1"]:+.2f},{ob["y1"]:+.2f})  剩 {len(self.obstacles)} 条')

    def clear_all(self):
        if not self.obstacles:
            self.set_status('已无任何修改记录')
            return
        n = len(self.obstacles)
        self.obstacles.clear()
        self.refresh_image()
        self.redraw()
        self.set_status(f'已清空全部 {n} 条修改, 地图已回到底图  已保存')

    def restore_original(self):
        """一键复原: 清空所有修改记录, 地图回到最初未处理底图。"""
        if not self.obstacles:
            self.set_status('当前已是最初底图, 无需复原')
            return
        n = len(self.obstacles)
        self.obstacles.clear()
        self.refresh_image()
        self.redraw()
        self.set_status(f'已复原到最初地图(撤销了全部 {n} 条修改)  已保存')

    def set_mode(self, mode):
        self.mode = mode
        self.pending.clear()
        self.draw_marks()
        for k, b in self.mode_btns.items():
            b.configure(relief='sunken' if k == mode else 'raised',
                        bg='#cde7ff' if k == mode else self._btn_bg)
        name = {'line': '线墙禁区(点两端)', 'rect': '矩形禁区(点对角)',
                'erase': '擦除动障(点对角, 变可通行)'}[mode]
        self.set_status(f'当前模式: {name}')

    def print_saved(self):
        self.set_status(f'记录: {self.paths["obstacles"]}  地图: {self.paths["pgm"]}')
        print('障碍记录:', self.paths['obstacles'])
        print('合成地图:', self.paths['pgm'])

    def run(self):
        self.root.mainloop()


def _point_seg_dist(px, py, x0, y0, x1, y1):
    vx, vy = x1 - x0, y1 - y0
    wx, wy = px - x0, py - y0
    seg2 = vx * vx + vy * vy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / seg2))
    cx, cy = x0 + t * vx, y0 + t * vy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def _point_rect_dist(px, py, x0, y0, x1, y1):
    """点到轴对齐矩形的距离; 点在矩形内返回 0。"""
    xmin, xmax = sorted((x0, x1))
    ymin, ymax = sorted((y0, y1))
    dx = max(xmin - px, 0.0, px - xmax)
    dy = max(ymin - py, 0.0, py - ymax)
    return (dx * dx + dy * dy) ** 0.5


def main():
    p = argparse.ArgumentParser(description='虚拟障碍管理(无需 RViz, 可增删)')
    p.add_argument('map_yaml', nargs='?',
                   default='/home/unitree/ws_localization/src/go2_loc_bringup/maps/scans.yaml')
    p.add_argument('--thickness', type=float, default=0.10)
    p.add_argument('--margin', type=float, default=2.0, help='裁剪边距 m')
    args = p.parse_args()
    if not os.path.isfile(args.map_yaml):
        print(f'找不到地图: {args.map_yaml}')
        sys.exit(1)
    if not os.environ.get('DISPLAY'):
        print('当前无 DISPLAY, 无法弹窗。请在机器人桌面终端运行, 或先 export DISPLAY=:0')
        sys.exit(1)
    MapPicker(args.map_yaml, args.thickness, args.margin).run()


if __name__ == '__main__':
    main()
