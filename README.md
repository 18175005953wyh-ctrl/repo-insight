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

首次可运行版本 `5d98590` 的实际自分析结果（截图保存前）：

```text
Files: 13 | Directories: 3 | Non-empty text lines: 791
Commits: 1 | Committers: 1 | Markers: 28
Skipped text files: 0 | Warnings: 0
```

当时输出目录被排除，截图尚未保存到仓库。下面的图片对应这次真实运行；当前版本重跑会把新增图片和文档更新计入，因此不应要求数字永远一致。

![Repo Insight 自分析报告](screenshots/report.png)

## 异常与限制

- 无效路径、非目录、非 Git 仓库、Git 未安装、命令超时与报告写入错误会给出清晰提示。
- Git 的权限/安全目录错误会保留原因，不会自动修改 safe.directory 或其他配置。
- 单个文件无法读取或解码时跳过相应统计并记录；没有足够权限读取某个目录时，结果可能不完整。
- 仅本地分析，不调用 GitHub API；浅克隆只统计现有历史并提示。
- 不检查分支保护、CI 结果、依赖漏洞或测试覆盖率；提交次数与清单不代表项目质量。
- 文件遍历的主要开销是读取文本，以及对每个目录的条目排序。F 为文件/目录数、B 为读取字节数、K 为扩展名种类时，扫描保守上界约 O(B + F log F)，类型排序为 O(K log K)；维护前十文件时列表最多十一项，每个文件的这部分工作可视为常数。Git 需要读取可达提交历史，提交者身份输出会占用与历史规模相关的内存。
- 报告包含本地路径、提交者名称和匹配到的文本片段，分享前应检查内容；默认忽略生成的报告，不自动上传。

## 后续改进与练习到的能力

后续可以加入目录维度统计、提交时间趋势、两仓库对比、CSV 导出、Git ignore 规则支持及 GitHub Actions 自动报告；这些尚未实现。
本项目练习了路径处理、递归剪枝、字典与排序、安全调用外部进程、异常处理、结构化输出、HTML 转义、响应式布局与自动化测试。

## License

MIT License，见 LICENSE。
## Git文件变更热点

### 指标定义

本功能从固定 HEAD 的真实提交读取 `git log --numstat`，与“当前工作区文件扫描”分开统计。未提交的编辑不会改变 Git 热点；历史中已经删除的文件仍可能出现在热点中。

- `commit_count`：窗口内涉及该路径的不同提交数量；同一提交同一路径只计一次。
- `additions` / `deletions`：Git numstat 新增/删除行数之和。
- `churn`：新增 + 删除，不是净增行数，也不是复杂度或质量分数。
- `last_changed_at`：窗口内涉及该路径记录的最新作者时间（`%aI`），按带时区的真实时刻比较，不依赖日志顺序；作者时间可被修改，不保证等于合并时间。
- `binary`：窗口内有任一次二进制记录即为 true，行数及 churn 为 null，避免把未知行数当作 0。此类文件保留提交次数与日期，单独列在 `binary_files`，不进入数值前十。

排序固定为 churn 降序、commit_count 降序、path 字典序。JSON 的 `git_history.hotspots` 与 HTML 使用同一份前十数据；所有路径、日期和警告经过 HTML 转义。

### 使用方法

从项目目录运行（需要 Python 3.10+ 和 PATH 中可执行的 Git）：

```bat
python -B src/main.py . --output reports/hotspots --git-limit 100
python -B -m unittest discover -s tests -v
```

也可把 `.` 换成另一个本地仓库目录。`--git-limit` 默认 100，必须是十进制正整数；0、负数、非数字被明确拒绝。它限制分析提交数，**不是热点文件数量**。原有总提交数、最近十次提交等字段保持原含义，历史读取与热点使用相同的固定 HEAD。

报告新增 `git_history`，包含 `requested_limit`、`analyzed_commits`、`head`、`hotspots`、`binary_files`、`warnings`。仓库不足 N 次时记录实际提交数；空提交也计入分析窗口，空仓库返回空列表。Git 执行错误沿用原有非零退出码和清晰错误提示；损坏 numstat 记录警告后跳过，不使整份报告崩溃。

