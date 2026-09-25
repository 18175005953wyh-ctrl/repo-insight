# Repo Insight

使用 Python 标准库和 Git 命令行分析本地仓库，生成 JSON 数据和可直接打开的 HTML 可视化报告。

## 项目背景

项目数量增多后，可以用统一的口径观察各仓库的文件规模、历史和工程文件。本项目将文件遍历、字典统计、Git 输出解析、JSON 和 HTML 组织成一个可复现的命令行工具，用于学习 Python 与工程化开发。

报告只提供客观数据，不生成缺乏依据的“健康评分”，也不把代码行数或提交数量等同于项目质量。

## 主要功能

- 统计工作区文件数、子目录数、字节数和扩展名分布。
- 统计成功解码的 UTF-8 文本非空行，列出最大的十个普通文件。
- 搜索 TODO、FIXME、BUG，保留文件、行号和文本片段。
- 通过 Git 读取当前 HEAD 可达的提交总数、最近一次及十次提交、提交者身份数。
- 检查根目录 README.md、.gitignore、LICENSE 和 tests/ 或 test/。
- 生成同一份数据对应的 report.json 和离线、自包含、适配手机宽度的 report.html。
- 处理错误路径、非 Git 目录、Git 缺失、读取失败、解码失败、空仓库和报告写入错误。

## 环境与技术

- Python 3.10+；Git CLI。
- 只使用 Python 标准库：pathlib、os、subprocess、argparse、json、html、unittest 等。
- HTML/CSS 柱状图，无 JavaScript、外部字体、CDN 或图表依赖，无需 pip install。
- 实测环境：Windows、Python 3.12.14、Git 2.53.0.windows.3。其他系统尚未实测。

检查环境：

```sh
python --version
git --version
```

Windows 如果 `python --version` 没有输出或跳转商店，请先确认 Python 已正确安装并加入 PATH；也可以用 `py -3` 代替下面的 `python`。VS 的 C 编译环境不等于 Python 环境，本项目不需要 CMake。

## 使用方法

在 **repo-insight 文件夹**打开终端：

```sh
python src/main.py .
python src/main.py "D:/Projects/my-project" --output reports
python src/main.py --help
```

传入仓库内部子目录时会找到并分析整个仓库根目录。目标可以是有空格的路径，要加引号。
目标必须是 Git 工作区，支持尚未提交的空仓库、detached HEAD 和 Git worktree；不支持 bare 仓库。
默认报告目录为**启动命令时当前目录下的 reports**；`--output` 可指定其他路径，缺失的父目录会创建。
不能把输出设为被分析仓库根目录、它的祖先目录或 `.git` 内部。

运行后：

```text
reports/report.json
reports/report.html
```

双击 report.html 即可在浏览器查看，无需服务器。也可以在 Windows 命令提示符执行 `start reports\report.html`，PowerShell 执行 `Start-Process reports/report.html`。
再次运行会替换同名报告。程序先写临时文件，再逐个替换正式文件；单个文件替换是原子的，但两个文件不构成跨文件事务，若替换过程中失败请重跑。

## 统计口径

| 指标 | 定义 |
|---|---|
| 文件总数 | 扫描范围内能取得元数据的普通文件，包含未提交和未跟踪文件 |
| 子目录总数 | 包含空目录，不含仓库根目录及排除目录 |
| 文件大小 | 文件系统提供的字节数，不是 Git 压缩体积或磁盘占用空间 |
| 文件类型 | 最后一个扩展名转小写；无扩展名和 `.gitignore` 等记为 `[no extension]` |
| 非空文本行 | 不超过 5 MiB、能以 UTF-8/UTF-8 BOM 解码且无 NUL/异常控制字符的文件中，去掉空白后非空的行 |
| 标记数量 | TODO/FIXME/BUG 独立单词的出现次数，不区分大小写，同一行多次出现分别计数 |
| 提交总数 | 当前 HEAD 可达的本地提交，包含合并提交，不合并其他未可达分支的历史 |
| 提交者数量 | Git committer 的 `(name, email)` 不同身份数，遵循 Git 的 mailmap，不等同于独立自然人数 |

非空行**包含注释、Markdown、配置和测试**，不做语言语法识别。二进制文件也计入文件数量和大小，但不计文本行。
文本判断不只看扩展名：例如 `.py` 也可能因内容无法解码而跳过，未知扩展名的可解码文本仍可计数。
大于 5 MiB、二进制、解码失败、读取异常的原因都可在报告中查看。
标记可能来自文档、字符串或测试，不代表真实缺陷。最多展示 1000 条匹配详情，数量统计仍覆盖全部匹配。

递归跳过以下名称的目录（不区分大小写）：

```text
.git build out node_modules .venv venv __pycache__
.vs .idea .pytest_cache .mypy_cache
```

