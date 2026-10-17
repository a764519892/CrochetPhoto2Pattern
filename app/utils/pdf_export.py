"""PDF 说明书导出（S4，roadmap 第 2 项）——reportlab 生成可打印图解。

reportlab 是可选依赖（pip install crochet-photo2pattern[pdf]）；
中文用 Adobe CID 字体 STSong-Light（无需携带字体文件）。
布局：封面（我的照片 + 成品渲染图）→ 分解图 → 材料 → 逐部件圈数表
（每件带一行"节奏"）→ 钩针详细教程 → 装配说明。

图与文字同一次生成、同源：渲染图/分解图来自 :mod:`app.utils.preview_export`
（结果页同一个渲染器），照片是输入原图。任何一张图取不到时只是少一张图，
文字图解照旧完整——图是辅助，不是图解本体。
"""
from __future__ import annotations

import base64
import html
import io
import re
from pathlib import Path
from typing import Any

from app import PRODUCT_NAME, theme
from app.schemas import difficulty_label

# app.ui.preview3d 静态预览的画幅比（宽 / 高），用来按宽度定高。
_PREVIEW_ASPECT = 460 / 420

# 钩针详细教程：通用工艺基础（读懂上面的记号用），不是本工具对成品可钩性的
# 验证——工具只保证同一份数据能导出这一份图解。
_TUTORIAL: tuple[tuple[str, str], ...] = (
    ("一、工具与材料",
     "钩针号数按线标推荐、且全程同一号数（换号会改变密度，尺寸就不对了）。"
     "另备：记号扣、填充棉、缝合针、剪刀。做表情还要黑色圆眼扣（约 10mm，"
     "配垫片）或黑色绣线，以及粉色绣线/腮红。"),
    ("二、起针：魔法环（环形起针）",
     "线在手指上绕两圈，钩针穿入环内钩 6 个短针，最后抽紧线尾把中心收拢。"
     "Amigurumi 最常用，中心不留洞。本图解所有部件都从魔法环 6 针起头。"),
    ("三、短针 X",
     "钩针穿入下一针的两条半针，带线拉出，再带线一次穿过钩针上的两个环。"
     "圈数表里的 X 就是一针短针，“36X”即这一圈钩 36 个短针、不加不减。"),
    ("四、加针 V",
     "在同一针里钩两个短针，这一处就多 1 针。括号后的“×6”表示整圈重复 6 次："
     "“(4X,V)×6”= 4 短针 + 1 加针，重复 6 遍，一圈共多 6 针。本图解的加针步长"
     "固定为每圈 ±6 针（六等分），所以每圈加 6 针。"),
    ("五、减针 A 与隐形减针",
     "钩针穿入下一针的前半针，再穿入再下一针的前半针，带线一次穿过这两个前半针，"
     "再带线收掉——这就是隐形减针（A），接缝处不会鼓包。本图解减针同样按 6 针步长"
     "收，一圈减 6 针。"),
    ("六、螺旋钩（本图解的方式）",
     "不引拔、不翻转，一圈接一圈往上螺旋钩。每圈第一针挂记号扣，否则数不清圈。"
     "螺旋钩没有接缝，但圈与圈的加针位置会有轻微阶梯错位，这是正常的——"
     "所以每圈的加针位置都与上一圈错开半组。"),
    ("七、换线",
     "在上一针的最后一步（钩针上还有两个环时）用新线收尾，换线点最平整。"
     "“节奏”里标了第几圈换线、从什么色换到什么色；单色作品可忽略。"),
    ("八、怎么读圈数表",
     "“圈”是第几圈；“针数”是这一圈钩完后的总针数；“加/减”是这一圈每处加/减的"
     "针数；“配色”是这一圈用的线色；“说明”是具体针法。钩的过程中随时可以停下"
     "来核对：当前圈总针数对不对，比形状更像不像。"),
    ("九、塞棉",
     "边钩边塞：塞到“捏得动、按下去不回弹、也不变形”为止。头/身要塞实，"
     "耳朵、手臂、腿这类细长部件少塞或不塞，否则会顶破针目。收口前把口部再补一点。"),
    ("十、收口与藏线",
     "针数收到 6 针时，剪线留 10–15cm，用缝合针依次穿过末圈每个针目的前半针，"
     "一抽就把口收拢（无痕收口）。线尾穿入体内来回两次再剪断，别打结在外表面。"),
    ("十一、缝合装配",
     "用留长的线尾 + 缝合针，按“装配说明”的顺序缝；定位可先用珠针固定。"
     "针目对针目、隐形缝合（在针目之间穿行）最不露痕。头颈接合处要塞紧实，"
     "否则头会前倾。"),
    ("十二、表情与装饰（图解本体不含，可选）",
     "眼睛、鼻子、腮红属于装饰，图解只算钩织结构。做法：黑色圆眼扣从内侧加垫片"
     "固定（位置对照你自己的照片目测）；鼻子用粉色绣线绕几圈缝成小三角；"
     "腮红用腮红粉或粉色线轻轻晕一层。给 3 岁以下儿童或宠物玩的玩偶请一律改用"
     "刺绣眼——眼件脱落有误吞风险。"),
    ("十三、常见问题",
     "成品偏大/偏小：多半是密度不同，先量小样再改密度重新生成。"
     "每圈多出/少了针：从上圈的记号扣数起，逐段核对“加/减”列。"
     "针目出现小洞：填充塞太多或钩针号偏大。"),
    ("十四、关于这份图解",
     "以上针法说明是通用钩针基础，用来读懂本图解的记号；它是工艺常识，"
     "不是本工具对这件成品可钩性的验证。毛线用量、工时、尺寸都是按密度算出的"
     "估算值，请以自己试钩的小样为准。"),
)

