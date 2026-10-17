"""PDF 说明书（``--pdf``）：我的照片 / 成品渲染图 / 分解图 / 节奏 / 钩针教程。

约定：图与文字同一次生成、同源；任何一张图取不到都只是少一张图，文字图解
（圈数表）照旧完整。
"""
import base64
import io

import pytest
from PIL import Image, ImageDraw

from app.models.crochet_params import CrochetParamsGenerator
from app.models.gauge import PRESETS
from app.models.structure_designer import StructureDesigner
from app.schemas import ImageAnalysis

_PARTS = ["头部", "身体", "手臂", "腿部", "耳朵"]


def _params(parts=None):
    analysis = ImageAnalysis(body_type="标准", head_diameter_cm=9.0,
                             height_cm=18.0, main_features=[], pose="站立",
                             difficulty="easy", parts=list(parts or _PARTS))
    structure = StructureDesigner.design_3d_structure(analysis)
    return CrochetParamsGenerator.generate_params(
        analysis, structure, gauge=PRESETS["classic"])


def _result(preview=None):
    return {"params": _params(),
            "analysis": {"body_type": "标准", "head_diameter_cm": 9.0,
                         "height_cm": 18.0},
            "preview": preview}


def _photo_bytes(size=(900, 700), color=(255, 200, 200, 0)):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _images(pdf: bytes) -> int:
    return pdf.count(b"/Subtype /Image")


# ── 节奏：圈数表 → 一句话 ────────────────────────────────────────────────

def test_rhythm_reads_a_circle_into_one_sentence():
    from app.utils.pdf_export import part_rhythm_text

    part = {"rounds": [{"row": 1, "stitches": 6},
                       {"row": 2, "stitches": 12, "increase": 6},
                       {"row": 3, "stitches": 18, "increase": 6},
                       {"row": 4, "stitches": 18},
                       {"row": 5, "stitches": 12, "decrease": 6},
                       {"row": 6, "stitches": 6, "decrease": 6}]}
    assert part_rhythm_text(part) == (
        "从 6 针起头；第 2–3 圈每圈加 6 针（6→18）；第 4 圈不加不减 18 针；"
        "第 5–6 圈每圈减 6 针（18→6）；收口。")


def test_rhythm_reports_each_colour_change_once():
    from app.utils.pdf_export import part_rhythm_text

    part = {"rounds": [{"row": 1, "stitches": 6, "color": "白色"},
                       {"row": 2, "stitches": 12, "increase": 6,
                        "color": "白色"},
                       {"row": 3, "stitches": 12, "color": "粉红色"},
                       {"row": 4, "stitches": 12, "color": "粉红色"}]}
    text = part_rhythm_text(part)
    assert "第 3 圈换线：白色 → 粉红色" in text
    assert text.count("换线") == 1


def test_rhythm_is_empty_without_usable_rounds():
    from app.utils.pdf_export import part_rhythm_text

    assert part_rhythm_text({}) == ""
    assert part_rhythm_text({"rounds": []}) == ""
    assert part_rhythm_text({"rounds": [None, {"stitches": "x"}]}) == ""


def test_rhythm_accepts_string_numbers():
    from app.utils.pdf_export import part_rhythm_text

    part = {"rounds": [{"row": 1, "stitches": "6"},
                       {"row": 2, "stitches": "12", "increase": "6"}]}
    assert part_rhythm_text(part) == "从 6 针起头；第 2 圈加 6 针（6→12）。"


def test_rhythm_has_no_closing_step_without_a_decrease():
    from app.utils.pdf_export import part_rhythm_text

    part = {"rounds": [{"row": 1, "stitches": 6},
                       {"row": 2, "stitches": 12, "increase": 6},
                       {"row": 3, "stitches": 12}]}
    text = part_rhythm_text(part)
    assert "收口" not in text


# ── 分解图：逐件单独成帧 ────────────────────────────────────────────────

def test_part_previews_cover_every_part_once():
    from app.utils.preview_export import part_previews

    previews = part_previews(_result())
    assert [p["name"] for p in previews] == _PARTS
    assert [p["quantity"] for p in previews] == [1, 1, 2, 2, 2]
    for preview in previews:
        assert preview["rounds"] > 0
        assert preview["max_stitches"] > 0
        assert preview["diameter_cm"] > 0
        assert preview["height_cm"] > 0


def test_each_part_preview_is_smaller_than_the_assembled_one():
    from app.utils.preview_export import part_previews, preview_svg

    assembled = preview_svg(_result())
    for preview in part_previews(_result()):
        assert preview["svg"].count("<polygon") > 10
        assert preview["svg"].count("<polygon") < assembled.count("<polygon")


def test_backfaces_fill_the_open_end_of_a_single_part():
    """单件成帧正对收口锥：打开背面才不会漏出背景（见 preview_export）。"""
    from app.ui.preview3d import assembly_payload, render_payload_svg

    payload = assembly_payload(_result())
    item = payload["items"][0]
    single = {"height": payload["height"],
              "items": [{**item,
                         "instances": [{"p": [0.0, 0.0, 0.0],
                                        "r": [0.0, 0.0, 0.0]}]}]}
    culled = render_payload_svg(single)
    filled = render_payload_svg(
        {**single, "items": [{**item, "backfaces": True,
                              "instances": [{"p": [0.0, 0.0, 0.0],
                                             "r": [0.0, 0.0, 0.0]}]}]})
    assert filled.count("<polygon") > culled.count("<polygon")


