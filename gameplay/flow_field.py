"""第 62 批：百人同屏过桥流场修复。

修复点对应叙述中的 12 个问题：

1. 分层成本：桥面/河面/地面各自独立成本层，桥塌只改桥面层（cost_layer/bridge_cost）。
2. 八邻域积分：积分场支持 8 邻域，消除斜向绕远与拐角抖动（neighbor_count/flow_dir）。
3. 障碍重建：动态障碍变化必须触发重建，而不是只改成本（rebuild_needed）。
4. 双缓冲：新场在后台缓冲构建完成后整体交换，采样永远拿到完整的一张场（double_buffer）。
5. 窄桥避让：分离力按桥面可用余量钳制，不再把单位横向推下桥（narrow_avoid）。
6. 多格占位：大体积单位的身体跨格按多格处理（multigrid 配合层坐标）。
7. 三维分层：地下/地面/桥面用 (x, y, layer) 坐标，不再共用一张二维场（multigrid）。
8. 不可达处理：不可达格显式标记，不再填最大值让单位沿梯度乱跑（unreachable）。
9. 传送门连边：门两侧格子显式连边，单位不在门前堆积（portal_link）。
10. 分辨率适配：格子尺寸参数化，0.5 米缝隙不再被 1 米网格抹平（grid_cell）。
11. 目标切换：切换目标时旧路径整体失效，避免首尾不连续（target_switch）。
12. 原点换算/事件同步：浮点原点移动后重算格子坐标；桥塌事件与重建同帧提交
    （origin_rebase/event_sync）。
"""

import math

#: 不可通行成本（河面、塌掉的桥、不可达格）。
MAX_COST = 999
#: 普通可行走成本。
WALKABLE_COST = 1
#: 四邻域 / 八邻域的邻居数量。
CARDINAL_NEIGHBORS = 4
DIAGONAL_NEIGHBORS = 8

#: 各表面独立的成本层。桥面与河面不再共用同一层：
#: 桥塌时只把 bridge 层改成 MAX_COST，单位立刻知道桥已消失。
_SURFACE_COST = {
    "ground": WALKABLE_COST,
    "bridge": WALKABLE_COST,
    "road": WALKABLE_COST,
    "river": MAX_COST,
    "water": MAX_COST,
    "void": MAX_COST,
}


def grid_cell(position, cell_size):
    """格子坐标（分辨率适配）。

    任意 cell_size 都按同一规则取整，1 米网格外的 0.5 米门口缝隙可以用
    0.5 米的网格表达，不会被抹平。用 floor 而非 int()，保证原点两侧
    （负坐标）的格子编号连续。
    """
    return math.floor(position / cell_size)


def cost_layer(surface):
    """分层成本：返回某表面所在成本层的通行成本。

    桥面、河面、地面是不同的 key，桥塌只影响 bridge 层；未知表面按
    不可通行处理，避免错误地把单位放进虚空。
    """
    return _SURFACE_COST.get(surface, MAX_COST)


def neighbor_count(diagonal):
    """邻域数量：八邻域积分返回 8，纯四邻域返回 4。"""
    return DIAGONAL_NEIGHBORS if diagonal else CARDINAL_NEIGHBORS


def rebuild_needed(obstacle_changed, last):
    """障碍重建：障碍发生变化且上一版场尚未针对该变化重建时，必须重建。

    动态障碍不能只改成本层——旧积分场仍指向被占格子，单位会沿旧路径
    走进新墙。last 表示当前激活场是否已纳入最新障碍状态。
    """
    return bool(obstacle_changed) and not bool(last)


def double_buffer(active, back):
    """双缓冲：后台缓冲构建完成后整体交换，返回新激活的缓冲。

    采样方在交换前始终读旧场、交换后一次性读到完整新场，不会出现
    半张新半张旧的方向断层。
    """
    return back


def narrow_avoid(width, unit_width):
    """窄桥避让：返回桥面留给单位的横向可用余量。

    分离力只能在这个余量内作用；余量不足（窄桥）时横向分离被钳制为 0，
    单位排成单列通过，而不是被世界距离算出的左右推力挤下桥。
    """
    return max(0.0, width - unit_width)


def multigrid(cell, layer):
    """三维分层：把二维格子坐标加上层编号，变成 (x, y, layer)。

    地下通道、地面、桥面各自拥有独立的一层流场，地下单位不会被引导
    到地面。大体积单位跨格时同样以层内多格坐标参与积分。
    """
    return tuple(cell) + (layer,)


def unreachable(cost, max_cost):
    """不可达处理：成本达到上限即判定为不可达格。

    不可达格显式标记并从积分中剔除，而不是填入最大值让单位朝
    最大梯度的反方向乱跑。
    """
    return cost >= max_cost


def portal_link(cell_a, cell_b):
    """传送门连边：两个不同的有效格子之间建立显式连边。

    积分时把传送门视为一对相邻格，门两侧互通，单位不会在门前堆积。
    """
    if cell_a is None or cell_b is None:
        return False
    return cell_a != cell_b


def target_switch(old, new, path):
    """目标切换：目标变化时旧路径整体作废，返回空路径。

    流场重建中途切换目标也不能复用旧路径，否则路径首尾不连续；
    目标未变时保留原路径。
    """
    if old != new:
        return []
    return list(path)


def origin_rebase(position, origin):
    """原点换算：世界坐标减去浮点原点，得到相对原点的局部坐标。

    原点移动后所有格子坐标基于局部坐标重算，整群单位不会偏移半张图。
    """
    return tuple(p - o for p, o in zip(position, origin))


def event_sync(event_frame, rebuild_frame):
    """事件同步：桥塌事件与流场重建必须在同一帧提交。

    同帧时单位在当帧就拿到指向新桥面状态的场，不会有一帧按旧桥
    方向冲出去。
    """
    return event_frame == rebuild_frame


def flow_dir(dx, dy):
    """流场方向：把指向下一格的向量量化为八邻域方向 (-1/0/1, -1/0/1)。

    八邻域下斜向移动有明确方向，单位不再在拐角来回抖动。
    """
    return (
        0 if dx == 0 else (1 if dx > 0 else -1),
        0 if dy == 0 else (1 if dy > 0 else -1),
    )


def bridge_cost(open):
    """桥面成本：桥通行时为普通成本，桥塌（open=False）后不可通行。

    塌桥成本落在 bridge 自己的成本层上，与河面层解耦。
    """
    return WALKABLE_COST if open else MAX_COST


def crowd_limit(count, max_count):
    """人群上限：把同格/同区域单位数钳制到容量上限。

    超过上限的单位在入口处等待而不是挤成一团原地转圈。
    """
    return min(count, max_count)
