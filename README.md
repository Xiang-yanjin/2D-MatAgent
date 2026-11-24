# 2D-MatAgent

用中文建立或导入二维结构，从指定目录选择机器学习势，再把计算顺序生成可预览的 UniMatSim 工作流。确认计划后即可执行，并在同一会话中追问每个任务用了什么结构、优化是否收敛，以及结果文件在哪里。

## 快速开始

以下命令适用于本机已配置好的 WSL Ubuntu 环境。首次在其他机器使用，请先看下方的「第一次配置环境」和「语言模型配置」。

```bash
source /home/administrator/software/UniMatSim/.venv/bin/activate
cd /home/administrator/agent/2D-MatAgent
WORK="$HOME/matagent-work/mos2"
mkdir -p "$WORK"
python -m matagent --workspace "$WORK" --new
```

看到 `你>` 后逐句发送，等 Agent 回答再继续。

1. **建模**　“用项目里有来源的单层 MoS₂ 原型给我建一个结构。告诉我有多少个原子，面外方向是哪一轴。”
2. **选势**　“看看 /home/administrator/software/models 里有哪些机器学习势。我想用里面的二维 MatterSim 模型，在 CPU 上算。” 有多个候选时可回答“用文件名为 rand2-2d.pth 的那个”。首次使用若缺少加载证据，可以说“验证加载 rand2-2d.pth，通过后选用它”。
3. **规划**　“用刚才建的结构和选好的势，先做二维优化，面外轴用 c，固定晶胞，力阈值 0.02 eV/Å，最多 100 步。收敛后，对优化后的结构分别做单点计算和结构信息分析。先给我看计划。”
4. **修改**　“把优化的力阈值改成 0.015 eV/Å，最多 50 步，其他保持原样。给我看最终 YAML，并说明改了什么。”
5. **执行**　核对参数后说“执行刚才改好的那份计划。” 前四步用于准备输入和计划，这一句授权启动计算。
6. **查询**　“优化收敛了吗？最终最大原子力是多少？两个分支读了哪份结构？给我最终结构、单点原始结果和优化节点日志的路径。”

输入 `/exit` 退出。下次激活同一 Python 环境后，用以下命令恢复，再问“刚才那次计算用了哪个权重？”：

```bash
python -m matagent --workspace "$HOME/matagent-work/mos2" --resume last
```

**已验收的流程。** 第 12 步用正式 DeepSeek 终端完成了 16 轮中文对话和两次恢复。修改版计划只执行一次，最终最大原子力为 0.00416523 eV/Å，两个分支读到的结构哈希均与优化输出一致。详见[完整验收记录](docs/acceptance.md)。

## 当前支持范围

| 能力       | 使用范围与依据                                                                                                                                                                                             |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 结构建模   | 支持 MoS₂、石墨烯、h-BN 参考原型，以及 POSCAR、CIF、MatSimPy JSON 导入。可以扩面内超胞、按位点替换、调整真空、导出结构。二维编辑要求 c 轴垂直于 a–b 平面。见[结构建模说明](docs/structures.md)。          |
| 本地势模型 | 扫描指定目录，登记候选与哈希，按需验证加载。普通选择用于当前会话，明确要求“以后默认用”可保存项目默认。MatterSim CPU 已有真实计算记录。各后端配置映射见[势模型说明](docs/potentials.md)。                  |
| 工作流     | 单任务和多节点 DAG 均支持预览、修改和执行授权。纯原生图生成 UniMatSim YAML，混合图生成工作流清单和原生节点配置。详见[单任务 YAML](docs/plans.md)和[DAG 工作流](docs/workflows.md)。                          |
| 执行与检查 | 本机 CPU 实测包括结构优化、单点计算、结构信息分析、对称性分析和 CIF 导出。上游失败时阻断依赖节点，独立分支可以继续。声子、弹性、EOS、BTE、训练等任务的适配和实测状态见[逐项执行覆盖表](docs/execution.md)。 |
| 结果解释   | 根据节点原始结果解释阈值、原子力、广义力及收敛状态。固定晶胞下的优化收敛只支持该模型与约束下的局部几何结论。见[PhysicsGuard 说明](docs/physics_guard.md)。                                                  |

## 结果与会话

以下路径均相对于 `--workspace` 指定的目录。用户可以直接问“最终结构文件在哪里？”。

| 要查的内容                 | 位置                                                                                                                                      |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 结构及来源                 | `.matagent/structures/<structure_id>/structure.json` 和同目录的 `manifest.json`                                                       |
| 势模型和默认偏好           | `.matagent/potentials/`、`.matagent/preferences.json`；权重本体保存在原目录                                                           |
| 每版计划及预览配置         | `.matagent/plans/<plan_id>/plan.json`、同目录的 `workflow.yaml`                                                                       |
| 整次运行及实际配置         | `runs/<run_id>/run.json`、同目录的 `workflow.yaml`；混合图的原生节点配置在 `native/`                                                |
| 单个节点的输入、结果及日志 | `runs/<run_id>/artifacts/<节点名>/` 内的 `node.json`、`raw.json`、`stdout.log` 和 `stderr.log`                                  |
| 最终优化结构               | 优化节点 `node.json` 的 `outputs.structure_file.path` 给出导出文件。下游实际消费的结构字段和哈希记录在消费节点的 `inputs.structure` |
| 对话与引用                 | `.matsimpy/sessions/` 保存消息和工具调用，`.matagent/sessions/` 保存会话引用和已完成工具结果                                          |

