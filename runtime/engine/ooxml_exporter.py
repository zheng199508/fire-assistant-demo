"""Generate a polished DOCX report using only the Python standard library.

The browser runtime cannot depend on server-side ``python-docx``. This module
therefore emits a small, standards-compliant OOXML package directly. Its visual
system follows the ``standard_business_brief`` document preset with one named
override: the report title uses the product's deep teal at 26 pt.
"""

from __future__ import annotations

import base64
import io
import re
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CONTENT_WIDTH = 9360


def _xml(text: object) -> str:
    return escape(str(text), {'"': "&quot;"})


def _run(text: str, *, bold: bool = False, italic: bool = False, code: bool = False) -> str:
    if not text:
        return ""
    props = []
    if bold:
        props.append("<w:b/><w:bCs/>")
    if italic:
        props.append("<w:i/><w:iCs/>")
    if code:
        props.append(
            '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:eastAsia="Microsoft YaHei"/>'
            '<w:sz w:val="19"/><w:szCs w:val="19"/><w:color w:val="9B1C1C"/>'
            '<w:shd w:val="clear" w:color="auto" w:fill="F2F4F7"/>'
        )
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    preserve = ' xml:space="preserve"' if text[:1].isspace() or text[-1:].isspace() else ""
    return f"<w:r>{rpr}<w:t{preserve}>{_xml(text)}</w:t></w:r>"


INLINE_RE = re.compile(r"(\*\*(.+?)\*\*|`(.+?)`|(?<!\*)\*([^*]+?)\*(?!\*))")


def _inline(text: str) -> str:
    runs = []
    cursor = 0
    for match in INLINE_RE.finditer(text):
        if match.start() > cursor:
            runs.append(_run(text[cursor:match.start()]))
        if match.group(2) is not None:
            runs.append(_run(match.group(2), bold=True))
        elif match.group(3) is not None:
            runs.append(_run(match.group(3), code=True))
        else:
            runs.append(_run(match.group(4), italic=True))
        cursor = match.end()
    if cursor < len(text):
        runs.append(_run(text[cursor:]))
    return "".join(runs) or _run(text)


def _paragraph(
    text: str,
    *,
    style: str = "Normal",
    num_id: int | None = None,
    level: int = 0,
    keep_next: bool = False,
    callout: str = "",
) -> str:
    ppr = [f'<w:pStyle w:val="{style}"/>']
    if keep_next:
        ppr.append("<w:keepNext/>")
    if num_id is not None:
        ppr.append(
            f'<w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="{num_id}"/></w:numPr>'
        )
    if callout:
        fill = "FFF4E5" if callout == "warning" else "F4F6F9"
        border = "C47A16" if callout == "warning" else "2E74B5"
        ppr.append(
            '<w:pBdr><w:left w:val="single" w:sz="18" w:space="8" '
            f'w:color="{border}"/></w:pBdr>'
            f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>'
            '<w:ind w:left="180" w:right="120"/>'
            '<w:spacing w:before="100" w:after="100" w:line="276" w:lineRule="auto"/>'
        )
    return f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{_inline(text)}</w:p>"


def _column_widths(count: int) -> list[int]:
    presets = {
        1: [CONTENT_WIDTH],
        2: [2700, 6660],
        3: [1800, 3780, 3780],
        4: [1300, 2900, 2500, 2660],
        5: [1000, 2090, 2090, 2090, 2090],
    }
    if count in presets:
        return presets[count]
    base = CONTENT_WIDTH // count
    widths = [base] * count
    widths[-1] += CONTENT_WIDTH - sum(widths)
    return widths


