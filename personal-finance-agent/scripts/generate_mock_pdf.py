"""
Generate a realistic Visa credit card statement PDF for March 2026.

Usage:
    python scripts/generate_mock_pdf.py
Output:
    data/mock/visa_statement_mar2026.pdf
"""

from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Colour palette (RBC-inspired blue/gold scheme)
# ---------------------------------------------------------------------------
NAVY      = colors.HexColor("#003189")   # deep navy — header background
GOLD      = colors.HexColor("#FFD700")   # gold accent
MID_BLUE  = colors.HexColor("#0055A4")   # section headings
LIGHT_BG  = colors.HexColor("#EEF3FB")   # alternating row / summary boxes
ROW_ALT   = colors.HexColor("#F4F7FC")   # alternate transaction row
RED       = colors.HexColor("#CC0000")   # amounts owed
DARK_TEXT = colors.HexColor("#1A1A1A")
MID_GREY  = colors.HexColor("#666666")
RULE      = colors.HexColor("#C8D4E8")

# ---------------------------------------------------------------------------
# Statement data
# ---------------------------------------------------------------------------
ACCOUNT_HOLDER  = "ALEX J MORGAN"
CARD_NUMBER     = "4519 **** **** 7823"
STATEMENT_DATE  = "March 20, 2026"
STATEMENT_PERIOD = "Feb 21, 2026  –  Mar 20, 2026"
PAYMENT_DUE     = "April 14, 2026"
CREDIT_LIMIT    = 15_000.00

PREV_BALANCE    = 2_502.77
PAYMENTS        = 2_502.77   # paid in full
NEW_PURCHASES   = 2_037.30
INTEREST        = 0.00
NEW_BALANCE     = NEW_PURCHASES  # = 2037.30
MIN_PAYMENT     = max(25.00, round(NEW_BALANCE * 0.02, 2))
AVAILABLE_CREDIT = CREDIT_LIMIT - NEW_BALANCE

TRANSACTIONS = [
    # (Trans Date,  Post Date,   Description,                         Amount)
    ("Feb 22",  "Feb 23",  "UBER EATS TORONTO ON",                   42.30),
    ("Feb 24",  "Feb 25",  "AMAZON.CA",                             189.99),
    ("Feb 25",  "Feb 26",  "PETRO-CANADA 4521 TORONTO",              73.45),
    ("Feb 26",  "Feb 27",  "SHOPPERS DRUG MART #1456",               56.78),
    ("Feb 28",  "Mar 01",  "STARBUCKS #8834 TORONTO",                23.45),
    ("Mar 02",  "Mar 03",  "WHOLE FOODS MARKET TORONTO",            145.67),
    ("Mar 03",  "Mar 04",  "ESSO STATION 2234 TORONTO",              68.90),
    ("Mar 04",  "Mar 05",  "LCBO #0445 TORONTO ON",                  67.89),
    ("Mar 05",  "Mar 06",  "NETFLIX.COM",                            18.99),
    ("Mar 06",  "Mar 07",  "UBER RIDES TORONTO ON",                  34.56),
    ("Mar 07",  "Mar 08",  "SHOPPERS DRUG MART #1456",               45.67),
    ("Mar 08",  "Mar 09",  "THE KEG STEAKHOUSE TORONTO",            234.50),
    ("Mar 09",  "Mar 10",  "LOBLAWS #1234 TORONTO ON",              156.78),
    ("Mar 10",  "Mar 11",  "AMAZON.CA",                              89.99),
    ("Mar 11",  "Mar 12",  "SPORT CHEK SCARBOROUGH ON",             123.45),
    ("Mar 12",  "Mar 13",  "BELL MOBILITY TORONTO ON",               95.67),
    ("Mar 13",  "Mar 14",  "PETRO-CANADA 4521 TORONTO",              71.23),
    ("Mar 14",  "Mar 15",  "APPLE.COM/BILL ITUNES",                  12.99),
    ("Mar 15",  "Mar 16",  "WHOLE FOODS MARKET TORONTO",            178.90),
    ("Mar 16",  "Mar 17",  "CINEPLEX ENTERTAINMENT",                 45.67),
    ("Mar 17",  "Mar 18",  "UBER EATS TORONTO ON",                   38.90),
    ("Mar 18",  "Mar 19",  "INDIGO CHAPTERS TORONTO ON",             56.78),
    ("Mar 19",  "Mar 20",  "WINNERS #0892 TORONTO ON",               89.45),
    ("Mar 20",  "Mar 20",  "ESSO STATION 2234 TORONTO",              75.34),
]

