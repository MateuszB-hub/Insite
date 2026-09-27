"""Build small, real text PDFs in code, for résumé tests.

No files on disk and no real people's data: each test writes the résumé it
needs. The output is a plain PDF 1.4 with Helvetica text, which pypdf reads
the way it reads a résumé exported from Word or LinkedIn.
"""


def _escape(line: str) -> str:
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(lines: list[str], pages: int = 1) -> bytes:
    """A PDF whose pages each show `lines` (ASCII) top to bottom."""
    objects: list[bytes] = []

    def add(body: str | bytes) -> int:
        objects.append(body.encode("latin-1") if isinstance(body, str) else body)
        return len(objects)

    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids = []
    pages_id = len(objects) + 2 * pages + 1  # filled in after the pages
    for _ in range(pages):
        text = "BT /F1 10 Tf 50 780 Td 13 TL " + " ".join(
            f"({_escape(line)}) '" for line in lines) + " ET"
        stream = text.encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(add(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>"))
    kids = " ".join(f"{p} 0 R" for p in page_ids)
    assert add(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>") == pages_id
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


NURSE = [
    "Dana Whitfield",
    "Omaha, NE | dana.w@example.com | (555) 010-2233",
    "SUMMARY",
    "Registered nurse with experience in emergency and med-surg care.",
    "EXPERIENCE",
    "Registered Nurse - Nebraska Medical Center",
    "2019-06 to present",
    "Triage, patient assessment, IV therapy, Epic charting.",
    "Licensed Practical Nurse - Bellevue Care Home",
    "2015-01 to 2019-05",
    "Medication administration and wound care.",
    "SKILLS",
    "Patient assessment, Triage, IV therapy, Wound care, Epic",
    "CERTIFICATIONS",
    "BLS, ACLS, PALS",
]
