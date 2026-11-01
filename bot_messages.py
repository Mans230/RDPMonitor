"""Balanced Telegram HTML pages sized for a narrow mobile message bubble."""
import html
from html.parser import HTMLParser
import unicodedata


class _Pages(HTMLParser):
    def __init__(self, rows, columns):
        super().__init__(convert_charrefs=False)
        self.rows, self.columns = rows, columns
        self.stack, self.parts, self.pages = [], [], []
        self.row, self.column, self.size = 1, 0, 0
        self.content = False

    def flush(self):
        if not self.content:
            return
        self.pages.append(''.join(self.parts) + ''.join('</'+tag+'>' for tag, _ in reversed(self.stack)))
        self.parts = [source for _, source in self.stack]
        self.row, self.column, self.size, self.content = 1, 0, 0, False

    def handle_starttag(self, tag, attrs):
        source = self.get_starttag_text()
        self.parts.append(source)
        self.stack.append((tag, source))

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
            self.parts.append('</'+tag+'>')
        else:
            raise ValueError('Unbalanced message HTML')

    def atom(self, source, value):
        width = sum(0 if unicodedata.combining(c) or c in '\u200f\u200e\ufe0f' else
                    2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in value)
        new_row = self.row + (1 if value == '\n' or self.column + width > self.columns else 0)
        if self.content and (new_row > self.rows or self.size + len(source) > 2800):
            self.flush()
            new_row = 1
        self.parts.append(source)
        self.row = new_row
        self.column = 0 if value == '\n' else (width if self.column+width > self.columns else self.column+width)
        self.size += len(source)
        self.content = True

    def handle_data(self, data):
        for char in data:
            self.atom(html.escape(char, quote=False), char)

    def handle_entityref(self, name):
        source = '&'+name+';'
        self.atom(source, html.unescape(source))

    def handle_charref(self, name):
        source = '&#'+name+';'
        self.atom(source, html.unescape(source))


def message_pages(text, rows=16, columns=32):
    """Preserve every visible character and balance tags across each page."""
    parser = _Pages(rows, columns)
    try:
        parser.feed(str(text))
        parser.close()
        if parser.stack:
            raise ValueError('Unclosed message HTML')
        parser.flush()
        return parser.pages or ['']
    except ValueError:
        # Invalid legacy HTML still reaches the user as literal, escaped text.
        parser = _Pages(rows, columns)
        parser.feed(html.escape(str(text)))
        parser.close()
        parser.flush()
        return parser.pages or ['']