_INVISIBLE_RE = re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def _escape_text(value: Any) -> str:
    """用户/模型提供的文本进 Paragraph 前必须转义——reportlab 会把
    <b>/<script> 等当作行内标记解析（U1 注塑面）；零宽/BiDi 控制符
    一并剥离（E1 显示欺骗面）。"""
    return html.escape(_INVISIBLE_RE.sub("", str(value)))


def export_pdf(params: dict[str, Any], analysis: dict[str, Any] | None = None,
               *, result: dict[str, Any] | None = None,
               photo: bytes | str | Path | None = None) -> bytes:
    """生成图解 PDF，返回字节流。reportlab 缺失时抛 ImportError。

    ``photo`` 是输入照片（字节或路径），排在封面渲染图旁边；不传时退回
    ``result["preview"]`` 内嵌的缩略图；都没有就不放照片（图解照旧完整）。
    """
    if result is not None:
        params, analysis = result["params"], result["analysis"]
    from app.models.validator import require_valid_pattern
    from app.utils.provenance import provenance_lines

    require_valid_pattern(params)
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

    esc = _escape_text
    body = ParagraphStyle("body", fontName="STSong-Light", fontSize=10.5,
                          leading=16)
    title = ParagraphStyle("title", parent=body, fontSize=18, leading=24,
                           spaceAfter=4)
    head = ParagraphStyle("head", parent=body, fontSize=13.5, leading=18,
                          spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("small", parent=body, fontSize=9, leading=13,
                           textColor=colors.HexColor("#666666"))
    cell = ParagraphStyle("cell", parent=body, fontSize=9.5, leading=13)
    cell_head = ParagraphStyle("cell_head", parent=cell, textColor=colors.white)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="Amigurumi 钩织图解",
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    story = []

    story.append(Paragraph("🧶 Amigurumi 钩针说明书", title))
    story.append(Paragraph(
        "图解 · 分解图 · 成品渲染图 · 钩针详细教程（同一份数据导出）", small))
    for note in provenance_lines(result):
        story.append(Paragraph(esc(note), small))
    if analysis:
        story.append(Paragraph(
            f"体型 {esc(analysis.get('body_type', '—'))} · "
            f"目标头径 {esc(analysis.get('head_diameter_cm', '—'))}cm · "
            f"目标高 {esc(analysis.get('height_cm', '—'))}cm · "
            f"难度 {esc(difficulty_label(str(analysis.get('difficulty', '—'))))}", small))
    # U24（升级）：密度随图解导出 + 兜底声明
    from app.models.gauge import gauge_from_mapping

    g = gauge_from_mapping(params.get("gauge"))
    st_g, rw_g = g.stitches_per_10cm, g.rows_per_10cm
    if params.get("gauge"):
        story.append(Paragraph(
            f"密度（小样）：10cm × {st_g:g} 针 × {rw_g:g} 行——请先试钩核对。"
            f"若你的小样密度不同，请改密度后重新生成", small))
    else:
        story.append(Paragraph(
            "密度（小样）：未记录（按经典图解默认 13 针 × 16 行 / 10cm）",
            small))
    from app.models.validator import shaping_policy_for_pattern
    shaping = shaping_policy_for_pattern(params)
    story.append(Paragraph(
        f"塑形：当前密度的连续几何变化率约 "
        f"{shaping['continuous_delta']:.2f} 针/圈，按六等分针法向上量化为每圈 "
        f"±{shaping['max_stitch_change']} 针；较平缓轮廓仍可使用 6 针步长",
        small))
    physical_parts = sum(
        max(1, int(part.get("quantity", 1)))
        for part in params.get("parts", []))
    minutes = max(0, int(params.get("estimated_time_minutes") or 0))
    story.append(Paragraph(
        f"工作量：{physical_parts} 个实体部件 · "
        f"{int(params.get('total_stitches') or 0):,} 针 · "
        f"基础操作估时 {minutes} 分钟（约 {minutes / 60:.1f} 小时）",
        small))
    story.append(Paragraph(
        "工时是未校准的低置信度经验值，只按针数与实体圈次计算；"
        "不含缝合、填充、换色、刺绣、返工和休息。",
        small))
    story.append(Paragraph(
        "记号：X=短针，V=加针，A=减针；(2X,V)×6 = “2 短针 + 1 加针”重复 6 次。"
        "螺旋钩（不引拔不翻转），每圈第一针挂记号扣；减针建议隐形减针。",
        small))
    story.append(Paragraph(
        "每个部件标题下的“节奏”一行，是把该部件的圈数表读成一句话（起头、加/减针"
        "区间、换线、收口），信息不超出下面的圈数表，不含额外工序。",
        small))
    story.append(Paragraph(
        "Stitch Key: X = sc (single crochet) · V = 2 sc in same st (increase) · "
        "A = sc2tog (invisible decrease) · SL = sl st · CH = ch。"
        "X/V/A 为日式 Amigurumi 惯例，与西方 CYC 图解体系对照如上。",
        small))
    story.append(Spacer(1, 6))

    # 封面图：我的照片 + 成品渲染图；分解图紧随其后。图与文字同源、同一次生成；
    # 任何一张取不到都只是少一张图，文字图解照旧完整。
    figure_result = result if result else {"params": params,
                                           "analysis": analysis or {}}
    figures = _figure_images(figure_result)
    assembled = figures["assembled"]
    photo_png = _photo_bytes(photo, result)
    cover: list[tuple[Any, str]] = []
    if photo_png:
        cover.append((_image_flowable(photo_png, 84 * mm),
                      "📷 我的照片（本机输入，只随这份 PDF）"))
    if assembled:
        cover.append((_image_flowable(assembled, 84 * mm),
                      "🖼 成品渲染图（按各部件真实圈数装配）"))
    if cover:
        if photo_png and assembled:
            heading = "🖼 照片与成品渲染图"
        elif photo_png:
            heading = "📷 我的照片"
        else:
            heading = "🖼 成品渲染图"
        story.append(Paragraph(heading, head))
        story.append(_cover_grid(cover, mm, small))
        if assembled:
            story.append(Paragraph(
                "装配示意：每个部件按<b>真实圈数</b>生成旋转体，再按与 CrochetPARADE "
                "装配块（--assemble）同一套解剖布局摆放；静态等距视图，非物理仿真，"
                "颜色只是最接近的色号。", small))
        if photo_png:
            story.append(Paragraph(
                "照片是你本机的输入原图，只随这份 PDF，不上传、不入库；"
                "要不要分享带照片的导出物由你决定。", small))
    if figures["parts"]:
        story.append(Paragraph("🧩 分解图", head))
        story.append(Paragraph(
            "各部件单独成图（与成品渲染图同一个渲染器和配色）——形状与配色示意，"
            "不代表成品比例；圈数、针数与尺寸见每张图的图注和下面的圈数表。", small))
        story.append(_part_grid(figures["parts"], mm, small))
    if not cover and not figures["parts"]:
        story.append(Paragraph(
            "（本次没有可渲染的部件，未附预览图；下方文字图解完整。）", small))
    story.append(Spacer(1, 4))

    # 材料
    story.append(Paragraph("🧵 所需材料", head))
    story.append(Paragraph("克重/米数为估算值（请以实际线标为准）", small))
    from app.models.materials import material_summary_text
    summary_text = material_summary_text(params)
    if summary_text:
        story.append(Paragraph(esc(summary_text), small))
    mat_rows = [[Paragraph("材料", cell_head), Paragraph("用量", cell_head)]]
    for mat in params.get("materials", []):
        if isinstance(mat, dict):
            mat_rows.append([Paragraph(esc(mat.get("item", "?")), cell),
                             Paragraph(esc(mat.get("quantity", "?")), cell)])
        else:
            mat_rows.append([Paragraph(esc(mat), cell), Paragraph("", cell)])
    mat_table = Table(mat_rows, colWidths=[70 * mm, 90 * mm])
    mat_table.setStyle(TableStyle([
        # 图解纸令牌：藏青表头 + 冷白斑马纹（与界面主题同源，见 app/theme.py）
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(theme.INK)),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(theme.RULE)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor(theme.PAPER)]),
    ]))
    story.append(mat_table)

    # 逐部件
    for part in params.get("parts", []):
        pd = part
        rounds = pd.get("rounds", [])
        quantity = max(1, int(pd.get("quantity", 1)))
        qty_label = f" × {quantity} 个" if quantity > 1 else ""
        story.append(Paragraph(
            f"🧶 {esc(pd.get('name', '?'))}{qty_label}"
            f"（{len(rounds)} 圈/个 · {esc(pd.get('type', '—'))}）",
            head))
        dims = []
        if pd.get("diameter_cm"):
            dims.append(f"直径 {esc(pd['diameter_cm'])}cm")
        if pd.get("height_cm"):
            dims.append(f"高 {esc(pd['height_cm'])}cm")
        if dims:
            story.append(Paragraph(" · ".join(dims), small))
        rhythm = part_rhythm_text(pd)
        if rhythm:
            story.append(Paragraph(f"节奏：{esc(rhythm)}", small))
        if pd.get("notes"):
            story.append(Paragraph(esc(pd["notes"]), small))
        if rounds:
            head_cells = [Paragraph(h, cell_head) for h in
                          ("圈", "针数", "加/减", "配色", "说明")]
            rows = [head_cells]
            for r in rounds:
                rd = r
                inc = f"+{rd['increase']}" if rd.get("increase") else (
                    f"-{rd['decrease']}" if rd.get("decrease") else "—")
                rows.append([
                    Paragraph(esc(rd.get("row", "")), cell),
                    Paragraph(esc(rd.get("stitches", "")), cell),
                    Paragraph(esc(inc), cell),
                    Paragraph(esc(rd.get("color") or "—"), cell),
                    Paragraph(esc(rd.get("notes") or ""), cell),
                ])
            rt = Table(rows, colWidths=[10 * mm, 14 * mm, 14 * mm, 22 * mm,
                                        116 * mm], repeatRows=1)
            rt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(theme.INK)),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(theme.RULE)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, colors.HexColor(theme.PAPER)]),
            ]))
            story.append(rt)

    # 钩针详细教程（通用基础；不含外链，离线也能读）
    story.append(Paragraph("🪡 钩针详细教程", head))
    story.append(Paragraph(
        "下面是通用钩针基础，用来读懂上面的记号；它是工艺常识，"
        "不构成本工具对这件成品可钩性的验证。", small))
    for tip_title, tip_body in _TUTORIAL:
        story.append(Paragraph(tip_title, cell))
        story.append(Paragraph(tip_body, small))

    # 装配
    assembly = params.get("assembly_instructions") or ""
    if assembly:
        story.append(Paragraph("🔧 装配说明", head))
        for step in str(assembly).split("\n"):
            if step.strip():
                story.append(Paragraph(esc(step), body))

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        f"由 {PRODUCT_NAME} 生成 — 比例可能需要试钩调整", small))
    doc.build(story)
    return buf.getvalue()


