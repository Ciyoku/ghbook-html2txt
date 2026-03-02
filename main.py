from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional


HEADING_CLASS_RE = re.compile(r"^content_h(?:[1-9]|10|11)$", re.IGNORECASE)
PAGE_MARKER_RE = re.compile(
    r"^\s*ص\s*:\s*[0-9\u0660-\u0669\u06F0-\u06F9]+\s*$", re.IGNORECASE
)


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def parse_class_tokens(attrs: list[tuple[str, Optional[str]]]) -> set[str]:
    for name, value in attrs:
        if name.lower() == "class" and value:
            return {token.strip().lower() for token in value.split() if token.strip()}
    return set()


def get_attr_value(attrs: list[tuple[str, Optional[str]]], name: str) -> Optional[str]:
    needle = name.lower()
    for key, value in attrs:
        if key.lower() == needle:
            return value
    return None


def is_content_heading(tag: str, classes: set[str]) -> bool:
    if not tag.startswith("h"):
        return False
    return any(HEADING_CLASS_RE.match(css_class) for css_class in classes)


def is_page_marker(text: str) -> bool:
    return bool(PAGE_MARKER_RE.match(text))


def read_html_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "cp1256", "windows-1256", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


class HtmlBookParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []

        self.current_heading_tag: Optional[str] = None
        self.heading_parts: list[str] = []

        self.in_paragraph = False
        self.paragraph_events: list[str] = []

        self.in_content_text_span = False
        self.span_parts: list[str] = []
        self.span_inside_paragraph = False
        self.in_notelink_anchor = False
        self.anchor_parts: list[str] = []

        self.pending_hr_margin = False
        self.in_content_note_div = False
        self.note_parts: list[str] = []
        self.pending_page_separator = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self._open_tag(tag.lower(), attrs, self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self._open_tag(tag.lower(), attrs, self_closing=True)

    def _open_tag(
        self,
        tag: str,
        attrs: list[tuple[str, Optional[str]]],
        self_closing: bool,
    ) -> None:
        if self.in_content_note_div:
            if tag == "br":
                self.note_parts.append(" ")
            return

        classes = parse_class_tokens(attrs)
        element_id = get_attr_value(attrs, "id") or ""

        is_content_note_div = (
            tag == "div"
            and "content_note" in classes
            and element_id.lower().startswith("content_note_")
        )

        if is_content_heading(tag, classes):
            self._finalize_pending_hr_margin()
            self._emit_pending_page_separator()
            self.current_heading_tag = tag
            self.heading_parts = []

        if tag == "p" and "content_paragraph" in classes:
            self._finalize_pending_hr_margin()
            self.in_paragraph = True
            self.paragraph_events = []

        if tag == "span" and "content_text" in classes:
            self.in_content_text_span = True
            self.span_parts = []
            self.span_inside_paragraph = self.in_paragraph

        if tag == "a" and self.in_paragraph and "content_notelink" in classes:
            self.in_notelink_anchor = True
            self.anchor_parts = []

        if self.pending_hr_margin and is_content_note_div:
            self.in_content_note_div = True
            self.note_parts = []
            return

        if tag == "hr" and "content_hr" in classes:
            self._finalize_pending_hr_margin()
            self._append_line("____________")
            self.pending_hr_margin = True
            return

        if self.pending_hr_margin and not is_content_note_div:
            self._finalize_pending_hr_margin()

    def handle_endtag(self, tag: str) -> None:
        lower_tag = tag.lower()

        if self.in_content_note_div:
            if lower_tag == "div":
                note_text = normalize_whitespace("".join(self.note_parts))
                if note_text:
                    self._append_line(note_text)
                self.in_content_note_div = False
                self.note_parts = []
            return

        if lower_tag == "span" and self.in_content_text_span:
            span_text = normalize_whitespace("".join(self.span_parts))
            if span_text:
                if is_page_marker(span_text):
                    if self.span_inside_paragraph:
                        self.paragraph_events.append("PAGE_SEPARATOR:")
                    else:
                        self.pending_page_separator = True
                elif self.span_inside_paragraph:
                    self.paragraph_events.append(span_text)

            self.in_content_text_span = False
            self.span_inside_paragraph = False
            self.span_parts = []

        if lower_tag == "a" and self.in_notelink_anchor:
            marker_text = normalize_whitespace("".join(self.anchor_parts))
            if marker_text and self.in_paragraph:
                self.paragraph_events.append(marker_text)
            self.in_notelink_anchor = False
            self.anchor_parts = []

        if self.current_heading_tag and lower_tag == self.current_heading_tag:
            heading = normalize_whitespace("".join(self.heading_parts))
            if heading:
                self._append_line(f"## {heading}")
                self._append_blank_line()
            self.current_heading_tag = None
            self.heading_parts = []

        if lower_tag == "p" and self.in_paragraph:
            self._flush_paragraph()
            self.in_paragraph = False
            self.paragraph_events = []

    def handle_data(self, data: str) -> None:
        if self.in_content_note_div:
            self.note_parts.append(data)
            return
        if self.in_notelink_anchor:
            self.anchor_parts.append(data)
            return
        if self.current_heading_tag:
            self.heading_parts.append(data)
        if self.in_content_text_span:
            self.span_parts.append(data)

    def _finalize_pending_hr_margin(self) -> None:
        if self.pending_hr_margin:
            self.pending_hr_margin = False
            self._append_blank_line()

    def _emit_pending_page_separator(self) -> None:
        if self.pending_page_separator:
            self._append_line("PAGE_SEPARATOR")
            self._append_blank_line()
            self.pending_page_separator = False

    def _flush_paragraph(self) -> None:
        if not self.paragraph_events:
            return

        has_page_marker = False
        text_buffer: list[str] = []
        for event in self.paragraph_events:
            if event == "PAGE_SEPARATOR:":
                has_page_marker = True
            else:
                text_buffer.append(event)

        if text_buffer:
            self._emit_pending_page_separator()
            self._append_line(" ".join(text_buffer))
            self._append_blank_line()

        if has_page_marker:
            self.pending_page_separator = True

    def _append_line(self, line: str) -> None:
        clean = normalize_whitespace(line)
        if clean:
            self.lines.append(clean)

    def _append_blank_line(self) -> None:
        if self.lines and self.lines[-1] != "":
            self.lines.append("")

    def to_text(self) -> str:
        self._emit_pending_page_separator()
        while self.lines and self.lines[-1] == "":
            self.lines.pop()
        return "\n".join(self.lines) + ("\n" if self.lines else "")


def convert_html_to_text(input_path: Path, output_path: Path) -> None:
    html_text = read_html_text(input_path)
    parser = HtmlBookParser()
    parser.feed(html_text)
    parser.close()
    output_path.write_text(parser.to_text(), encoding="utf-8")


def resolve_output_path(input_path: Path, output_path: Optional[Path]) -> Path:
    if output_path:
        return output_path
    return input_path.with_suffix(".txt")


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 1 or len(args) > 2:
        return 1

    input_path = Path(args[0])
    output_path = resolve_output_path(input_path, Path(args[1]) if len(args) == 2 else None)

    if not input_path.exists():
        return 1
    if not input_path.is_file():
        return 1

    convert_html_to_text(input_path, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