def _table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    columns = max(len(row) for row in rows)
    widths = _column_widths(columns)
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)
    border_xml = "".join(
        f'<w:{edge} w:val="single" w:sz="4" w:space="0" w:color="D7DEE3"/>'
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV")
    )
    table_rows = []
    for row_index, raw_row in enumerate(rows):
        row = [*raw_row, *([""] * (columns - len(raw_row)))]
        trpr = "<w:trPr><w:tblHeader/></w:trPr>" if row_index == 0 else ""
        cells = []
        for column_index, value in enumerate(row):
            shade = '<w:shd w:val="clear" w:color="auto" w:fill="F2F4F7"/>' if row_index == 0 else ""
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", value)
            cells.append(
                "<w:tc><w:tcPr>"
                f'<w:tcW w:w="{widths[column_index]}" w:type="dxa"/>{shade}'
                '<w:vAlign w:val="center"/>'
                "</w:tcPr>"
                f'<w:p><w:pPr><w:pStyle w:val="TableText"/></w:pPr>'
                f'{_run(text, bold=row_index == 0)}</w:p></w:tc>'
            )
        table_rows.append(f"<w:tr>{trpr}{''.join(cells)}</w:tr>")
    return (
        "<w:tbl><w:tblPr>"
        f'<w:tblW w:w="{CONTENT_WIDTH}" w:type="dxa"/><w:tblInd w:w="120" w:type="dxa"/>'
        '<w:tblLayout w:type="fixed"/><w:tblBorders>'
        f"{border_xml}</w:tblBorders>"
        '<w:tblCellMar><w:top w:w="80" w:type="dxa"/><w:left w:w="120" w:type="dxa"/>'
        '<w:bottom w:w="80" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tblCellMar>'
        "</w:tblPr>"
        f"<w:tblGrid>{grid}</w:tblGrid>{''.join(table_rows)}</w:tbl>"
        '<w:p><w:pPr><w:spacing w:after="80"/></w:pPr></w:p>'
    )


def _parse_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _document_body(markdown: str) -> str:
    blocks: list[str] = []
    lines = markdown.replace("\r\n", "\n").split("\n")
    index = 0
    title_seen = False
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            rows = []
            while index < len(lines):
                current = lines[index].strip()
                if not (current.startswith("|") and current.endswith("|")):
                    break
                if not re.fullmatch(r"\|[\s:|\-]+\|", current):
                    rows.append(_parse_table_row(current))
                index += 1
            blocks.append(_table(rows))
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            text = heading.group(2)
            if level == 1 and not title_seen:
                blocks.append(_paragraph("消防方案助手 · 专业审核版", style="Kicker"))
                blocks.append(_paragraph(text, style="Title", keep_next=True))
                title_seen = True
            else:
                style = {1: "Heading1", 2: "Heading1", 3: "Heading2", 4: "Heading3"}[level]
                blocks.append(_paragraph(text, style=style, keep_next=True))
        elif stripped.startswith("> "):
            text = stripped[2:].strip()
            warning = any(mark in text for mark in ("⚠", "⛔", "警告", "审核中", "免责声明"))
            blocks.append(_paragraph(text, style="Quote", callout="warning" if warning else "note"))
        elif re.match(r"^\d+[.)]\s+", stripped):
            blocks.append(_paragraph(re.sub(r"^\d+[.)]\s+", "", stripped), num_id=2))
        elif stripped.startswith("- "):
            blocks.append(_paragraph(stripped[2:], num_id=1))
        elif stripped == "---":
            blocks.append('<w:p><w:pPr><w:spacing w:before="80" w:after="80"/></w:pPr></w:p>')
        elif stripped:
            blocks.append(_paragraph(stripped))
        index += 1
    return "".join(blocks)


def _styles_xml() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W_NS}">
  <w:docDefaults><w:rPrDefault><w:rPr>
    <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei" w:cs="Calibri"/>
    <w:sz w:val="22"/><w:szCs w:val="22"/><w:color w:val="14272A"/>
  </w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>
    <w:spacing w:after="120" w:line="264" w:lineRule="auto"/>
  </w:pPr></w:pPrDefault></w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/>
    <w:qFormat/><w:pPr><w:spacing w:after="120" w:line="264" w:lineRule="auto"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Kicker"><w:name w:val="Kicker"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:before="0" w:after="80"/><w:keepNext/></w:pPr>
    <w:rPr><w:b/><w:color w:val="C47A16"/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>
    <w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:before="0" w:after="260"/><w:keepNext/></w:pPr>
    <w:rPr><w:rFonts w:ascii="Calibri Light" w:hAnsi="Calibri Light" w:eastAsia="Microsoft YaHei"/>
      <w:b/><w:color w:val="122B2F"/><w:sz w:val="52"/><w:szCs w:val="52"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
    <w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="320" w:after="160"/><w:outlineLvl w:val="0"/></w:pPr>
    <w:rPr><w:b/><w:color w:val="2E74B5"/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
    <w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="1"/></w:pPr>
    <w:rPr><w:b/><w:color w:val="2E74B5"/><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/>
    <w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="160" w:after="80"/><w:outlineLvl w:val="2"/></w:pPr>
    <w:rPr><w:b/><w:color w:val="1F4D78"/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:before="100" w:after="100" w:line="276" w:lineRule="auto"/></w:pPr>
    <w:rPr><w:color w:val="536566"/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="TableText"><w:name w:val="Table Text"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:before="0" w:after="0" w:line="252" w:lineRule="auto"/></w:pPr>
    <w:rPr><w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr>
  </w:style>