# ── 图与"节奏"：供 export_pdf 使用 ───────────────────────────────────────


def part_rhythm_text(part: dict[str, Any]) -> str:
    """把一件的圈数表读成一句话：起头 → 加/减针区间 → 换线 → 收口。

    例：``从 6 针起头；第 2–6 圈每圈加 6 针（6→36）；第 7–12 圈不加不减
    36 针；第 13–17 圈每圈减 6 针（36→6）；收口。``

    只归纳圈数表里已有的数字，不添加表里没有的工序或塑形建议；表为空或
    全是非法值时返回空串。
    """
    entries: list[dict[str, Any]] = []
    for index, raw in enumerate(part.get("rounds") or [], start=1):
        row = raw if isinstance(raw, dict) else (
            raw.model_dump() if hasattr(raw, "model_dump") else {})
        stitches = _int_or_none(row.get("stitches"))
        if stitches is None:
            continue
        entries.append({
            "row": index,
            "stitches": stitches,
            "inc": _int_or_none(row.get("increase")) or 0,
            "dec": _int_or_none(row.get("decrease")) or 0,
            "color": str(row.get("color") or "").strip(),
        })
    if not entries:
        return ""

    steps = [f"从 {entries[0]['stitches']} 针起头"]
    start = 1
    while start < len(entries):
        end = start
        while (end + 1 < len(entries)
               and _same_phase(entries[end], entries[end + 1])):
            end += 1
        steps.append(_phase_text(entries[start], entries[end],
                                 entries[start - 1]["stitches"]))
        start = end + 1
    changes = _color_changes(entries)
    if changes:
        steps.append("；".join(changes))
    last = entries[-1]
    if last["dec"] and last["stitches"] <= 6:
        steps.append("收口")
    return "；".join(steps) + "。"


