# B 论文 GRP 仿真实现路径

## 1. 文档目的

本文档用于固化 `B_基于时空测地线的太空原生网络预测性路由协议设计.docx` 的工程实现路径，明确：

- 论文核心思路在工程上的落地方式
- 当前仓库与论文声称结果之间的实际差距
- 一条可执行、可逐步验证的仿真路线
- 从轻量 Python 原型过渡到正式网络仿真的路径

该文档面向后续开发，不等同于论文正文，也不宣称当前已经完成真实仿真。

## 2. 论文核心思路

### 2.1 GRP 是什么

`GRP` 可理解为 `Geodesic Routing Protocol`，即基于时空测地线的预测性路由协议。其核心不是对“当前时刻拓扑”做最短路，而是对“未来一段时间内的链路可用窗口序列”做全局选路。

### 2.2 核心机制

论文中的关键机制可以拆成四层：

1. `WLT`（Window Link Table，窗口链路表）
   - 记录未来时间区间内每条链路何时出现、持续多久、容量多大、传播时延如何变化。

2. 时空展开图（time-expanded graph）
   - 将节点在不同时间片展开为不同状态点。
   - 链路不再只是“节点到节点”，而是“某时刻的节点状态”到“未来某时刻的节点状态”。

3. 因果约束 / 光锥裁剪
   - 任何候选路径都必须满足“包先到达，后转发”，不能违反时间因果关系。
   - 这一步会显著减少不可行路径搜索空间。

4. 预测性切换与局部回退
   - 正常情况下按预测路径提前切换。
   - 若窗口偏差、队列突增或链路异常，则局部修复而不是全局重算。

### 2.3 优化目标

`GRP` 的路径代价不是单一跳数，而是加权综合：

- 端到端时延
- 排队拥塞
- 链路中断风险
- 能耗或切换代价

因此，`GRP` 本质上是在求一条跨越未来时间窗口的最小代价时空路径。

## 3. 当前实际状态

当前仓库中没有发现可执行的 `GRP` 仿真工程。现状应定义为：

- 有论文文本与修订稿
- 有对 `GRP/WLT/预测路由` 的文字性描述
- 没有真实可运行的仿真代码
- 没有 `ns-3` 工程
- 没有 `WLT` 生成器
- 没有 `GRP` 路由实现
- 没有实验数据输出脚本

因此，论文中与仿真相关的部分，目前在仓库层面仍属于“待实现状态”。

## 4. 推荐实现总路线

推荐分两阶段推进，而不是直接上复杂全栈仿真。

### 阶段一：轻量 Python 原型

目标：先验证 `GRP` 的算法逻辑是否成立。

特点：

- 不依赖 `ns-3`
- 用 Python 快速实现
- 先做简化轨道与链路窗口模型
- 优先验证 `WLT -> 时空图 -> 路由搜索 -> 性能指标` 这条主链路

### 阶段二：正式网络仿真

目标：在更真实的协议栈、队列、业务流和链路动态下验证论文结论。

特点：

- 可迁移到 `ns-3`
- 引入更真实的链路容量、缓存、业务模型和控制开销
- 对比基线协议

## 5. 阶段一的最小可行实现

建议先落地以下 5 个脚本。

### 5.1 `simulation/gen_wlt.py`

功能：生成简化版 `WLT`。

输入：

- 星座参数，例如 Walker Delta
- 仿真总时长
- 时间步长
- 链路建立规则

输出：

- `output/wlt.json` 或 `output/wlt.csv`

最小版本可以先不做高精度轨道动力学，而是使用简化窗口模型：

- 固定轨道周期
- 固定可见性规则
- 固定星间链路建立条件

`WLT` 的基本字段建议包括：

- `src`
- `dst`
- `t_start`
- `t_end`
- `prop_delay_ms`
- `capacity_mbps`
- `risk`

### 5.2 `simulation/grp_router.py`

功能：根据 `WLT` 构建时空展开图，并执行 `GRP` 选路。

核心步骤：

1. 读取 `WLT`
2. 构建时间扩展节点
3. 连接满足因果关系的候选边
4. 定义综合代价函数
5. 运行最短路或最小代价路径搜索

建议先用 `NetworkX` 实现，避免过早进入底层优化。

建议代价函数形式：

```text
cost = a * delay + b * queue + c * risk + d * handover_penalty
```