assert abs(sum(t[3] for t in TRANSACTIONS) - NEW_PURCHASES) < 0.01, \
    f"Transaction total {sum(t[3] for t in TRANSACTIONS):.2f} != {NEW_PURCHASES}"


# ---------------------------------------------------------------------------
# Helper: money formatting
# ---------------------------------------------------------------------------
def fmt(amount: float, show_sign: bool = False) -> str:
    sign = "+" if show_sign and amount > 0 else ""
    return f"{sign}${amount:,.2f}"


# ---------------------------------------------------------------------------
# Style factory
# ---------------------------------------------------------------------------
def make_styles() -> dict:
    base = getSampleStyleSheet()

    def s(name, **kw) -> ParagraphStyle:
        kw.setdefault("fontName", "Helvetica")
        kw.setdefault("textColor", DARK_TEXT)
        return ParagraphStyle(name, parent=base["Normal"], **kw)

    return {
        "bank_name": s("bank_name",
                        fontSize=20, fontName="Helvetica-Bold",
                        textColor=colors.white, leading=24),
        "bank_sub":  s("bank_sub",
                        fontSize=9, textColor=colors.HexColor("#AACCFF"), leading=12),
        "stmt_title": s("stmt_title",
                        fontSize=14, fontName="Helvetica-Bold",
                        textColor=colors.white, alignment=TA_RIGHT, leading=18),
        "stmt_period": s("stmt_period",
                         fontSize=9, textColor=colors.HexColor("#AACCFF"),
                         alignment=TA_RIGHT, leading=13),
        "section_hdr": s("section_hdr",
                          fontSize=9, fontName="Helvetica-Bold",
                          textColor=colors.white),
        "label":  s("label",  fontSize=9,  textColor=MID_GREY),
        "value":  s("value",  fontSize=9,  textColor=DARK_TEXT),
        "bold9":  s("bold9",  fontSize=9,  fontName="Helvetica-Bold"),
        "bold10": s("bold10", fontSize=10, fontName="Helvetica-Bold"),
        "red10":  s("red10",  fontSize=10, fontName="Helvetica-Bold",
                    textColor=RED),
        "small":  s("small",  fontSize=7.5, textColor=MID_GREY, leading=10),
        "footer": s("footer", fontSize=7, textColor=MID_GREY,
                    alignment=TA_CENTER, leading=10),
        "th":     s("th",     fontSize=8.5, fontName="Helvetica-Bold",
                    textColor=colors.white),
        "td":     s("td",     fontSize=8.5, leading=11),
        "td_r":   s("td_r",   fontSize=8.5, leading=11, alignment=TA_RIGHT),
        "td_bold":s("td_bold",fontSize=8.5, fontName="Helvetica-Bold", leading=11),
        "td_bold_r": s("td_bold_r", fontSize=8.5, fontName="Helvetica-Bold",
                       leading=11, alignment=TA_RIGHT),
    }


