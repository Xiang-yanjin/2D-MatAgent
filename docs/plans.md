# 第 9 步：自动生成单任务 YAML

当前版本 1.3.0。通过现有中文 Agent，将已登记结构、已验证势模型、CPU 和优化参数整理成计划，由代码生成并校验 UniMatSim YAML。预览和校验不加载模型、不计算能量或力、不启动优化。

## 使用

在 WSL Ubuntu 中启动：

```bash
source /home/administrator/software/UniMatSim/.venv/bin/activate
cd /home/administrator/agent/2D-MatAgent
matagent --new
```

先按照[势模型说明](potentials.md)选择已验证权重。需要跨会话使用时，明确保存为当前项目默认。然后逐句输入：

```text
用已有原型建立一个 MoS₂ 单层，采用默认参数。
用刚才建的结构和项目默认势模型，在 CPU 上生成一个二维优化计划，力阈值 0.02 eV/Å，最多 100 步。只看配置。
把力阈值改成 0.015，最多 50 步，其他不变。
给我看最终 YAML，并说明相对原计划改了什么。
/exit
```

```bash
matagent --resume <会话编号> "这份计划用了哪个权重？结构文件和 YAML 在哪里？"
```

没有已选模型或结构时，会要求补充。多个候选须指定编号；“提高精度一点”需要明确数值。预览不会自动加载权重，失效的模型须先通过第 8 步工具重新验证和选择。

## 参数和来源

| 项目 | 当前规则 |
|---|---|
| 任务 | 一个 optimization 节点 |
| 结构 | 明确指定的 structure_id，或当前会话唯一结构 |
| 势模型 | 明确指定优先；否则会话选择优先于项目默认；明确要求项目默认时直接读取项目偏好 |
| 设备 | CPU；GPU 请求不会默默改成 CPU |
| fmax | 有限正数，单位 eV/Å；项目默认 0.02 |
| steps | 正整数最大优化步数；项目默认 200 |
| 二维约束 | is_2d=true、面外轴 c、c 垂直于 a–b 平面、relax_cell=false |
| 优化器 | BFGS |
| 结果配置 | save_json=true、save_structure=vasp、save_summary=false、resource_diagnostics=true |

布尔值不能充当数字，NaN、无穷大和未知工具参数会被拒绝。已有计划仅开放 fmax 和 steps 修改，其余字段继承父计划；更换结构或模型需创建新计划。项目默认变更不会改写历史计划。

plan.json 的 parameter_sources 区分用户输入、会话引用与项目默认，并附单位或对象编号。上述 fmax/steps 是项目默认，不是 UniMatSim 的隐式默认。

## 势模型映射

| 后端 | metadata.ml_params | 验证边界 |
|---|---|---|
| MatterSim | model_path、device=cpu | 本机真实权重加载记录可复用 |
| MACE | model_path、device=cpu、default_dtype=float32 | 配置映射已覆盖，真实权重加载须另行验证 |
| SevenNet | model_path、device=cpu | 配置映射已覆盖，依赖及加载须具备有效证据 |
| DeepMD / dp | model_file | CPU 控制来自运行环境，不添加未支持的 device 参数 |
| OpenCSP | model_path、明确的 model_variant | CPU 控制来自环境，不猜测模型变体 |

每份计划要求当前环境下有效的权重加载记录，能力登记不等同于加载成功。已知元素范围不包含结构元素时拦截；范围未知时明确记为未知。

权重保留在原目录，计划保存路径、SHA-256、加载证据位置及哈希。结构、权重或证据被修改、删除或移动时，旧计划校验失败，不换用其他文件。

## YAML、结构输入和周期性

UniMatSim 当前 YAML CLI 要求 --input 单独传入结构。workflow.yaml 保存模型和任务参数；plan.json 的 launch_spec 保存结构输入、命令参数列表、工作目录和必要环境变量。本阶段只记录，不执行该命令。