还会排除本次 `--output` 目录、`.git` 工作区指针文件、符号链接和 Windows 重解析点。不跟随链接访问仓库外文件。不解析 `.gitignore`，因此其他自定义生成目录需要自行整理；旧报告位于其他目录时也可能被扫描。
工程文件只检查根目录约定名称与类型，不验证内容，不接受链接；名称大小写是否等价取决于操作系统文件系统。

## 实现思路与学习路线

```text
命令行路径 → Git 根目录校验 → Git 历史快照 + 文件扫描
                                   ↓
                              一个 Python 字典
                                   ↓
                           JSON 数据 / HTML 页面
```

1. `scanner.py`：用 Path 处理路径，用 `os.walk(topdown=True)` 遍历，并修改 `directories[:]` 提前剪掉忽略目录。`Path.rglob('*')` 也能递归，但不方便在进入大型目录前剪枝，因此这里选择 os.walk。
2. `git_analyzer.py`：通过 `subprocess.run()` 的参数列表调用 Git，不使用 `shell=True`。通过 NUL 分隔字段解析提交，避免提交标题中的竖线等字符造成错列；Git 调用超时为 30 秒。
3. `report_generator.py`：同一字典交给 `json.dump()` 与 HTML 渲染，所有路径、扩展名、提交文字及标记片段通过 `html.escape()` 转义，横条宽度来自数量比例。
4. `main.py`：argparse 获取目标与输出目录，组织执行，普通错误输出英文说明并返回非零状态。

Git 只执行本地读取命令，不拉取、推送或更改被分析仓库的配置。工具会清理继承的 GIT_* 路由变量，避免环境变量把分析指向另一个仓库。
Git 数据使用固定 HEAD 提交作为快照；工作区文件在遍历时读取，不是原子快照，分析时尽量不要同时修改文件。

## 项目结构

```text
repo-insight/
├── src/
│   ├── main.py
│   ├── scanner.py
│   ├── git_analyzer.py
│   └── report_generator.py
├── tests/
│   ├── support.py
│   ├── test_scanner.py
│   ├── test_git_analyzer.py
│   ├── test_report_generator.py
│   └── test_cli.py
├── reports/.gitkeep
├── screenshots/
├── .gitignore
├── LICENSE
└── README.md
```

## 自动化测试

```sh
python -B -m unittest discover -s tests -v
```

2026-09-25 在上述 Windows 环境实际运行：**38 项测试全部通过，无跳过**。
测试涵盖文件统计、剪枝、扩展名、文本/BOM/大小限制、标记、前十文件、工程清单、读取异常、空仓库、12 次真实提交与两个提交者、最近十次截断、detached HEAD、Git 缺失和超时、无 shell 调用、HTML 转义、JSON 回读、报告写入失败清理及重复运行稳定性。
链接跳过与读取权限异常使用 mock，避免依赖 Windows 的符号链接权限；Git 历史与 CLI 主要使用临时真实仓库，结束后清理。测试不修改 Git 全局身份配置。

## 真实运行与截图

项目会对自己的本地 Git 仓库运行 `python src/main.py . --output reports`。示例报告与截图是运行时快照，后续新增文档、图片或提交后数字会变化。

![Repo Insight 自分析报告](screenshots/report.png)

## 异常与限制

- 无效路径、非目录、非 Git 仓库、Git 未安装、命令超时与报告写入错误会给出清晰提示。
- Git 的权限/安全目录错误会保留原因，不会自动修改 safe.directory 或其他配置。
- 单个文件无法读取或解码时跳过相应统计并记录；没有足够权限读取某个目录时，结果可能不完整。
- 仅本地分析，不调用 GitHub API；浅克隆只统计现有历史并提示。
- 不检查分支保护、CI 结果、依赖漏洞或测试覆盖率；提交次数与清单不代表项目质量。
- 文件扫描约为 O(F + B + L log L) 中的主要读取成本，实际遍历每文件维护最多十个元素，近似 O(F + B)；F 是文件/目录数量，B 是读取文本总字节数。文件类型排序为 O(K log K)，K 为扩展名种类。Git 需要读取可达提交历史，作者身份输出会占用与历史规模相关的内存。
- 报告包含本地路径、提交者名称和匹配到的文本片段，分享前应检查内容；默认忽略生成的报告，不自动上传。

## 后续改进与练习到的能力

后续可以加入目录维度统计、提交时间趋势、两仓库对比、CSV 导出、Git ignore 规则支持及 GitHub Actions 自动报告；这些尚未实现。
本项目练习了路径处理、递归剪枝、字典与排序、安全调用外部进程、异常处理、结构化输出、HTML 转义、响应式布局与自动化测试。

## License

MIT License，见 LICENSE。
