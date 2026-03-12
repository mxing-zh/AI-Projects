from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
from typing import Iterable, List


SUPPORTED_IMAGE_FORMATS = {"png", "jpg", "jpeg"}


@dataclass
class ConvertConfig:
    input_root: Path
    output_root: Path
    image_format: str = "png"
    dpi: int = 300
    mirror_structure: bool = True
    single_output_dir: Path | None = None
    oda_converter: Path | None = None

    def normalized_format(self) -> str:
        fmt = self.image_format.lower().strip(".")
        if fmt == "jpeg":
            fmt = "jpg"
        if fmt not in SUPPORTED_IMAGE_FORMATS:
            raise ValueError(f"Unsupported image format: {self.image_format}")
        return fmt


def discover_dwgs(input_root: Path) -> List[Path]:
    return sorted(p for p in input_root.rglob("*.dwg") if p.is_file())


def resolve_output_path(dwg_file: Path, config: ConvertConfig) -> Path:
    fmt = config.normalized_format()
    if config.single_output_dir:
        config.single_output_dir.mkdir(parents=True, exist_ok=True)
        return config.single_output_dir / f"{dwg_file.stem}.{fmt}"

    rel = dwg_file.relative_to(config.input_root)
    destination = config.output_root / rel
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination.with_suffix(f".{fmt}")


def _run_oda_converter(input_root: Path, dxf_root: Path, oda_converter: Path) -> None:
    if not oda_converter.exists():
        raise FileNotFoundError(f"ODA converter not found: {oda_converter}")

    cmd = [
        str(oda_converter),
        str(input_root),
        str(dxf_root),
        "ACAD2018",
        "DXF",
        "1",
        "1",
        "*.dwg",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "ODA conversion failed.\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout: {proc.stdout}\n"
            f"stderr: {proc.stderr}"
        )


def _render_dxf_to_image(dxf_file: Path, image_file: Path, dpi: int) -> None:
    import matplotlib.pyplot as plt
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    doc = ezdxf.readfile(dxf_file)
    msp = doc.modelspace()

    fig = plt.figure(figsize=(12, 8), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_aspect("equal")
    ax.axis("off")

    ctx = RenderContext(doc)
    out = MatplotlibBackend(ax)
    Frontend(ctx, out).draw_layout(msp, finalize=True)
    fig.savefig(image_file, dpi=dpi, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def batch_convert(config: ConvertConfig) -> Iterable[str]:
    input_root = config.input_root.resolve()
    if not input_root.exists():
        raise FileNotFoundError(f"Input directory not found: {input_root}")

    dwg_files = discover_dwgs(input_root)
    if not dwg_files:
        yield "未找到 DWG 文件。"
        return

    yield f"共找到 {len(dwg_files)} 个 DWG 文件。"

    converter_path = config.oda_converter
    if converter_path is None:
        raise ValueError("必须提供 ODA File Converter 可执行文件路径。")

    with tempfile.TemporaryDirectory(prefix="dwg2img_dxf_") as tmp:
        dxf_root = Path(tmp)
        yield "开始将 DWG 批量转换为 DXF..."
        _run_oda_converter(input_root, dxf_root, converter_path)
        yield "DWG -> DXF 完成，开始渲染图片..."

        converted = 0
        for index, dwg_file in enumerate(dwg_files, 1):
            rel = dwg_file.relative_to(input_root)
            dxf_file = (dxf_root / rel).with_suffix(".dxf")
            if not dxf_file.exists():
                yield f"[{index}/{len(dwg_files)}] 跳过（未找到DXF）: {rel}"
                continue

            output_file = resolve_output_path(dwg_file, config)
            _render_dxf_to_image(dxf_file, output_file, config.dpi)
            converted += 1
            yield f"[{index}/{len(dwg_files)}] 完成: {rel} -> {output_file}"

    yield f"完成，成功输出 {converted}/{len(dwg_files)} 张图片。"