# ── 照片：重编码只为排版，不改原文件 ─────────────────────────────────────

def test_photo_is_recoded_to_jpeg_and_capped():
    from app.utils.pdf_export import _shrink_photo

    raw = _photo_bytes(size=(2400, 1800))
    shrunk = _shrink_photo(raw)
    with Image.open(io.BytesIO(shrunk)) as image:
        assert image.format == "JPEG"
        assert max(image.size) <= 1600
        corner = image.convert("RGB").getpixel((0, 0))
    assert all(channel >= 250 for channel in corner)  # 透明区域压成白底
    assert len(shrunk) < len(raw)


def test_photo_recoding_keeps_unreadable_bytes_as_is():
    from app.utils.pdf_export import _shrink_photo

    assert _shrink_photo(b"not an image") == b"not an image"


# ── PDF 本体 ────────────────────────────────────────────────────────────

def test_manual_embeds_photo_renders_and_parts():
    pytest.importorskip("reportlab")
    from app.utils.pdf_export import export_pdf

    with_photo = export_pdf(_params(), result=_result(),
                            photo=_photo_bytes())
    without_photo = export_pdf(_params(), result=_result())
    assert with_photo.startswith(b"%PDF-")
    # 照片 + 成品渲染图 + 5 件分解图
    assert _images(with_photo) == _images(without_photo) + 1
    assert _images(with_photo) >= 3


def test_manual_falls_back_to_the_embedded_preview_thumbnail():
    pytest.importorskip("reportlab")
    from app.utils.pdf_export import export_pdf

    thumbnail = base64.b64encode(_photo_bytes((80, 80), (0, 0, 0, 255))).decode()
    with_thumb = export_pdf(
        _params(), result=_result(f"data:image/png;base64,{thumbnail}"))
    without = export_pdf(_params(), result=_result())
    assert _images(with_thumb) == _images(without) + 1


def test_manual_survives_a_photo_that_cannot_be_read(tmp_path):
    pytest.importorskip("reportlab")
    from app.utils.pdf_export import export_pdf

    data = export_pdf(_params(), result=_result(),
                      photo=tmp_path / "missing.png")
    assert data.startswith(b"%PDF-")
    assert _images(data) >= 1  # 图还是那几张，只是没有照片


def test_manual_without_a_result_stays_a_complete_pdf():
    pytest.importorskip("reportlab")
    from app.utils.pdf_export import export_pdf

    data = export_pdf(_params(), {"body_type": "标准"})
    assert data.startswith(b"%PDF-")
    assert b"/STSong-Light" in data or _images(data) >= 1


def test_manual_rejects_an_invalid_pattern():
    pytest.importorskip("reportlab")
    from app.utils.pdf_export import export_pdf

    with pytest.raises(ValueError, match="图解自检失败"):
        export_pdf({"parts": [{"name": "头部"}]})


# ── 教程 ────────────────────────────────────────────────────────────────

def test_tutorial_covers_the_basics_once():
    from app.utils.pdf_export import _TUTORIAL

    titles = [title for title, _body in _TUTORIAL]
    assert len(titles) == len(set(titles))
    joined = " ".join(titles)
    for keyword in ("工具", "起针", "短针", "加针", "减针", "螺旋钩", "换线",
                    "圈数表", "塞棉", "收口", "缝合", "装饰", "常见问题"):
        assert keyword in joined


def test_tutorial_keeps_the_honest_boundary_and_safety_notes():
    from app.utils.pdf_export import _TUTORIAL

    body = " ".join(text for _title, text in _TUTORIAL)
    assert "不是本工具" in body          # 通用工艺 ≠ 可钩性验证
    assert "刺绣眼" in body              # 眼件误吞：儿童/宠物改刺绣
    assert "估算值" in body


def test_tutorial_headings_avoid_glyphs_the_pdf_font_lacks():
    """STSong-Light（Adobe-GB1）没有 ⑪–⑳ 这类字形：标题里不能用它们。"""
    from app.utils.pdf_export import _TUTORIAL

    for title, _body in _TUTORIAL:
        assert not any("\u246a" <= ch <= "\u2473" for ch in title)


# ── CLI 接线 ────────────────────────────────────────────────────────────

def test_cli_pdf_manual_includes_the_input_photo(tmp_path):
    pytest.importorskip("reportlab")
    from app import cli

    photo = tmp_path / "doll.png"
    image = Image.new("RGB", (200, 400), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    draw.ellipse([75, 24, 125, 74], fill=(230, 180, 150))
    draw.rounded_rectangle([80, 85, 120, 195], radius=10, fill=(0, 120, 215))
    draw.rounded_rectangle([78, 195, 122, 372], radius=10, fill=(0, 120, 215))
    image.save(photo)
    pdf_path = tmp_path / "manual.pdf"
    assert cli.main(["--image", str(photo), "--local", "--height", "30",
                     "--gauge", "dk", "--out", str(tmp_path / "p.json"),
                     "--pdf", str(pdf_path), "--quiet"]) == 0
    data = pdf_path.read_bytes()
    assert data.startswith(b"%PDF-")
    assert _images(data) >= 3  # 照片 + 成品渲染图 + 分解图