实际 YAML 的核心结构如下，路径和哈希由工具填入：

```yaml
metadata:
  name: single_2d_optimization
  potential_type: ml
  ml_potential: mattersim
  ml_params:
    model_path: /absolute/path/to/validated-weight.pth
    device: cpu
  slab_normal_axis: c
  checkpoint_sha256: <实际文件SHA-256>
tasks:
- name: optimization
  type: optimization
  config:
    is_2d: true
    relax_cell: false
    optimizer: BFGS
    fmax: 0.015
    steps: 50
    save_json: true
    save_structure: vasp
    save_summary: false
    resource_diagnostics: true
dependencies:
  optimization: null
```

slab_normal_axis 是本项目的几何检查元数据，不表示后端会自动旋转晶胞。结构和模型路径采用 WSL 可读绝对路径，产物另提供相对于工作区的路径；含空格、中文的路径经过测试。

POSCAR 不表达二维 PBC。源结构及用户声明来自结构登记，MatSimPy、UniMatSim/Pymatgen 和 ASE 的读入 PBC 分别记录。当前 POSCAR 后端按三维周期超胞读入，任务显式开启二维处理并固定晶胞。各项 PBC 证据不能相互替代。

## 工具和产物

```text
.matagent/plans/<plan_id>/
├── plan.json
├── input.vasp
├── workflow.yaml
└── validation.json
```

plan.json 使用 schema_version=2、kind=single_optimization。定义、输入和 YAML 保持不变；参数修改生成新编号，记录 parent_id、revision 和 changes_from_parent。validation.json 保存最新检查，plan.json 同时保留创建时的摘要。

| 工具 | 行为 |
|---|---|
| preview_optimization | 解析结构和模型引用，生成计划与 YAML；缺项时保存已确认输入并提问 |
| update_optimization_plan | 修改 fmax/steps，生成新版本 |
| inspect_plan | 重读计划、完整 YAML、来源和修改差异，刷新校验 |
| validate_plan | 重新校验并保存报告 |
| execute_plan | 新通用计划返回 execution_not_supported；原有固定样例保留执行入口 |

新计划没有 run_id，不借用旧运行的能量、收敛状态或最终结构。计划的模型查询使用该计划证据，历史运行的模型查询仍读取对应 run.json。

## 独立校验与重新编译

```bash
python -m matagent.plan_cli validate --workspace /path/to/project --plan-id <计划编号>
python -m matagent.plan_cli compile --workspace /path/to/project --plan-id <计划编号> --output regenerated.yaml
```

两条命令不依赖语言模型。compile 先校验，再写到工作区内尚不存在的 .yaml 文件，不覆盖原计划。成功退出码为 0，校验失败、阻塞或非法输出路径为 2。

校验检查严格参数类型、二维几何、文件哈希与加载证据、结构导出、YAML 回读一致性和真实 UniMatSim 解析。使用独立进程和临时检查点目录，前后核对文件未变化。

config_validated 仅表示配置和结构传递校验通过，同时 execution_supported=false；不表示优化成功、二维预测准确或材料稳定。缺少依赖或解析失败时报告具体字段、实际值、原因和修正建议。

## 源码依据

- run_workflow 位于 UniMatSim 的 unimatsim/ui/cli/commands/workflow.py：YAML 需使用 --input，模型来自 metadata。不能仅添加顶层 input 字段代替 CLI 参数。
- TaskConfigParser._parse_yaml 位于 unimatsim/workflows/task_parser.py：读取 metadata/tasks/dependencies，再调用 builder.add_task。
- WorkflowBuilder.get_execution_plan 位于 unimatsim/workflows/builder.py：校验时核对唯一 optimization 节点；构造器会创建检查点目录，因此使用临时目录。
- Optimization.__call__ 位于 unimatsim/workflows/tasks/optimization.py：给出优化参数及默认行为。上游解析器不完整检查任务参数，本项目补充严格校验。
- 本项目复用第 8 步 request_for/validation_current 和 PhysicsGuard 的参数、几何检查。

