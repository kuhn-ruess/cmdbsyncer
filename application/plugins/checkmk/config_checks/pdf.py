"""
PDF export of configuration check reports, in the syncer design: a header
band in the navbar color of the installation with the white logo, then per
check the numbers it looked at, a summary of the findings per topic and one
section per topic with its own table, the same structure as the web page.

Built with fpdf2 (pure Python), an optional package from the ``extras``
(``pip install cmdbsyncer[extras]``). Only the export imports this module,
so the page and the checks work without fpdf2; :func:`pdf_available` tells
the page whether to offer the export. The built-in Helvetica only knows
Latin-1, so text is mapped to it; Checkmk output is plain ASCII in practice.
"""
from datetime import datetime

from fpdf import FPDF
from fpdf.fonts import FontFace

from .base import SEVERITY_WARNING

DEFAULT_BRAND = (44, 62, 80)
TEXT = (44, 62, 80)
MUTED = (108, 117, 125)
HEADING_FILL = (245, 247, 250)
SEVERITY_FILL = {SEVERITY_WARNING: (255, 193, 7)}
INFO_FILL = (23, 162, 184)
OK_FILL = (40, 167, 69)
STATE_FILL = {'WARN': (255, 193, 7), 'CRIT': (220, 53, 69),
              'UNKNOWN': (253, 126, 20)}
# Relative column widths by column kind.
KIND_WIDTH = {'items': 3.2, 'text': 2.2, 'code': 2.0, 'state': 0.9}
_REPLACE = {
    '…': '...', '‘': "'", '’': "'", '“': '"',
    '”': '"', '–': '-', '—': '-', ' ': ' ',
    '→': '->', '·': '-',
}


def latin1(text):
    """``text`` as a string the built-in PDF fonts can print."""
    text = str('' if text is None else text)
    for char, replacement in _REPLACE.items():
        text = text.replace(char, replacement)
    return text.encode('latin-1', 'replace').decode('latin-1')


def parse_color(value, default=DEFAULT_BRAND):
    """``#rgb`` or ``#rrggbb`` as an RGB tuple, ``default`` otherwise."""
    value = (value or '').strip().lstrip('#')
    if len(value) == 3:
        value = ''.join(char * 2 for char in value)
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)) \
            if len(value) == 6 else default
    except ValueError:
        return default


def items_text(items, scope_folder=None):
    """A list of rule items as lines of text (see ``Finding``)."""
    lines = []
    for item in items or []:
        head = ' '.join(part for part in (item.get('service'), item.get('rule'))
                        if part)
        detail = item.get('detail', '')
        if item.get('folder') and item.get('folder') != scope_folder:
            detail += f", folder {item['folder']}"
        if item.get('rule_id'):
            detail += f", rule {item['rule_id']}"
        lines.append(f"{head}: {detail}" if head else detail)
    return '\n'.join(lines)


def cell_text(column, finding):
    """The printable text of one column of a finding."""
    value = finding.values.get(column.key)
    if column.kind == 'items':
        return items_text(value, finding.values.get('folder'))
    return '' if value is None else str(value)


class ReportPDF(FPDF):
    """A4 landscape page with the syncer header band and a page footer."""

    def __init__(self, title, subtitle, brand, logo_path=None):
        super().__init__(orientation='L', unit='mm', format='A4')
        self.report_title = title
        self.report_subtitle = subtitle
        self.brand = brand
        self.logo_path = logo_path
        self.set_margins(12, 12, 12)
        self.set_auto_page_break(True, margin=14)

    def header(self):
        self.set_fill_color(*self.brand)
        self.rect(0, 0, self.w, 24, style='F')
        text_x = 12
        if self.logo_path:
            try:
                self.image(self.logo_path, x=12, y=3.5, h=17)
                text_x = 40
            except (OSError, RuntimeError, ValueError):
                text_x = 12
        self.set_text_color(255, 255, 255)
        self.set_xy(text_x, 5)
        self.set_font('Helvetica', 'B', 15)
        self.cell(0, 8, latin1(self.report_title))
        self.set_xy(text_x, 13)
        self.set_font('Helvetica', '', 9)
        self.cell(0, 6, latin1(self.report_subtitle))
        self.set_text_color(*TEXT)
        self.set_y(30)

    def footer(self):
        self.set_y(-10)
        self.set_font('Helvetica', '', 7)
        self.set_text_color(*MUTED)
        self.cell(0, 5, 'Created by CMDBsyncer. The checks only read the '
                        'Checkmk configuration.')
        self.cell(0, 5, f'Page {self.page_no()}/{{nb}}', align='R')
        self.set_text_color(*TEXT)


