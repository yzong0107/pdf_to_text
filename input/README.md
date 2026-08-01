# input/

把待转换的 PDF 直接放进这个文件夹，然后在项目根目录运行：

```powershell
python convert.py
```

会自动转换本目录下**全部** `.pdf`，结果写入 `output/`（与 PDF 同名的 `.txt`）。

可选：只转指定文件（一个或多个）：

```powershell
python convert.py book1.pdf book2.pdf
```