校验使用与现有执行入口一致的工作区 UniMatSim，保存实际模块路径、版本和关键源码哈希。后端变更后，旧计划需重新生成和校验。

## 回归与真实对话

```bash
python -m unittest discover -s tests -v
MATAGENT_LIVE_YAML=1 python -m unittest discover -s tests -p test_live_yaml.py -v
```

真实测试需要本机第 8 步有效验收记录及已配置模型服务。它复制登记、加载证据和项目偏好到独立工作区，保留原始证据来源，不复制权重、不重新加载、不修改主项目默认。

## 原有固定样例

```bash
matagent --new "按默认配置给我看原有固定 MoS₂ 样例的优化计划"
matagent "执行计划 <旧样例计划编号>"
python examples/mos2/run.py
```

旧样例保留固定权重及执行方式。新通用计划不会交给旧样例入口替代执行，旧记录无需迁移。此前实际优化结果见[会话与交付说明](conversations.md)和[MoS₂ 样例说明](mos2.md)。

## 本机真实验收（2026-11-22）

83 项离线回归通过，6 项可选真实/计算集成测试按开关跳过；另行通过本阶段真实 DeepSeek 对话验收。五种后端均通过实际 UniMatSim 配置解析，其中其他后端使用明确标记的模拟加载证据，不能据此声称真实模型加载成功。

真实对话复用第 8 步的 MatterSim / rand2-2d.pth 加载记录，没有新增模型加载或材料计算；主项目默认、原结构、权重和已有运行文件未变。

| 项目 | 实际结果 |
|---|---|
| 会话编号 | 20261122-064135-0364 |
| 原计划 | plan-20261122T064144Z-aef4f952 |
| 修改后计划 | plan-20261122T064157Z-e4ee103f |
| 结构编号 | str-20261122T064137Z-955aca0c74cf |
| 势模型编号 | pot-604525a185d54dae87114e1a |
| fmax | 0.02 → 0.015 eV/Å |
| steps | 100 → 50 |
| 模型、结构及约束 | 修改前后不变；CPU、c 面外、二维固定晶胞 |
| 状态 | config_validated；execution_supported=false |
| 恢复后查询 | 读取同一计划，权重及产物路径一致 |
| 执行请求 | execution_not_supported，没有新增运行 |

[真实对话和工具记录](../.matagent/acceptance/step9/report.json)、[交付摘要](../.matagent/acceptance/step9/delivery.json)、[离线日志](../.matagent/acceptance/step9/offline-tests.txt)、[真实测试日志](../.matagent/acceptance/step9/live-tests.txt)。

实际产物：[workflow.yaml](../.matagent/acceptance/step9/live-a40e9f6746/workspace/.matagent/plans/plan-20261122T064157Z-e4ee103f/workflow.yaml)、[plan.json](../.matagent/acceptance/step9/live-a40e9f6746/workspace/.matagent/plans/plan-20261122T064157Z-e4ee103f/plan.json)、[validation.json](../.matagent/acceptance/step9/live-a40e9f6746/workspace/.matagent/plans/plan-20261122T064157Z-e4ee103f/validation.json)。这些本机验收产物被 Git 忽略，不随源码发布。

恢复本次对话（会调用已配置语言模型）：

```bash
matagent --workspace /home/administrator/agent/2D-MatAgent/.matagent/acceptance/step9/live-a40e9f6746/workspace --resume 20261122-064135-0364 "这份计划用了哪个权重？结构文件和 YAML 在哪里？"
```

不调用语言模型的实际校验命令：

```bash
python -m matagent.plan_cli validate --workspace /home/administrator/agent/2D-MatAgent/.matagent/acceptance/step9/live-a40e9f6746/workspace --plan-id plan-20261122T064157Z-e4ee103f
```
