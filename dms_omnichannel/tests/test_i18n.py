"""Whether this addon can be read in another language.

Both optional addons were written in English, so nothing here needed
translating — but an unwrapped literal is invisible to gettext all the same,
and it stays invisible until somebody opens the module in Vietnamese and reads
an English error in the middle of a Vietnamese screen.

The guard is a source scan rather than a review convention because that is what
worked in `dms`: three Odoo-19 view breaks and 45 untranslatable f-strings all
shipped through review, and every one of them was found by a test that read the
source.
"""
import ast
import pathlib

from odoo.tests.common import TransactionCase, tagged

ROOT = pathlib.Path(__file__).resolve().parent.parent
ERRORS = {'UserError', 'ValidationError', 'AccessError', 'RedirectWarning'}


@tagged('post_install', '-at_install')
class TestI18nReachable(TransactionCase):

    def _offenders(self):
        found = []
        for path in sorted(ROOT.rglob('*.py')):
            if '__pycache__' in str(path) or '/tests/' in str(path):
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id in ERRORS and node.args):
                    continue
                first = node.args[0]
                bare = (isinstance(first, ast.Constant)
                        and isinstance(first.value, str))
                fstring = isinstance(first, ast.JoinedStr)
                formatted = (isinstance(first, ast.BinOp)
                             and isinstance(first.op, ast.Mod)
                             and isinstance(getattr(first, 'left', None), ast.Constant))
                if bare or fstring or formatted:
                    found.append('%s:%s' % (path.relative_to(ROOT), node.lineno))
        return found

    def test_every_error_message_goes_through_gettext(self):
        """`self.env._("...")`, never a bare literal and never an f-string.

        An f-string is the worse of the two: it is interpolated BEFORE gettext
        sees it, so the msgid changes with the data and matches nothing in any
        .po. Valid Python, green install, silently untranslated.
        """
        self.assertFalse(
            self._offenders(),
            'these messages cannot be translated: %s' % self._offenders())

    def test_the_translation_template_exists(self):
        pot = list((ROOT / 'i18n').glob('*.pot')) if (ROOT / 'i18n').exists() else []
        self.assertTrue(pot, 'no .pot: run odoo i18n export for this addon')
