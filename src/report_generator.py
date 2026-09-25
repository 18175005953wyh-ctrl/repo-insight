"""Render one analysis dictionary as JSON and an offline HTML report."""

import html
import json
import os
import tempfile
from pathlib import Path


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def size_label(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value / (1024 * 1024):.1f} MB"


def table(headers: tuple[str, ...], rows: list[tuple]) -> str:
    head = "".join(f"<th scope='col'>{escape(label)}</th>" for label in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>" for row in rows)
    if not body:
        body = f"<tr><td colspan='{len(headers)}' class='empty'>暂无数据</td></tr>"
    return f"<div class='table-scroll'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def render_html(data: dict) -> str:
    scan, git = data["scan"], data["git"]
    total_markers = sum(scan["marker_counts"].values())
    cards = "".join(
        f"<article class='metric'><span>{escape(label)}</span><strong>{escape(value)}</strong><small>{escape(note)}</small></article>"
        for label, value, note in (
            ("扫描文件", scan["file_count"], f"{scan['directory_count']} 个子目录 · {size_label(scan['total_bytes'])}"),
            ("非空文本行", scan["nonempty_lines"], f"{scan['text_file_count']} 个可读取文本文件"),
            ("历史提交", git["commit_count"], f"{git['committer_count']} 个提交者身份 · HEAD 可达历史"),
            ("待办标记", total_markers, "TODO / FIXME / BUG · 文本匹配"),
        )
    )
    extensions = sorted(scan["extension_counts"].items(), key=lambda item: (-item[1], item[0]))
    maximum = max((value for _, value in extensions), default=1)
    bars = "".join(
        f"<div class='bar-row'><span>{escape(extension)}</span><div class='track'><div class='bar' style='width:{100 * count / maximum:.2f}%'></div></div><b>{count}</b></div>"
        for extension, count in extensions[:8]
    ) or "<p class='empty'>没有可统计的文件。</p>"
    type_table = table(("扩展名", "数量", "占全部文件"), [
        (extension, count, f"{count / scan['file_count']:.1%}" if scan["file_count"] else "N/A")
        for extension, count in extensions
    ])
    checks = "".join(
        f"<li><span class='check {'yes' if present else 'no'}'>{'✓' if present else '–'}</span><span>{escape(name)}</span><b>{'存在' if present else '未找到'}</b></li>"
        for name, present in scan["engineering_files"].items()
    )
    commits = "".join(
        f"<li class='commit'><div class='commit-dot'></div><div><div class='commit-subject'>{escape(item['subject'])}</div><p><code>{escape(item['hash'][:10])}</code> · {escape(item['committer'])} · {escape(item['date'])}</p></div></li>"
        for item in git["recent_commits"]
    ) or "<li class='empty'>仓库尚无提交。</li>"
    largest = table(("文件路径", "体积"), [(item["path"], size_label(item["bytes"])) for item in scan["largest_files"]])
    markers = table(("标记", "文件", "行号", "文本片段"), [
        (item["marker"], item["path"], item["line"], item["excerpt"]) for item in scan["markers"]
    ])
    skipped = table(("路径", "原因"), [(item["path"], item["reason"]) for item in scan["skipped_text"] + scan["warnings"]])
    skipped_names = ", ".join(scan["skipped_directories"]) or "无"
    links = ", ".join(scan["skipped_links"]) or "无"
    history_note = "浅克隆：仅统计本地已有历史。" if git["shallow"] else "统计当前 HEAD 可达的本地历史，不访问网络。"
    marker_note = "仅列前 1000 条匹配，数量仍为全部匹配次数。" if scan["marker_details_truncated"] else "按独立单词匹配，不区分大小写；注释、字符串与文档中的标记也计入。"
    stylesheet = """
    :root{color-scheme:light;--ink:#172e3c;--muted:#617584;--green:#147862;--line:#dce6e9}
    *{box-sizing:border-box}body{margin:0;background:#f1f5f5;color:var(--ink);font:15px/1.65 'Segoe UI','Microsoft YaHei',sans-serif}
    .top{background:#122f3c;color:#fff;padding:15px 5%;display:flex;justify-content:space-between;align-items:center;gap:16px}.brand{font-weight:750;letter-spacing:1px}.brand i{display:inline-block;background:#65dbaf;width:9px;height:9px;border-radius:50%;margin-right:10px}.top span{font-size:12px;color:#b8d1d7}
    main{max-width:1240px;margin:auto;padding:36px 28px 42px}.hero{display:flex;justify-content:space-between;gap:24px;align-items:center;margin-bottom:26px}.eyebrow{color:var(--green);font-size:11px;letter-spacing:2px;font-weight:700;margin:0 0 8px}h1{font-size:36px;line-height:1.2;letter-spacing:-1px;margin:0 0 12px;overflow-wrap:anywhere}.subtitle{color:var(--muted);margin:0}.badge{border:1px solid #b9d8cc;background:#e8f6ef;color:#146b52;padding:8px 14px;border-radius:24px;white-space:nowrap;font-size:12px}.path{font-size:12px;color:var(--muted);overflow-wrap:anywhere;margin-top:9px}
    .metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:22px}.metric{background:#fff;border:1px solid var(--line);border-radius:12px;padding:20px 22px}.metric>span{color:var(--muted);font-size:13px}.metric strong{display:block;font-size:34px;line-height:1.3;margin:8px 0;color:var(--ink)}.metric small{font-size:11px;color:var(--muted)}
    .grid{display:grid;grid-template-columns:1.2fr 1fr;gap:22px;margin-bottom:22px}.panel{background:#fff;border:1px solid var(--line);border-radius:12px;padding:24px;min-width:0}.heading{display:flex;justify-content:space-between;gap:12px;align-items:baseline;margin-bottom:12px}h2{font-size:17px;margin:0}h3{font-size:14px;margin:20px 0 10px}.section-no{font-size:11px;letter-spacing:1px;color:#77908d}.note{color:var(--muted);font-size:12px;margin:5px 0 18px}.bar-row{display:grid;grid-template-columns:100px 1fr 35px;gap:10px;align-items:center;font-size:12px;margin:13px 0}.bar-row>span{overflow-wrap:anywhere}.bar-row b{text-align:right;font-weight:500}.track{height:10px;background:#edf2f3;border-radius:5px;overflow:hidden}.bar{height:100%;background:#1e967b;border-radius:5px}
    .checklist{list-style:none;padding:0;margin:16px 0}.checklist li{display:flex;align-items:center;gap:10px;border-bottom:1px solid #eef2f3;padding:12px 0;font-size:13px}.checklist b{margin-left:auto;font-weight:500;color:var(--muted);font-size:12px}.check{width:23px;height:23px;display:grid;place-items:center;border-radius:50%}.yes{background:#e7f6ed;color:#137550}.no{background:#fff2df;color:#996717}.callout{background:#f4f7f8;border-left:3px solid #8daab1;padding:12px 14px;color:var(--muted);font-size:12px;border-radius:3px}
    table{border-collapse:collapse;width:100%;font-size:12px;text-align:left}th{color:var(--muted);font-size:11px;font-weight:600;background:#f5f8f8}td,th{padding:10px;border-bottom:1px solid #e9eef0;overflow-wrap:anywhere;vertical-align:top}td:first-child{max-width:320px}table td:last-child{min-width:65px}.table-scroll{overflow:auto}details{margin-top:18px}summary{cursor:pointer;font-size:12px;color:var(--green);padding:5px 0}.commits{padding:0;margin:14px 0;list-style:none}.commit{display:flex;gap:13px;margin:0;padding:11px 0;border-bottom:1px solid #eef2f3}.commit-dot{width:8px;height:8px;flex-shrink:0;background:#239980;border-radius:50%;margin-top:8px}.commit-subject{font-size:13px;overflow-wrap:anywhere}.commit p{font-size:11px;color:var(--muted);margin:5px 0;overflow-wrap:anywhere}code{font-family:Consolas,monospace;font-size:11px;color:#286653}.empty{color:var(--muted);padding:16px}.full{margin-bottom:22px}.pill{display:inline-block;font-size:12px;background:#edf4f4;border-radius:5px;padding:4px 10px;margin-right:6px}.footer{border-top:1px solid #d7e1e5;padding-top:18px;display:flex;justify-content:space-between;gap:18px;color:var(--muted);font-size:11px;flex-wrap:wrap}
    @media(max-width:760px){main{padding:24px 16px}.hero{display:block}h1{font-size:28px}.badge{display:inline-block;margin-top:16px}.metrics{grid-template-columns:repeat(2,1fr);gap:10px}.metric{padding:15px}.metric strong{font-size:28px}.grid{grid-template-columns:1fr}.panel{padding:18px}.top span{display:none}}
    @media print{body{background:#fff}.panel,.metric{break-inside:avoid}.top{background:#fff;color:#172e3c}main{max-width:none;padding:20px}.metrics{gap:8px}details{display:block}}
    """
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<title>{escape(data['repository_name'])} · Repo Insight</title><style>{stylesheet}</style></head>
<body><header class="top"><div class="brand"><i></i>REPO INSIGHT</div><span>LOCAL REPOSITORY ANALYSIS · OFFLINE REPORT</span></header>
<main><section class="hero"><div><p class="eyebrow">REPOSITORY SNAPSHOT</p><h1>{escape(data['repository_name'])}</h1><p class="subtitle">用可核对的数据，了解仓库的规模、历史与工程文件。</p><div class="path">工作区文件快照 / Git 提交历史 / 工程文件完整度</div></div><span class="badge">本地分析 · 无外部请求</span></section>
<section class="metrics" aria-label="概览">{cards}</section>
<div class="grid"><section class="panel"><div class="heading"><h2>文件类型分布</h2><span class="section-no">01 / FILES</span></div><p class="note">横条按数量最多的类型归一化；展示前八类。</p>{bars}<details><summary>查看全部文件类型与占比</summary>{type_table}</details></section>
<section class="panel"><div class="heading"><h2>工程文件检查</h2><span class="section-no">02 / STRUCTURE</span></div><p class="note">检查仓库根目录中的约定文件与测试目录。</p><ul class="checklist">{checks}</ul><div class="callout">存在不代表内容完整或代码质量高。本报告不生成健康评分。</div></section></div>
<div class="grid"><section class="panel"><div class="heading"><h2>最大的十个文件</h2><span class="section-no">03 / SIZE</span></div><p class="note">按文件字节数降序；二进制文件也参与统计。</p>{largest}</section>
<section class="panel"><div class="heading"><h2>最近提交</h2><span class="section-no">04 / HISTORY</span></div><p class="note">{escape(history_note)} 时间为提交者时间，最多十条。</p><ol class="commits">{commits}</ol></section></div>
<section class="panel full"><div class="heading"><h2>待办标记</h2><span class="section-no">05 / MARKERS</span></div><div>{''.join(f"<span class='pill'>{escape(key)} · {value}</span>" for key, value in scan['marker_counts'].items())}</div><p class="note">{escape(marker_note)}</p><details><summary>展开文件位置与文本片段（{len(scan['markers'])} 条）</summary>{markers}</details></section>
<section class="panel full"><div class="heading"><h2>扫描范围与限制</h2><span class="section-no">06 / SCOPE</span></div><p class="note">工作区快照包含未提交和未跟踪文件，不读取 .gitignore 规则；非空文本行包含注释与文档，不等同于纯代码行。</p><p class="note">跳过文本统计：{len(scan['skipped_text'])} 个文件；读取警告：{len(scan['warnings'])} 条。仅读取不超过 5 MiB 的 UTF-8 文本。</p><details><summary>查看跳过项与读取异常</summary><p class="path">仓库路径：{escape(data['repository_path'])}</p><p class="path">排除目录：{escape(skipped_names)}</p><p class="path">链接或重解析点：{escape(links)}</p>{skipped}</details></section>
<footer class="footer"><span>Generated {escape(data['generated_at'])}</span><span>Python standard library · Git CLI · Schema {escape(data['schema_version'])}</span></footer></main></body></html>"""


def write_reports(data: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    # Complete both temporary files before replacing either existing report.
    pending = []
    try:
        for name in ("report.json", "report.html"):
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output, prefix=".repo-insight-", suffix=".tmp", delete=False) as file:
                pending.append((Path(file.name), output / name))
                if name.endswith(".json"):
                    json.dump(data, file, ensure_ascii=False, indent=2)
                    file.write("\n")
                else:
                    file.write(render_html(data))
        for temporary, destination in pending:
            os.replace(temporary, destination)
    finally:
        for temporary, _ in pending:
            temporary.unlink(missing_ok=True)
