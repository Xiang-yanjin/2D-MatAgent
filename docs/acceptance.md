# 从中文建模到计算结果

在 WSL 中进入项目并启用已有计算环境。WORK 指向自己的工作区。

```bash
source /home/administrator/software/UniMatSim/.venv/bin/activate
cd /home/administrator/agent/2D-MatAgent
WORK="$PWD"
python -m matagent --workspace "$WORK" --new
```

1. 说“用项目里有来源的单层 MoS₂ 原型给我建一个结构”，然后给出允许扫描的模型目录。有多个候选时，可用文件名指定权重。
2. 说“用刚才建的结构和选好的势，先做二维优化，固定晶胞，面外轴用 c，阈值 0.02 eV/Å，最多 100 步。收敛后分别做单点计算和结构信息分析。先给我看计划”。
3. 说“把力阈值改为 0.015，最多 50 步，其他保持原样”，再问“给我看最终 YAML，并说明改动”。
4. 输入 `/exit` 后，用下面的命令恢复。先问“刚才改好的那份计划用了哪个权重”，核对后说“执行刚才改好的那份计划。”
5. 执行结束后询问“最终最大原子力和广义最大力分别是多少”“两个分支读的是什么结构”“最终结构、单点原始结果和优化日志在哪里”。再次退出并恢复，仍可用“刚才那次计算”引用同一份记录。

```bash
python -m matagent --workspace "$WORK" --resume last
```

### 复跑正式验收

以下显式启用的用例会调用本地配置的语言模型服务，并在新的独立工作区授权一条真实 CPU 工作流。它复用第 8 步有效的加载证据；真实模型询问和材料计算均会消耗相应资源。

```bash
MATAGENT_LIVE_STEP12=1 python -B -m unittest discover -s tests -p test_live_step12.py -v
```

每次尝试的逐轮提问、回答、工具调用和前后计数保存在 `.matagent/acceptance/step12/live-*/dialogue.json`。通过验收后，`delivery.json` 记录工作区、会话、两版计划以及本次 run_id。结构、权重和计划按会话引用；运行的实际输入、参数、数值和输出文件按节点记录查询。节点记录内的 `outputs.structure_file` 指向导出的结构文件，`inputs.structure` 记录下游实际消费的结构字段及哈希。


## 本机完整验收

真实 DeepSeek 中文会话共 16 轮，正常退出并恢复两次。第 1–8 轮运行数为 0，第 9–16 轮运行数为 1。

| 对象 | 本次记录 |
|---|---|
| 会话 | `20261123-183427-ebf1` |
| MoS₂ 原型产物 | `str-20261123T183431Z-6528bea6efb7`，文件 SHA-256 为 `c0d39874684ced55096ef8a19f011f09c593c92a29d01a14f7997b2d9cbbd76f` |
| 选定权重 | `/home/administrator/software/models/rand2-2d.pth`，`pot-604525a185d54dae87114e1a` |
| 权重 SHA-256 | `604525a185d54dae87114e1a60835c602f7102ab45008deb09ed1814206735da` |
| 初版 → 修改版 | `plan-20261123T183513Z-61e9d084` → `plan-20261123T183546Z-756e4c9f` |
| 实际运行 | `20261123T183629Z-509f215a0218` |
| 优化结构对象 SHA-256 | `f887d3a4364644a7ac49216706c0f260fe9d60ca5154dd068ce07a9b732d63c6` |
| 各节点证据 | 运行目录内的 `artifacts/opt/node.json`、`artifacts/sp/node.json`、`artifacts/info/node.json` |

| 验收项 | 结果 | 核对依据 |
|---|---|---|
| 有来源的建模、目录发现、按文件名选势 | 真实接口通过 | 结构来源、有效 PBC 和本次选势保存在加载记录与逐轮工具记录中 |
| 修改计划、两次恢复、唯一执行授权 | 真实模型与真实计算通过 | 逐轮计数、两版计划、同一会话及 run.json |
| 优化结构传给单点与结构分析 | 真实模型与真实计算通过 | 优化的结构输出与两个节点输入的结构对象哈希相同 |
| 力阈值、残余力与用户回答 | 真实模型与真实计算通过 | 实际阈值 0.015 eV/Å，原子与广义最大力均为 0.004165233112871647 eV/Å |
| 完整 YAML、最终 VASP、单点原始 JSON 和日志 | 真实接口通过 | 展示的 YAML 与文件逐字一致，回答的三个产物路径均指向本次运行 |
| 歧义、拒绝误执行、幂等、失败传播、历史引用与新会话 | 离线或模拟通过 | regression.log 中原有用例通过 110 项，新增通过 2 项；失败 0 项，默认跳过 8 项可选联调 |
| 声子、弹性、BTE、训练 | 本轮待验证 | 参见第 11 步逐项执行覆盖表 |

会话引用修复位于 `conversation.py`，整句授权支持“执行刚才改好的那份计划”。对“上一次已经完成的计算”的查询从该会话持久化的执行结果定位，兼容已有记录。`potential_tools.py` 接受“用文件名为……的那个”作为选择意图。节点调度、模型加载证据复用和运行产物查询通过现有接口完成。

在项目目录中恢复本次真实对话或只读查询优化节点：

```bash
WORK="/home/administrator/agent/2D-MatAgent/.matagent/acceptance/step12/live-cbbc8428ea/workspace"
python -m matagent --workspace "$WORK" --resume 20261123-183427-ebf1
python -m matagent.execution status --workspace "$WORK" --id 20261123T183629Z-509f215a0218 --node opt
```

[逐轮对话](../.matagent/acceptance/step12/live-cbbc8428ea/dialogue.json) · [交付报告](../.matagent/acceptance/step12/delivery.json) · [运行配置](../.matagent/acceptance/step12/live-cbbc8428ea/workspace/runs/20261123T183629Z-509f215a0218/workflow.yaml) · [完整回归日志](../.matagent/acceptance/step12/regression.log)