`--new` 开启新会话，`--resume last` 恢复指定工作区最近保存的会话。要选择更早的一次，先用 `--list-sessions` 查看列表，再用 `--resume` 指定会话编号。普通执行请求会复用同一版本已登记的运行；要另算一次，请明确说“重新执行这份计划”。查询结果与恢复会话均可复用已有记录。

## 源码导航

| 子包 | 开发时从这里找 |
|---|---|
| [assistant](src/matagent/assistant/) | 中文对话、模型配置、工具注册、会话恢复 |
| [structures](src/matagent/structures/) | 建模、几何编辑、结构登记与来源 |
| [potentials](src/matagent/potentials/) | 本地权重发现、选择、加载验证 |
| [planning](src/matagent/planning/) | 单任务 YAML、DAG、能力目录与配置校验 |
| [execution](src/matagent/execution/) | 已授权工作流的执行、节点状态和运行证据查询 |
| [physics](src/matagent/physics/) | 二维约束、几何和收敛证据检查 |

## 第一次配置环境

**从 wheel 安装。** 在具备 MatSimPy 及其 AI 依赖的环境中安装分发文件。规划和执行还需在同一解释器中安装配套 UniMatSim（已验收提交 `6afd5fc`）和任务依赖。在 wheel 所在目录安装后，就可以在自己的工作区开始离线查询。

```bash
python -m pip install ./2d_matagent-1.4.0-py3-none-any.whl
matagent --demo --workspace "$HOME/matagent-work/mos2" "列出已有运行"
```

wheel 携带固定 MoS₂ 示例的 YAML、参考结构和脚本；本地权重由用户提供。新工作区首次查询会显示空的运行列表。构建命令与子进程验收见[开发说明](docs/development.md)。

**从源码开发。**

需要 Python 3.10 或以上版本，从相邻源码目录安装 MatSimPy。执行通用工作流还需要配套的 UniMatSim 实现及相应任务依赖，目录布局如下：

```text
workspace/
├── matsimpy/
├── UniMatSim/           # 执行新优化时需要
└── 2D-MatAgent/
```

在本项目目录使用准备好的 Python 环境安装：

```bash
python -m pip install -e ../matsimpy -e .
```

查询参考记录不需要加载势模型，可先运行：

```bash
matagent --demo --workspace examples/mos2 "上次 MoS₂ 优化收敛了吗？最终最大原子力是多少，证据在哪？"
```

`--demo` 是确定性的离线查询测试模型，支持列出、最近运行和按编号查询。完整自然语言计划与执行使用已配置的语言模型。程序测试还通过可注入模型验证多轮工具流程。

执行新优化需要 UniMatSim、MatterSim、PyTorch、ASE 等计算依赖，以及 YAML 指定的本地检查点。环境版本、结构来源和独立复跑命令见 [MoS₂ 优化文档](docs/mos2.md)。程序不会自动安装包或下载权重。换机器时需准备相同权重并核对 YAML 中的路径与 SHA-256。

## 语言模型配置

本机直接读取 `~/.config/2d-matagent/model.json`，已配置的模型为 `deepseek-v4-pro`。新环境可创建以下配置，填写自己的凭据和服务支持的模型名：

```json
{
  "provider": "deepseek",
  "api_key": "YOUR_API_KEY",
  "base_url": "https://api.deepseek.com",
  "model": "YOUR_MODEL_NAME"
}
```

将配置目录权限设为 700、文件权限设为 600。可选字段 `reasoning_effort` 取决于所用模型支持的参数。配置保存在用户目录，不放入项目或会话文件。

也可使用环境变量 `DEEPSEEK_API_KEY`，并通过 `MATSIMPY_AI_MODEL`、`MATSIMPY_AI_BASE_URL` 指定模型和地址。兼容服务支持 `OPENAI_API_KEY`、`OPENAI_MODEL` 和 `OPENAI_BASE_URL`。显式环境变量优先于本地配置；同时设置两组凭据时优先 DeepSeek。缺少配置时程序提示配置方式，不会自动降级为测试模型。

## 开发与验收

在项目根目录运行离线回归：

```bash
python -B -m unittest discover -s tests -v
```

如需从正式终端复跑完整自然语言验收，使用下面的显式开关。此用例会调用已配置的真实语言模型，在新工作区授权一次真实 CPU 工作流，并复用本机第 8 步已有的有效加载证据。

```bash
MATAGENT_LIVE_STEP12=1 python -B -m unittest discover -s tests -p test_live_step12.py -v
```

第 12 步验收时，离线回归通过 112 项、失败 0 项、跳过 8 项可选联调，真实端到端用例单独通过。会话、两版计划、运行编号和节点证据见[自然语言验收说明](docs/acceptance.md)。

原有固定 MoS₂ 样例的独立复跑命令见[样例说明](docs/mos2.md)。代码组织和开发环境见[开发说明](docs/development.md)，配套 UniMatSim 的接口变更见[上游改动说明](docs/upstream-step10.md)。