def _same_phase(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """相邻两圈是否属于同一"节奏段"（同样加/减，或不加不减同针数）。"""
    if first["inc"] or first["dec"]:
        return second["inc"] == first["inc"] and second["dec"] == first["dec"]
    return (not second["inc"] and not second["dec"]
            and second["stitches"] == first["stitches"])


def _phase_text(first: dict[str, Any], last: dict[str, Any], before: int) -> str:
    if first["row"] == last["row"]:
        span = f"第 {first['row']} 圈"
        each = ""
    else:
        span = f"第 {first['row']}–{last['row']} 圈"
        each = "每圈"
    if first["inc"]:
        return f"{span}{each}加 {first['inc']} 针（{before}→{last['stitches']}）"
    if first["dec"]:
        return f"{span}{each}减 {first['dec']} 针（{before}→{last['stitches']}）"
    return f"{span}不加不减 {first['stitches']} 针"


def _color_changes(entries: list[dict[str, Any]]) -> list[str]:
    changes: list[str] = []
    current = entries[0]["color"]
    for entry in entries[1:]:
        if entry["color"] and entry["color"] != current:
            changes.append(
                f"第 {entry['row']} 圈换线：{current or '—'} → {entry['color']}")
            current = entry["color"]
    return changes


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _photo_bytes(photo: Any, result: dict[str, Any] | None) -> bytes | None:
    """输入照片字节：显式传入的优先（bytes 或路径），其次 result 内嵌缩略图。"""
    if photo is not None:
        try:
            if isinstance(photo, (bytes, bytearray)):
                return _shrink_photo(bytes(photo))
            return _shrink_photo(Path(photo).read_bytes())
        except OSError:
            pass
    preview = (result or {}).get("preview")
    if isinstance(preview, str) and ";base64," in preview:
        try:
            return _shrink_photo(base64.b64decode(preview.split(";base64,", 1)[1]))
        except (ValueError, TypeError):
            return None
    return None


def _shrink_photo(data: bytes, *, max_side: int = 1600) -> bytes:
    """照片重编码成 JPEG（只为排版）：超大图缩到 1600px 内、透明区域压白底。

    排版用不着原始像素，但几 MB 的原图会把 PDF 撑到同样大；认不出来的格式
    原样返回，交给 reportlab 自己试。
    """
    from PIL import Image as PILImage

    try:
        with PILImage.open(io.BytesIO(data)) as source:
            source.load()
            if source.mode in ("RGBA", "LA", "P"):
                rgba = source.convert("RGBA")
                canvas = PILImage.new("RGB", rgba.size, (255, 255, 255))
                canvas.paste(rgba, mask=rgba.split()[-1])
                image = canvas
            else:
                image = source.convert("RGB")
            if max(image.size) > max_side:
                image.thumbnail((max_side, max_side), PILImage.Resampling.LANCZOS)
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=88, optimize=True)
        return out.getvalue()
    except Exception:
        return data