第一版可先将 `queue` 用估计值代替，后续再与仿真状态耦合。

### 5.3 `simulation/sim_grp.py`

功能：建立轻量事件驱动仿真器。

需要模拟：

- 分组生成
- 路由选择
- 发送与到达事件
- 队列积压
- 窗口失效
- 局部重路由

建议最小事件类型：

- `packet_generate`
- `packet_enqueue`
- `packet_tx_start`
- `packet_tx_end`
- `window_close`
- `reroute`

该脚本是第一阶段的核心，因为它决定最终能否输出论文需要的性能指标。

### 5.4 `simulation/baseline_router.py`

功能：提供对照组。

建议至少实现 3 类基线：

- 反应式路由：AODV-like
- 准静态链路状态路由：quasi-static link-state
- 接触图路由：CGR-like

最小版本中不要求完全复刻标准协议，但必须保持方法论上的对照意义。

### 5.5 `simulation/analyze_grp_results.py`

功能：汇总实验输出并生成图表。

建议输出：

- 吞吐率
- 平均时延
- 95% 尾时延
- 路由切换次数
- 重路由时延
- 控制开销
- 丢包率

输出形式建议为：

- `output/results.csv`
- `output/fig_delay.png`
- `output/fig_throughput.png`
- `output/fig_overhead.png`

## 6. 推荐的数据流

建议采用以下数据流：

```text
constellation params
    -> simulation/gen_wlt.py
    -> wlt.json
    -> simulation/grp_router.py / simulation/baseline_router.py
    -> simulation/sim_grp.py
    -> results.csv
    -> simulation/analyze_grp_results.py
    -> figures / tables
```

这样可以把“窗口生成”“路由算法”“仿真执行”“结果分析”拆开，便于逐步调试。

## 7. 推荐的第一版仿真假设

为了尽快得到第一批可信结果，建议第一版使用简化假设，而不是追求一次性完整还原。

### 7.1 星座与时间参数

可优先采用论文文本中已经出现过的参数：

- Walker Delta 星座
- 轨道高度 `550 km`
- `d = 6`
- `K = 32`
- `H = 4`
- 控制更新周期 `2 s`
- 仿真时长 `24 h`

### 7.2 简化点

第一版允许的简化包括：

- 忽略高保真摄动轨道模型
- 采用规则化业务流
- 将排队模型先简化为有限缓存队列
- 将链路风险先建模为窗口中断概率或抖动概率

这些简化不会破坏 `GRP` 的核心验证目标，因为第一阶段验证的是“预测性时空路由”的机制，而不是完整物理层真实性。

## 8. 路由算法的最小工程定义

在代码层面，建议先把 `GRP` 明确定义为如下流程：

1. 根据 `WLT` 枚举从源节点到目的节点的时空可达边
2. 去除违反因果约束的边
3. 对每条边赋予传播、拥塞、风险、切换等代价
4. 在给定预测窗口范围内搜索最小总代价路径
5. 当实际窗口与预测偏离时，仅执行局部修复

只要这 5 步在代码中清晰存在，就已经形成了一个可被称为 `GRP prototype` 的原型。

## 9. 指标与论文结论映射

为了让后续结果能直接反哺论文，建议每个指标都对应一类论点。

| 指标 | 对应论点 |
|------|----------|
| 平均时延 | 预测路由能降低整体传输时间 |
| 95% 尾时延 | 预测路由能降低极端抖动 |
| 吞吐率 | 路由更能利用未来链路机会 |
| 重路由时延 | 预测切换减少临时性恢复成本 |
| 控制开销 | 相比频繁全局更新更稳定 |
| 丢包率 | 因果约束和窗口预测提高可达性 |

## 10. 从 Python 原型到 ns-3 的迁移路径

当 Python 原型完成后，再进入 `ns-3`，顺序建议如下：

1. 保留 `WLT` 生成器，作为外部输入
2. 在 `ns-3` 中实现 `GRP` 路由模块
3. 将链路窗口映射为时变拓扑或 contact plan
4. 将业务流、缓存、队列、链路误差接入正式仿真
5. 用同样的指标体系复现实验

原因很简单：如果先在 `ns-3` 中调试所有细节，会把“算法问题”和“仿真平台问题”混在一起，开发成本会显著升高。

## 11. 当前建议的直接下一步

