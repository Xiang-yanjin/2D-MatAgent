# MoS₂ 参考样例

`runs/20261120T143706Z-09f1c9a4/` 是 2026 年 11 月 20 日一次真实优化运行的完整副本，包含 9 个文件。原始记录来自本机项目的同名 `runs/` 目录，复制时逐文件核对 SHA-256。

初始结构来源于 MatSimPy 的 `tests/symmetry/test_kpath_2d.py::test_buckled_mos2_monolayer_is_hexagonal`。计算使用 UniMatSim 2.1.0、MatterSim 1.2.2 和本地 `rand1-2d.pth`，固定晶胞，沿 c 轴设置二维模式。完整版本和源码提交见[运行记录](runs/20261120T143706Z-09f1c9a4/run.json)。

| 结果 | 值 |
|---|---|
| 收敛状态 | 已收敛 |
| 总能量 | −15.636652946472168 eV |
| 最终最大原子力 | 0.004807979334145784 eV/Å |
| 收敛阈值 | 0.02 eV/Å |

从项目根目录查询该样例。

```bash
matagent --demo --workspace examples/mos2 "上次 MoS₂ 优化收敛了吗？最终最大原子力是多少，证据在哪？"
```

执行新的优化时使用 `python examples/mos2/run.py`，结果写入项目根目录的 `runs/`。默认配置为本目录的 `workflow.yaml`，其中检查点路径对应原始 WSL 机器。跨机器运行时，请在配置副本中填写已有检查点的绝对路径并用 `--config` 指定，脚本会校验文件 SHA-256。检查点的长期来源与训练数据仍待核实。参数和产物解释见[优化文档](../../docs/mos2.md)。