</w:styles>'''


def _numbering_xml() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="{W_NS}">
  <w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/>
    <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/>
      <w:lvlJc w:val="left"/><w:pPr><w:tabs><w:tab w:val="num" w:pos="720"/></w:tabs><w:ind w:left="720" w:hanging="360"/><w:spacing w:after="160" w:line="280" w:lineRule="auto"/></w:pPr>
      <w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:hint="default"/></w:rPr>
    </w:lvl></w:abstractNum>
  <w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="singleLevel"/>
    <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/>
      <w:lvlJc w:val="left"/><w:pPr><w:tabs><w:tab w:val="num" w:pos="720"/></w:tabs><w:ind w:left="720" w:hanging="360"/><w:spacing w:after="160" w:line="280" w:lineRule="auto"/></w:pPr>
    </w:lvl></w:abstractNum>
  <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
  <w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>
</w:numbering>'''


def _document_xml(markdown: str) -> str:
    body = _document_body(markdown)
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}"><w:body>{body}
<w:sectPr>
  <w:headerReference w:type="default" r:id="rId3"/><w:footerReference w:type="default" r:id="rId4"/>
  <w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/>
  <w:cols w:space="720"/><w:docGrid w:linePitch="312"/>
</w:sectPr></w:body></w:document>'''


def _header_xml() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="{W_NS}"><w:p><w:pPr><w:spacing w:after="0"/></w:pPr>
<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei"/><w:color w:val="687779"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr><w:t>消防设施配置方案报告 · 专业审核版</w:t></w:r>
</w:p></w:hdr>'''


def _footer_xml() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="{W_NS}"><w:p><w:pPr><w:jc w:val="right"/><w:spacing w:before="0" w:after="0"/></w:pPr>
<w:r><w:rPr><w:color w:val="7B898A"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr><w:t>消防方案助手  |  第 </w:t></w:r>
<w:fldSimple w:instr="PAGE"><w:r><w:rPr><w:color w:val="7B898A"/><w:sz w:val="18"/></w:rPr><w:t>1</w:t></w:r></w:fldSimple>
<w:r><w:rPr><w:color w:val="7B898A"/><w:sz w:val="18"/></w:rPr><w:t> 页</w:t></w:r>
</w:p></w:ftr>'''


def build_docx(report_markdown: str) -> bytes:
    """Return a real ``.docx`` package for one Markdown report."""
    if not isinstance(report_markdown, str) or not report_markdown.strip():
        raise ValueError("report_markdown 不能为空")
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    parts = {
        "[Content_Types].xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>''',
        "_rels/.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>''',
        "word/document.xml": _document_xml(report_markdown),
        "word/styles.xml": _styles_xml(),
        "word/numbering.xml": _numbering_xml(),
        "word/settings.xml": f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="{W_NS}"><w:zoom w:percent="100"/><w:defaultTabStop w:val="720"/><w:updateFields w:val="true"/><w:compat/></w:settings>''',
        "word/_rels/document.xml.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>''',
        "word/header1.xml": _header_xml(),
        "word/footer1.xml": _footer_xml(),
        "docProps/core.xml": f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:title>消防设施配置方案报告</dc:title><dc:subject>专业审核版</dc:subject><dc:creator>消防方案助手</dc:creator><cp:lastModifiedBy>消防方案助手</cp:lastModifiedBy><dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified></cp:coreProperties>''',
        "docProps/app.xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>消防方案助手</Application><AppVersion>1.0</AppVersion></Properties>''',
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content.encode("utf-8"))
    return output.getvalue()


def build_docx_base64(report_markdown: str) -> str:
    """String bridge used by the Pyodide web worker."""
    return base64.b64encode(build_docx(report_markdown)).decode("ascii")