def _figure_images(figure_result: dict[str, Any]) -> dict[str, Any]:
    """成品渲染图 + 逐件分解图（PNG 字节）。任何一步失败只是少一张图。"""
    from app.utils.preview_export import part_previews, preview_svg, rasterise_preview_svg

    figures: dict[str, Any] = {"assembled": None, "parts": []}
    try:
        figures["assembled"] = rasterise_preview_svg(preview_svg(figure_result))
    except Exception:  # 没有可渲染部件/栅格化失败 → 不放这张图
        figures["assembled"] = None
    try:
        previews = part_previews(figure_result)
    except Exception:
        previews = []
    for preview in previews:
        try:
            preview["png"] = rasterise_preview_svg(preview["svg"])
        except Exception:
            continue
        figures["parts"].append(preview)
    return figures


def _image_flowable(data: bytes, width: float) -> Any:
    """位图 → reportlab 图片（按原始宽高比缩放，居中）。"""
    from PIL import Image as PILImage
    from reportlab.platypus import Image as RLImage

    try:
        with PILImage.open(io.BytesIO(data)) as im:
            pixel_w, pixel_h = im.size
    except Exception:
        pixel_w, pixel_h = 0, 0
    height = width * (pixel_h / pixel_w) if pixel_w else width
    flow = RLImage(io.BytesIO(data), width=width, height=height)
    flow.hAlign = "CENTER"
    return flow