底层命令相当于：

```text
git log --numstat -z --no-renames --no-ext-diff --no-textconv --diff-merges=off --root --format=commit:%H%x09%aI%x00 -n 100 <固定HEAD> --
```

复用原有 `run_git()` 列表参数、30 秒超时、返回码和标准错误检查，不启用 shell。纯解析函数 `parse_numstat_log()` 与聚合函数 `build_file_hotspots()` 不运行 Git。使用 NUL 分隔保留空格、制表符、换行路径；numstat 字段仅按前两个制表符分割。

### 示例结果

本项目在 HEAD `cfadc22` 的实际自分析结果（完整 HEAD 以 `examples/hotspots-cfadc22.json` 为准）：请求 100 次，实际分析 **6 次**，Top 5 为：

| File | Commits | Additions | Deletions | Churn |
|---|---:|---:|---:|---:|
| README.md | 2 | 174 | 1 | 175 |
| src/git_analyzer.py | 3 | 157 | 0 | 157 |
| src/scanner.py | 1 | 138 | 0 | 138 |
| src/report_generator.py | 2 | 131 | 0 | 131 |
| tests/test_scanner.py | 1 | 109 | 0 | 109 |

以上数值来自添加本节文档和新测试之前的功能提交，不会伪装成持续变化的最新结果。提交新的代码、测试和 README 后再次运行，数字变化是正常现象。完整热点及二进制记录保存在 `examples/hotspots-cfadc22.json`，不含机器绝对路径。

如需精确重现该历史窗口，可在无同名目录时建立独立工作树，然后仍使用当前分析器读取它：

```bat
git worktree add --detach ../repo-insight-hotspot-example cfadc22
python -B src/main.py ../repo-insight-hotspot-example --output reports/pinned-hotspots --git-limit 100
```

### 如何解读

README 排名第一主要因为初次提交导入了文档，随后又补充说明。`src/git_analyzer.py` 涉及 3 次提交，包含初始实现、解析器和聚合功能迭代。二者都是可以解释的正常变化，不能据此认定代码质量差。

热点可以提示“值得阅读哪些文件”，后续应结合文件规模、变更目的、测试及缺陷记录。当前工具没有测量测试覆盖率，也不把 TODO 次数、文件大小或 churn 合成健康评分。

### 限制

- 默认只分析最近 100 次 HEAD 可达提交，按 Git 默认历史遍历选取窗口，不跨分支汇总。
- 二进制文件没有可靠行数；曾在窗口内被识别为二进制的路径整体退出数值排行。
- 使用 `--no-renames`，重命名前后按不同路径处理；不追踪文件身份。
- 合并提交计入窗口，但不统计其 diff，以免重复累加分支改动；因此合并时独有的冲突解决改动可能漏计。
- 初始提交相对空树统计；浅克隆仅有本地历史，报告会提示，浅边界可能将快照视为新增，结果不宜与完整克隆直接比较。
- 作者日期可乱序或人为设定；最新时间只反映当前窗口中记录的时间。
- 路径按已有 Git 封装的 UTF-8 文本模式读取，不保证非 UTF-8 原始路径字节的无损往返。
- 日志由原有封装一次捕获，提交数受限不等于输出字节数受限；大型仓库应使用较小窗口。
- 重复 numstat 记录只对提交次数去重，行数仍累加各记录；正常的无重命名单父提交中同路径只有一条记录。
- 高 churn 不等于代码质量评分。

### 升级测试

原有 38 项测试保持通过，新增 21 项，共 **59 项测试通过**。覆盖纯解析与聚合、空白和 Unicode 路径、损坏记录、二进制与文本转换、日期时区比较、排序、真实 Git 仓库、空仓库、空提交、浅历史提示、窗口与前十区分、无效参数、JSON/HTML 一致性和 HTML 转义。

`tests/fixtures/git_numstat.txt` 是从本仓库真实初始提交 `5d98590` 导出的 NUL 分隔 Git 输出；包含 NUL，编辑器可能将其显示为二进制。解析器测试直接读取固定夹具，不依赖当前仓库状态。
