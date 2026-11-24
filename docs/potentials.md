# 第 8 步：势模型发现与选择

通过现有中文 Agent 扫描用户目录、识别候选、验证加载并保存项目默认。扫描不加载模型；验证只初始化所选计算器和权重，不计算能量、力或执行优化。

## 使用

在本机 WSL Ubuntu 终端运行：

```bash
source /home/administrator/software/UniMatSim/.venv/bin/activate
cd /home/administrator/agent/2D-MatAgent
matagent --new
```

逐句输入：

```text
扫描 /home/administrator/software/models ，用里面的二维模型。
选择 rand2-2d.pth，验证加载，以后在这个项目默认用它。
当前选的是哪个势模型，为什么判断它属于这个后端？给出权重路径、SHA-256 和加载证据。
/exit
```

该目录有 rand1 至 rand4 四份权重。Agent 先列出候选并请用户选定，不按顺序、时间或大小判断谁更好。“选择第二个”也可引用刚才扫描结果的顺序。

```bash
matagent --resume <会话编号> "刚才选的模型和加载日志在哪里？"
matagent --new "当前项目默认的势模型是什么？"
```

普通“用这个”仅改变会话选择；“以后默认用这个”才保存项目默认。先前登记的唯一目录可在后续请求中省略；多个目录时须指定目录。新项目不继承其他项目默认。

## 识别与来源

扫描用户明确指定的目录及子目录，跳过 Git、环境、缓存目录和符号链接。登记常见 .pth、.pt、.ckpt、.model、.pb、.safetensors、.h5、.hdf5、.pth.tar 文件，以及包含 model.json/model.pt/state.pt 的 MatGL 文件包。发现文件不表示当前后端已经支持其加载。

只读最多 4 MiB 的格式头、静态 pickle 操作码和伴随 JSON/YAML，不执行模型对象或脚本。伴随元数据支持 backend、framework 或 ml_potential 声明来源，OpenCSP 可用 model_variant 声明变体；也核对本项目及随源码提供的参考运行中、与权重哈希匹配的实际后端记录。未知或证据冲突时请用户说明来源，用户不必编写工作流 YAML。

四份现有权重都含 model_name=m3gnet，但 model/model_args/ema/validation_metrics/rbf.dn 等完整签名符合 MatterSim。m3gnet 是内部网络名称，实际加载后端为 MatterSim，不能仅用该字符串选择 MatGL。

文件名中的 2d 是候选标签，不证明训练范围或二维预测准确性。用户声明、静态识别和既有运行依据分别记录；加载成功也不证明当前结构的元素兼容性。

## 全部后端能力表

| 类型 | 本地权重入口 / 当前限制 |
|---|---|
| MatterSim | model_path、device=cpu；已有真实加载验收 |
| MACE | model_path、device=cpu、default_dtype=float32；已安装，无本阶段真实权重验收 |
| SevenNet | 使用 UniMatSim 当前 model_path 入口；本机缺加载依赖，导入兼容性仍须验证 |
| DeepMD / dp | model_file；已安装，无本阶段真实权重验收 |
| OpenCSP | model_path 和明确的 model_variant=l6/l12/l24；底层使用 DeepMD，不默认 L24 |
| CHGNet | 当前 UniMatSim 入口不接受任意本地权重，报告接口阻塞 |
| M3GNet 及两个 MP 变体 | 当前入口加载固定预训练模型，报告本地权重接口阻塞 |
| ORB | 当前入口调用预训练工厂，报告本地权重接口阻塞 |
| CHGNet2D | 当前只有枚举，没有加载实现 |
| Lennard-Jones / Buckingham | 经典势参数，不是机器学习权重 |
| CUSTOM | 没有通用的本地权重加载接口 |

全部覆盖指能力登记、来源识别以及明确的支持/阻塞结果，不表示所有类型都已真实加载成功。不会安装依赖、下载模型或用内置模型代替用户文件。

## 加载验证与失效

只对已明确选择或唯一候选执行验证，使用 UniMatSim 固定入口和本地绝对路径。在独立进程中运行，默认 120 秒超时，禁止网络连接。进程隔离不等于操作系统安全沙箱，验证会调用所选后端的加载器。

记录文件哈希、参数、Python/后端版本、计算器类型、设备证据、公开能力、日志和结果。MatterSim 额外检查参数键和形状，拒绝缺失、额外或形状不符的权重，防止宽松加载掩盖问题。

本阶段仅支持 CPU。MatterSim、MACE、SevenNet 显式传 CPU；DeepMD/OpenCSP 使用运行环境屏蔽 CUDA，并区分环境设置和后端实际公开的设备信息。无法读取实际设备时记录未知，不声称已从参数证实。显式要求 GPU 时会说明当前限制。