def _cover_grid(cells: list[tuple[Any, str]], mm: Any,
                caption_style: Any) -> Any:
    """封面：图一行、图注一行；只有一张时整幅居中。"""
    from reportlab.platypus import Paragraph, Table, TableStyle

    images = [cell[0] for cell in cells]
    captions = [Paragraph(cell[1], caption_style) for cell in cells]
    if len(cells) == 1:
        col_widths = [178 * mm]
    else:
        col_widths = [89 * mm, 89 * mm]
        images = images[:2]
        captions = captions[:2]
    grid = Table([images, captions], colWidths=col_widths)
    grid.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, 0), "BOTTOM"),
        ("VALIGN", (0, 1), (-1, 1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return grid


def _part_grid(parts: list[dict[str, Any]], mm: Any, caption_style: Any) -> Any:
    """分解图：每行两件，图 + 图注交替成行。"""
    from reportlab.platypus import Paragraph, Table, TableStyle

    width = 86 * mm
    rows: list[list[Any]] = []
    for index in range(0, len(parts), 2):
        pair = parts[index:index + 2]
        images: list[Any] = [_image_flowable(p["png"], width) for p in pair]
        captions: list[Any] = [
            Paragraph(_part_caption(p), caption_style) for p in pair]
        if len(pair) == 1:
            images.append("")
            captions.append("")
        rows.append(images)
        rows.append(captions)
    grid = Table(rows, colWidths=[89 * mm, 89 * mm])
    grid.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return grid


def _part_caption(preview: dict[str, Any]) -> str:
    quantity = max(1, _int_or_none(preview.get("quantity")) or 1)
    qty = f" × {quantity}" if quantity > 1 else ""
    bits = [f"{preview.get('rounds')} 圈"]
    if preview.get("max_stitches"):
        bits.append(f"最大 {preview['max_stitches']} 针")
    if preview.get("diameter_cm"):
        bits.append(f"直径约 {preview['diameter_cm']}cm")
    if preview.get("height_cm"):
        bits.append(f"高约 {preview['height_cm']}cm")
    name = _escape_text(preview.get("name") or "")
    return f"<b>{name}</b>{qty}<br/>{' · '.join(bits)}"
