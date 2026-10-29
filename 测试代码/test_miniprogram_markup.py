"""Validate every native template's tag nesting without requiring IDE access."""
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / '微信小程序'


class WXMLTags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []

    def handle_starttag(self, tag, attrs):
        self.stack.append((tag, self.getpos()))

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if not self.stack:
            raise ValueError(f'{self.getpos()}: unexpected </{tag}>')
        expected, opened = self.stack.pop()
        if tag != expected:
            raise ValueError(f'{self.getpos()}: expected </{expected}> for opening at {opened}, got </{tag}>')

    def finish(self, markup):
        self.feed(markup)
        self.close()
        if self.stack:
            raise ValueError(f'Unclosed tags: {self.stack}')


class NativeTemplates(unittest.TestCase):
    def test_every_page_has_balanced_tags(self):
        files = sorted((ROOT / 'pages').rglob('*.wxml'))
        self.assertTrue(files, 'Native page templates must exist')
        for path in files:
            with self.subTest(page=str(path.relative_to(ROOT))):
                WXMLTags().finish(path.read_text('utf-8'))

    def test_checker_detects_wrong_closing_tag(self):
        with self.assertRaisesRegex(ValueError, 'expected </text>'):
            WXMLTags().finish('<view><text>{{deviceToken}}</view></view>')


if __name__ == '__main__':
    unittest.main()