最合理的落地顺序是：

1. 先写 `simulation/gen_wlt.py`
2. 再写 `simulation/grp_router.py`
3. 用一个最小场景验证是否能生成可行时空路径
4. 然后补 `simulation/sim_grp.py`
5. 最后加入基线和结果分析

如果只允许先做一件事，那么优先级最高的是：

`gen_wlt.py + grp_router.py`

因为这两部分决定了论文的核心创新是否真正被实现。

## 12. 当前实现状态声明

截至 `2026-05-15`，本仓库对 B 论文的仿真支持应表述为：

- 已完成论文思路梳理
- 已明确工程实现路径
- 已完成第一阶段最小 Python 原型
- 尚未完成正式高保真仿真
- 尚未形成可用于论文定稿的完整实验结果

这一表述应在后续写作、汇报和答辩中保持一致，避免把“论文中的目标性描述”误写成“仓库中已经落地的事实”。

## 13. 本地执行建议

当前会话中，建议优先使用已安装的标准 Python 解释器：

```powershell
$env:PYTHONPATH='C:\Users\lyr\Desktop\innovation\.pydeps'
& 'C:\Users\lyr\AppData\Local\Programs\Python\Python311\python.exe' scripts\your_script.py
```

这样可以避开 Windows Store `python.exe` 别名带来的不稳定行为。

## 14. 当前已落地脚本

截至当前版本，以下原型脚本已经落地：

- `simulation/gen_wlt.py`
  - 生成简化版 `WLT`
- `simulation/grp_router.py`
  - 基于 `WLT` 搜索一条可行的预测性时空路径
- `simulation/baseline_router.py`
  - 提供 `aodv_like / quasi_static / cgr_like` 三类基线路由
- `simulation/sim_grp.py`
  - 在简化负载模型下运行多业务流仿真并输出基础指标，支持 `--algorithm`

## 15. 最小运行方法

### 15.1 生成 WLT

```powershell
$env:PYTHONPATH='C:\Users\lyr\Desktop\innovation\.pydeps'
& 'C:\Users\lyr\AppData\Local\Programs\Python\Python311\python.exe' simulation\gen_wlt.py --output output\wlt_demo.json
```

### 15.2 计算一条 GRP 路径

```powershell
$env:PYTHONPATH='C:\Users\lyr\Desktop\innovation\.pydeps'
& 'C:\Users\lyr\AppData\Local\Programs\Python\Python311\python.exe' simulation\grp_router.py --wlt output\wlt_demo.json --src P00S00 --dst P03S04 --output output\grp_route_demo.json
```

### 15.3 运行轻量多流仿真

```powershell
$env:PYTHONPATH='C:\Users\lyr\Desktop\innovation\.pydeps'
& 'C:\Users\lyr\AppData\Local\Programs\Python\Python311\python.exe' simulation\sim_grp.py --wlt output\wlt_demo.json --output output\grp_sim_demo.json --flow-count 20 --flow-size-mbits 150
```

### 15.4 运行单条基线路由

```powershell
$env:PYTHONPATH='C:\Users\lyr\Desktop\innovation\.pydeps'
& 'C:\Users\lyr\AppData\Local\Programs\Python\Python311\python.exe' simulation\baseline_router.py --algorithm cgr_like --wlt output\wlt_demo.json --src P00S00 --dst P03S04 --output output\baseline_route_demo.json
```

### 15.5 运行基线多流仿真

```powershell
$env:PYTHONPATH='C:\Users\lyr\Desktop\innovation\.pydeps'
& 'C:\Users\lyr\AppData\Local\Programs\Python\Python311\python.exe' simulation\sim_grp.py --algorithm aodv_like --wlt output\wlt_demo.json --output output\aodv_like_sim_demo.json --flow-count 20 --flow-size-mbits 150
```

## 16. 当前原型边界

当前原型用于验证论文 B 的核心机制链条，而不是直接作为论文最终实验系统。它的边界包括：

- 使用简化 Walker 星座几何
- 使用规则化链路窗口与容量模型
- 使用轻量队列惩罚近似，不是完整缓存/MAC/PHY 联合仿真
- 已实现基线路由原型，但尚未完成论文级系统对比实验
- 尚未迁移到 `ns-3`

因此，当前结果应表述为“算法原型验证结果”，不应直接表述为“完整网络仿真结果”。