加载通过只说明当前环境能够初始化所选模型，不产生能量或力数值，不能把缺失结果显示为零。

同一权重和环境的有效验证可复用。文件内容、识别信息、后端版本或影响加载的环境变量变化后，旧验证失效。文件移动/删除时保留原选择并报告具体问题，不换用其他权重或路径。

## 工具与产物

原始权重只读引用，不复制进项目。

```text
.matagent/
├── potentials/
│   ├── registry.json
│   └── <potential_id>/<validation_id>/
│       ├── request.json
│       ├── worker.json
│       ├── validation.json
│       └── load.log
├── preferences.json
└── sessions/<session_id>.json
```

potential_id 来自内容哈希。相同内容的文件合并登记并保留路径；会话中的模型引用与结构、计划、运行引用分开。preferences.json 只保存当前项目默认，不保存语言模型 API 凭据。上述运行产物已被 Git 忽略。

| 工具 | 用途 |
|---|---|
| scan_potentials | 扫描登记，返回候选、证据、歧义和后端能力 |
| inspect_potential | 查看来源、验证记录、失效原因 |
| validate_potential | 独立进程加载；可补充用户明确说明的后端、OpenCSP 变体 |
| select_potential | 选择有效模型；明确要求时保存项目默认 |
| get_potential_selection | 查询会话选择和项目默认，返回来源和有效状态 |

旧会话缺失新字段时按空值兼容。选择模型后仍能继续编辑原结构。历史运行“用了哪个权重”仍读取该次 run.json，不使用当前默认回答。

## 测试与边界

离线测试使用明确标记的 synthetic 权重容器和模拟加载结果：

```bash
python -m unittest discover -s tests -v
```

真实验收使用已配置的语言模型和本地权重，只验证加载：

```bash
MATAGENT_LIVE_POTENTIALS=1 python -m unittest discover -s tests -p test_live_potentials.py -v
```

验收在独立项目目录完成，不替用户设置主项目默认。覆盖四个候选的澄清、rand2 实际加载、退出恢复、新会话默认和不同项目隔离。完整记录位于 .matagent/acceptance/step8/；没有真实权重的其他后端明确保留“真实加载待验证”。

第 8 步负责模型发现与选择。当前 1.3.0 已在第 9 步接入所选模型的单任务 YAML 生成与配置校验，见[单任务 YAML 说明](plans.md)。新计划的计算执行和多任务 DAG 尚未接入；原有固定 MoS₂ 样例需明确指定。

## 本机真实验收（2026-11-22）

67 项离线回归通过，5 项真实/计算集成测试按开关跳过；另外单独通过本阶段的真实 DeepSeek + MatterSim 加载集成测试。最终完整对话只启动一次加载进程，零次材料计算，四份源权重及原有结构、计划、运行文件哈希均未改变。

| 项目 | 实际结果 |
|---|---|
| 权重 | rand2-2d.pth |
| potential_id | pot-604525a185d54dae87114e1a |
| SHA-256 | 604525a185d54dae87114e1a60835c602f7102ab45008deb09ed1814206735da |
| 加载器 | mattersim.forcefield.potential.MatterSimCalculator |
| 实际设备 | CPU |
| 权重完整性 | missing_keys、unexpected_keys、shape_mismatches 均为空 |
| 会话 | 20261122-052321-ba54 |
| 主项目默认 | 未修改；偏好只写入独立验收工作区 |

[完整对话及工具记录](../.matagent/acceptance/step8/report.json)、[交付摘要](../.matagent/acceptance/step8/delivery.json)、[离线测试日志](../.matagent/acceptance/step8/offline-tests.txt)和[真实测试日志](../.matagent/acceptance/step8/live-test.txt)保存在本机运行产物中，不随 Git 源码发布。

恢复本次真实验收：

```bash
matagent --workspace /home/administrator/agent/2D-MatAgent/.matagent/acceptance/step8/live-b57f1dffb4/workspace --resume 20261122-052321-ba54 "刚才选的模型和加载日志在哪里？"
```

加载日志：[load.log](../.matagent/acceptance/step8/live-b57f1dffb4/workspace/.matagent/potentials/pot-604525a185d54dae87114e1a/load-e057b59bdce94ed3/load.log)；验证记录：[validation.json](../.matagent/acceptance/step8/live-b57f1dffb4/workspace/.matagent/potentials/pot-604525a185d54dae87114e1a/load-e057b59bdce94ed3/validation.json)。

验收中曾发现模型沿用历史回答并错误拼接绝对路径。现在程序先做只读证据刷新，再让模型回答；模型查询不能重新加载或改变默认。应用产生的工具消息也已验证与 DeepSeek 思考模式兼容。旧失败日志保留，最终通过记录如上。相对产物路径始终从工具返回的完整 workspace 根目录解析，不能再额外添加一层 .matagent。
