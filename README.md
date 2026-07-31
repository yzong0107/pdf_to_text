# PDF to Text

把扫描版 PDF（尤其是中文）通过 OCR 转成**可搜索、方便复制**的纯文本 `.txt`。

适合影印件、扫描书等「看得见字但选不中 / 复制很痛苦」的 PDF。中文优先，英文也可识别。

## 功能

- 扫描件 OCR（PyMuPDF 渲染 + RapidOCR）
- 有文字层的 PDF 也会直接抽取，不足时再走 OCR
- 智能合并视觉换行：正文连成段落，方便复制；章节名等短标题仍单独成行
- 按页输出 `===== 第 N 页 =====`，便于搜索定位做笔记
- 支持指定起始页 / 页数，调试大文件不必一次跑完全书

## 目录结构

```
pdf-to-text/
├── input/             # 放入待转换的 PDF
├── output/            # 生成的 .txt
├── convert.py         # 命令行入口
├── requirements.txt
├── README.md
└── .venv/             # 本地虚拟环境（不提交到 Git）
```

## 环境要求

- Windows / macOS / Linux
- Python 3.10+（推荐 3.12）
- 首次运行会自动下载 OCR 模型

## 安装

```powershell
# 在项目根目录创建虚拟环境（示例使用本机 Python 3.12）
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# 若提示无法运行脚本，可先执行：
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

pip install -r requirements.txt
```

不激活环境也可以直接调用：

```powershell
.\.venv\Scripts\python.exe convert.py test.pdf
```

## 用法

1. 将 PDF 放到 `input/`
2. 在项目根目录运行：

```powershell
$env:PYTHONUTF8=1   # Windows 下避免控制台中文乱码

# 默认：input/test.pdf → output/test.txt
python convert.py test.pdf

# 只转部分页（大文件建议先这样试）
python convert.py test.pdf --start-page 20 --max-pages 5

# 指定输出文件名（仍写入 output/）
python convert.py test.pdf -o notes.txt --dpi 200

# 已有 txt 只想合并换行、不想重新 OCR
python convert.py --reflow output/test.txt
```

### 常用参数

| 参数 | 说明 |
|------|------|
| `pdf` | 文件名（在 `input/` 查找）或完整路径 |
| `-o` / `--output` | 输出路径，默认 `output/<同名>.txt` |
| `--dpi` | 渲染分辨率，默认 `200`（更高更清晰也更慢） |
| `--start-page` | 从第 N 页开始（从 1 计） |
| `--max-pages` | 最多转换 N 页 |
| `--reflow` | 对已有 `.txt` 做段落合并，不重新 OCR |

## 输出说明

- 编码：UTF-8
- 每页以 `===== 第 N 页 =====` 分隔
- 正文会尽量合并为连续段落，复制到笔记里一般不必再手动「删回车」
- 章节名、短标题、页眉类短行会保留换行

OCR 并非 100% 准确（形近字、竖排/复杂版式、低清扫描都可能出错），请以原文核对重要摘录。

## 说明

- `input/` 里的 PDF、`output/` 里的生成结果默认不纳入 Git（见 `.gitignore`），避免把大文件推进仓库。
- 封面、竖排、复杂版式页的识别顺序可能仍不理想；正文页一般明显好于封面。

## 许可

个人学习使用。若公开分发，请自行确认所转换 PDF 的版权与使用范围。