# ---------------------------------------------------------------------------
# Build PDF
# ---------------------------------------------------------------------------
def build_pdf(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.6 * inch,
        title="Visa Credit Card Statement – March 2026",
        author="Royal Trust Bank",
    )

    W = LETTER[0] - doc.leftMargin - doc.rightMargin   # usable width
    st = make_styles()
    story = []

    # -----------------------------------------------------------------------
    # 1. HEADER BANNER  (logo placeholder + statement title)
    # -----------------------------------------------------------------------
    logo_cell = [
        Paragraph("ROYAL TRUST", st["bank_name"]),
        Paragraph("VISA INFINITE CARD", st["bank_sub"]),
    ]
    title_cell = [
        Paragraph("CREDIT CARD STATEMENT", st["stmt_title"]),
        Paragraph(f"Statement Period:  {STATEMENT_PERIOD}", st["stmt_period"]),
        Paragraph(f"Statement Date:  {STATEMENT_DATE}", st["stmt_period"]),
    ]

    header_tbl = Table(
        [[logo_cell, title_cell]],
        colWidths=[W * 0.5, W * 0.5],
    )
    header_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), NAVY),
        ("TOPPADDING",   (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 14),
        ("LEFTPADDING",  (0, 0), (0, 0),   18),
        ("RIGHTPADDING", (1, 0), (1, 0),   18),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(header_tbl)

    # Gold accent rule under header
    story.append(HRFlowable(width=W, thickness=3, color=GOLD, spaceAfter=10))

    # -----------------------------------------------------------------------
    # 2. ACCOUNT INFO STRIP
    # -----------------------------------------------------------------------
    acct_data = [[
        [Paragraph("ACCOUNT HOLDER", st["label"]),
         Paragraph(ACCOUNT_HOLDER, st["bold10"])],
        [Paragraph("CARD NUMBER", st["label"]),
         Paragraph(CARD_NUMBER, st["bold10"])],
        [Paragraph("CREDIT LIMIT", st["label"]),
         Paragraph(fmt(CREDIT_LIMIT), st["bold10"])],
        [Paragraph("AVAILABLE CREDIT", st["label"]),
         Paragraph(fmt(AVAILABLE_CREDIT), st["bold10"])],
    ]]
    acct_tbl = Table(acct_data, colWidths=[W / 4] * 4)
    acct_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_BG),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("LINEAFTER",     (0, 0), (2, 0),   0.5, RULE),
    ]))
    story.append(acct_tbl)
    story.append(Spacer(1, 12))

    # -----------------------------------------------------------------------
    # 3. ACCOUNT SUMMARY  +  PAYMENT BOX  (side by side)
    # -----------------------------------------------------------------------
    # Left: summary table
    summary_rows = [
        [Paragraph("ACCOUNT SUMMARY", st["section_hdr"]), ""],
        [Paragraph("Previous Balance", st["label"]),
         Paragraph(fmt(PREV_BALANCE), st["td_r"])],
        [Paragraph("Payments & Credits", st["label"]),
         Paragraph(f"-{fmt(PAYMENTS)}", st["td_r"])],
        [Paragraph("New Purchases", st["label"]),
         Paragraph(fmt(NEW_PURCHASES, show_sign=True), st["td_r"])],
        [Paragraph("Cash Advances", st["label"]),
         Paragraph("$0.00", st["td_r"])],
        [Paragraph("Interest Charged", st["label"]),
         Paragraph(fmt(INTEREST, show_sign=True), st["td_r"])],
        [Paragraph("Fees Charged", st["label"]),
         Paragraph("$0.00", st["td_r"])],
        ["", ""],   # spacer row
        [Paragraph("NEW BALANCE", st["bold9"]),
         Paragraph(fmt(NEW_BALANCE), st["td_bold_r"])],
    ]
    sum_tbl = Table(summary_rows, colWidths=[W * 0.27, W * 0.18])
    sum_tbl.setStyle(TableStyle([
        # header row
        ("BACKGROUND",    (0, 0), (-1, 0), MID_BLUE),
        ("SPAN",          (0, 0), (1, 0)),
        ("TOPPADDING",    (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("LEFTPADDING",   (0, 0), (-1, 0), 8),
        # body
        ("BACKGROUND",    (0, 1), (-1, -1), LIGHT_BG),
        ("TOPPADDING",    (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LEFTPADDING",   (0, 1), (-1, -1), 8),
        ("RIGHTPADDING",  (1, 1), (1, -1), 8),
        # separator before total
        ("LINEABOVE",     (0, -1), (-1, -1), 1, MID_BLUE),
        ("BACKGROUND",    (0, -1), (-1, -1), colors.HexColor("#D6E4F7")),
        ("TOPPADDING",    (0, -1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
        # spacer row
        ("TOPPADDING",    (0, -2), (-1, -2), 2),
        ("BOTTOMPADDING", (0, -2), (-1, -2), 2),
    ]))

    # Right: payment info box
    pay_rows = [
        [Paragraph("PAYMENT INFORMATION", st["section_hdr"])],
        [Paragraph(
            f"<b>Payment Due Date:</b><br/>"
            f"<font size=13><b>{PAYMENT_DUE}</b></font>",
            ParagraphStyle("pi", fontName="Helvetica", fontSize=9,
                           textColor=DARK_TEXT, leading=16))],
        [Paragraph(
            f"<b>Minimum Payment Due:</b><br/>"
            f"<font size=13 color='#CC0000'><b>{fmt(MIN_PAYMENT)}</b></font>",
            ParagraphStyle("pi2", fontName="Helvetica", fontSize=9,
                           textColor=DARK_TEXT, leading=16))],
        [Paragraph(
            f"<b>New Balance:</b><br/>"
            f"<font size=13><b>{fmt(NEW_BALANCE)}</b></font>",
            ParagraphStyle("pi3", fontName="Helvetica", fontSize=9,
                           textColor=DARK_TEXT, leading=16))],
        [Paragraph(
            "To avoid interest charges, pay the New Balance in full by the "
            "Payment Due Date. Interest accrues at 19.99% per annum on "
            "purchases and 22.99% on cash advances.",
            ParagraphStyle("disc", fontName="Helvetica", fontSize=7.5,
                           textColor=MID_GREY, leading=10))],
    ]
    pay_tbl = Table(pay_rows, colWidths=[W * 0.45 - 10])
    pay_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), MID_BLUE),
        ("TOPPADDING",    (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("LEFTPADDING",   (0, 0), (-1, 0), 8),
        ("BACKGROUND",    (0, 1), (-1, -1), colors.HexColor("#FFF8E6")),
        ("TOPPADDING",    (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
        ("LEFTPADDING",   (0, 1), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 1), (-1, -1), 10),
        ("LINEBELOW",     (0, 1), (-1, -2), 0.5, RULE),
    ]))

    two_col = Table(
        [[sum_tbl, pay_tbl]],
        colWidths=[W * 0.45, W * 0.55],
    )
    two_col.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 10),
    ]))
    story.append(two_col)
    story.append(Spacer(1, 14))

    # -----------------------------------------------------------------------
    # 4. TRANSACTION SECTION HEADER
    # -----------------------------------------------------------------------
    hdr_bar = Table(
        [[Paragraph("TRANSACTIONS — MARCH 2026 STATEMENT", st["section_hdr"])]],
        colWidths=[W],
    )
    hdr_bar.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), MID_BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
    ]))
    story.append(hdr_bar)

    # -----------------------------------------------------------------------
    # 5. TRANSACTION TABLE
    # -----------------------------------------------------------------------
    COL_W = [
        W * 0.095,   # Trans Date
        W * 0.095,   # Post Date
        W * 0.62,    # Description
        W * 0.19,    # Amount
    ]

    # Column headers
    tx_rows = [[
        Paragraph("TRANS DATE", st["th"]),
        Paragraph("POST DATE",  st["th"]),
        Paragraph("DESCRIPTION", st["th"]),
        Paragraph("AMOUNT (CAD)", ParagraphStyle(
            "th_r", parent=st["th"], alignment=TA_RIGHT)),
    ]]

    # Transaction rows
    for i, (tdate, pdate, desc, amt) in enumerate(TRANSACTIONS):
        row_style = st["td"]
        amt_style = st["td_r"]
        tx_rows.append([
            Paragraph(tdate, row_style),
            Paragraph(pdate, row_style),
            Paragraph(desc,  row_style),
            Paragraph(fmt(amt), amt_style),
        ])

    # Subtotal row
    tx_rows.append([
        Paragraph("", st["td"]),
        Paragraph("", st["td"]),
        Paragraph("Total New Purchases", st["td_bold"]),
        Paragraph(fmt(NEW_PURCHASES), st["td_bold_r"]),
    ])

    tx_tbl = Table(tx_rows, colWidths=COL_W, repeatRows=1)

    row_count = len(tx_rows)
    tx_style = TableStyle([
        # Header row
        ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
        ("TOPPADDING",    (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("LEFTPADDING",   (0, 0), (-1, 0), 6),
        ("RIGHTPADDING",  (0, 0), (-1, 0), 6),
        # Body
        ("TOPPADDING",    (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("LEFTPADDING",   (0, 1), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 1), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        # Alternating row colours
        *[("BACKGROUND", (0, r), (-1, r), ROW_ALT)
          for r in range(2, row_count - 1, 2)],
        # Total row
        ("BACKGROUND",    (0, -1), (-1, -1), colors.HexColor("#D6E4F7")),
        ("LINEABOVE",     (0, -1), (-1, -1), 1, MID_BLUE),
        ("TOPPADDING",    (0, -1), (-1, -1), 7),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
        # Outer border
        ("BOX",           (0, 0),  (-1, -1), 0.5, RULE),
        ("INNERGRID",     (0, 1),  (-1, -2), 0.25, RULE),
    ])
    tx_tbl.setStyle(tx_style)
    story.append(tx_tbl)
    story.append(Spacer(1, 16))

    # -----------------------------------------------------------------------
    # 6. INTEREST RATE SUMMARY TABLE
    # -----------------------------------------------------------------------
    rate_hdr = Table(
        [[Paragraph("INTEREST RATE INFORMATION", st["section_hdr"])]],
        colWidths=[W],
    )
    rate_hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), MID_BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
    ]))
    story.append(rate_hdr)

    rate_cw = [W * 0.40, W * 0.20, W * 0.20, W * 0.20]
    rate_rows = [
        [Paragraph("Type", st["th"]),
         Paragraph("Annual Rate",   ParagraphStyle("th_c", parent=st["th"], alignment=TA_CENTER)),
         Paragraph("Daily Rate",    ParagraphStyle("th_c", parent=st["th"], alignment=TA_CENTER)),
         Paragraph("Interest This Period", ParagraphStyle("th_r2", parent=st["th"], alignment=TA_RIGHT))],
        [Paragraph("Purchases",      st["td"]),
         Paragraph("19.99%", ParagraphStyle("tc", parent=st["td"], alignment=TA_CENTER)),
         Paragraph("0.05476%", ParagraphStyle("tc", parent=st["td"], alignment=TA_CENTER)),
         Paragraph("$0.00", ParagraphStyle("tr", parent=st["td"], alignment=TA_RIGHT))],
        [Paragraph("Cash Advances",  st["td"]),
         Paragraph("22.99%", ParagraphStyle("tc2", parent=st["td"], alignment=TA_CENTER)),
         Paragraph("0.06299%", ParagraphStyle("tc2", parent=st["td"], alignment=TA_CENTER)),
         Paragraph("$0.00", ParagraphStyle("tr2", parent=st["td"], alignment=TA_RIGHT))],
        [Paragraph("Balance Transfers", st["td"]),
         Paragraph("19.99%", ParagraphStyle("tc3", parent=st["td"], alignment=TA_CENTER)),
         Paragraph("0.05476%", ParagraphStyle("tc3", parent=st["td"], alignment=TA_CENTER)),
         Paragraph("$0.00", ParagraphStyle("tr3", parent=st["td"], alignment=TA_RIGHT))],
    ]
    rate_tbl = Table(rate_rows, colWidths=rate_cw)
    rate_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
        ("TOPPADDING",    (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("LEFTPADDING",   (0, 0), (-1, 0), 6),
        ("RIGHTPADDING",  (0, 0), (-1, 0), 6),
        ("BACKGROUND",    (0, 1), (-1, -1), LIGHT_BG),
        ("BACKGROUND",    (0, 2), (-1, 2), ROW_ALT),
        ("TOPPADDING",    (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("LEFTPADDING",   (0, 1), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 1), (-1, -1), 6),
        ("BOX",           (0, 0), (-1, -1), 0.5, RULE),
        ("INNERGRID",     (0, 1), (-1, -1), 0.25, RULE),
    ]))
    story.append(rate_tbl)
    story.append(Spacer(1, 14))

    # -----------------------------------------------------------------------
    # 7. FOOTER
    # -----------------------------------------------------------------------
    story.append(HRFlowable(width=W, thickness=1, color=RULE, spaceBefore=4, spaceAfter=6))

    footer_lines = [
        (
            "<b>HOW TO MAKE A PAYMENT:</b>  Online banking · Telephone banking · ATM · "
            "In branch · Pre-authorized debit"
        ),
        (
            "Royal Trust Bank, P.O. Box 5100, Toronto, ON  M5J 2T3  |  "
            "Customer Service: 1-800-769-2511  |  royaltrustbank.ca"
        ),
        (
            "This statement is for informational purposes only and is generated as "
            "synthetic mock data. All transactions, account numbers, and balances are "
            "fictitious. Royal Trust Bank is a fictional entity created for development "
            "and testing purposes."
        ),
    ]
    for line in footer_lines:
        story.append(Paragraph(line, st["footer"]))
        story.append(Spacer(1, 2))

    # -----------------------------------------------------------------------
    # Build
    # -----------------------------------------------------------------------
    def on_first_page(canvas, doc):
        canvas.saveState()
        # Page number
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MID_GREY)
        canvas.drawRightString(
            doc.pagesize[0] - doc.rightMargin,
            0.35 * inch,
            f"Page 1  |  Account ending {CARD_NUMBER[-4:]}  |  {STATEMENT_DATE}",
        )
        # Thin gold bottom rule
        canvas.setStrokeColor(GOLD)
        canvas.setLineWidth(2)
        canvas.line(
            doc.leftMargin, 0.45 * inch,
            doc.pagesize[0] - doc.rightMargin, 0.45 * inch,
        )
        canvas.restoreState()

    def on_later_pages(canvas, doc):
        on_first_page(canvas, doc)

    doc.build(story, onFirstPage=on_first_page, onLaterPages=on_later_pages)
    import sys
    out = sys.stdout.buffer if hasattr(sys.stdout, "buffer") else sys.stdout
    lines = [
        f"[OK] PDF written to: {output_path.name}",
        f"     Transactions : {len(TRANSACTIONS)}",
        f"     New purchases: ${NEW_PURCHASES:,.2f}",
        f"     New balance  : ${NEW_BALANCE:,.2f}",
        f"     Min payment  : ${MIN_PAYMENT:,.2f}",
        f"     Due date     : {PAYMENT_DUE}",
    ]
    for line in lines:
        out.write((line + "\n").encode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    here = Path(__file__).parent.parent   # project root
    out  = here / "data" / "mock" / "visa_statement_mar2026.pdf"
    build_pdf(out)