def _badge_fill(topic, count):
    if not count:
        return OK_FILL
    return SEVERITY_FILL.get(topic.severity, INFO_FILL)


def _paragraph(pdf, text, size=9, style='', color=TEXT):
    pdf.set_font('Helvetica', style, size)
    pdf.set_text_color(*color)
    pdf.multi_cell(0, 4.6, latin1(text), new_x='LMARGIN', new_y='NEXT')
    pdf.set_text_color(*TEXT)


def _summary(pdf, report):
    pdf.set_font('Helvetica', '', 9)
    with pdf.table(col_widths=(80, 20), width=100, align='LEFT',
                   line_height=5.5, borders_layout='HORIZONTAL_LINES',
                   headings_style=FontFace(emphasis='BOLD',
                                           fill_color=HEADING_FILL)) as table:
        row = table.row()
        row.cell('Topic')
        row.cell('Findings', align='RIGHT')
        for section in report['sections']:
            count = len(section['findings'])
            row = table.row()
            row.cell(latin1(section['topic'].title))
            row.cell(str(count), align='RIGHT', style=FontFace(
                emphasis='BOLD', fill_color=_badge_fill(section['topic'], count),
                color=(255, 255, 255) if not count else TEXT))
        row = table.row()
        row.cell('Total', style=FontFace(emphasis='BOLD'))
        row.cell(str(report['total']), align='RIGHT',
                 style=FontFace(emphasis='BOLD'))
    pdf.ln(3)


def _section(pdf, section):
    topic = section['topic']
    findings = section['findings']
    if pdf.will_page_break(30):
        pdf.add_page()
    pdf.set_font('Helvetica', 'B', 11)
    pdf.set_draw_color(200, 206, 214)
    pdf.cell(0, 7, latin1(f"{topic.title}  ({len(findings)})"), border='B',
             new_x='LMARGIN', new_y='NEXT')
    pdf.ln(1)
    if not findings:
        _paragraph(pdf, 'No findings.', color=MUTED)
        pdf.ln(2)
        return
    _paragraph(pdf, topic.description)
    _paragraph(pdf, f"What to do: {topic.action}", style='B')
    pdf.ln(1)
    widths = (0.5,) + tuple(KIND_WIDTH.get(c.kind, 2) for c in topic.columns)
    pdf.set_font('Helvetica', '', 8)
    with pdf.table(col_widths=widths, line_height=4.2, text_align='LEFT',
                   borders_layout='HORIZONTAL_LINES', repeat_headings=1,
                   headings_style=FontFace(emphasis='BOLD',
                                           fill_color=HEADING_FILL)) as table:
        row = table.row()
        row.cell('#')
        for column in topic.columns:
            row.cell(latin1(column.label))
        for index, finding in enumerate(findings, 1):
            row = table.row()
            row.cell(str(index))
            for column in topic.columns:
                text = latin1(cell_text(column, finding))
                style = None
                if column.kind == 'state':
                    style = FontFace(
                        emphasis='BOLD', fill_color=STATE_FILL.get(text),
                        color=(255, 255, 255) if text == 'CRIT' else TEXT)
                elif column.kind == 'code':
                    style = FontFace(family='Courier')
                row.cell(text, style=style)
    pdf.ln(3)


def render_pdf(reports, account, brand_color=None, logo_path=None,
               created=None):
    """The reports of one run as PDF bytes."""
    created = created or datetime.now()
    pdf = ReportPDF('Checkmk Configuration Checks',
                    f"Account {account}  |  {created:%Y-%m-%d %H:%M}",
                    parse_color(brand_color), logo_path)
    pdf.set_title(latin1(f'Checkmk Configuration Checks {account}'))
    pdf.set_creator('CMDBsyncer')
    pdf.add_page()
    for number, report in enumerate(reports):
        if number:
            pdf.add_page()
        pdf.set_font('Helvetica', 'B', 13)
        pdf.cell(0, 8, latin1(report['title']), new_x='LMARGIN', new_y='NEXT')
        _paragraph(pdf, report['description'], color=MUTED)
        _paragraph(pdf, '   '.join(f"{label}: {value}"
                                   for label, value in report['stats']),
                   size=8, color=MUTED)
        pdf.ln(2)
        _summary(pdf, report)
        for section in report['sections']:
            _section(pdf, section)
    return bytes(pdf.output())


def pdf_filename(account, created=None):
    """``checkmk-config-checks-<account>-<date>.pdf``, safe for a download."""
    # pylint: disable=import-outside-toplevel
    from werkzeug.utils import secure_filename
    created = created or datetime.now()
    name = f"checkmk-config-checks-{account}-{created:%Y-%m-%d}.pdf"
    return secure_filename(name) or f"checkmk-config-checks-{created:%Y-%m-%d}.pdf"
