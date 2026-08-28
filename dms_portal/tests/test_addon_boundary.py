"""Plan 16A Task 1 — the addon boundary itself.

Three facts that no other test in either module can see, and that fail
silently when they break.
"""
import pathlib

from odoo.tests.common import TransactionCase, tagged


def _manifest(addon):
    # Odoo 19's Manifest is itself a Mapping; there is no `.manifest`
    # attribute. Same helper shape as dms/tests/test_install_integrity.py.
    from odoo.modules.module import Manifest
    return Manifest.for_addon(addon)


@tagged('post_install', '-at_install')
class TestAddonBoundary(TransactionCase):

    #: Plan 16 section 12 — "Optional module can remain uninstalled without
    #: breaking core DMS." Master section 3 lists exactly these four as
    #: required only when B2B self-service is switched on.
    PROFILE_ONLY = ('portal', 'website_sale', 'payment', 'delivery')

    def test_core_dms_does_not_depend_on_portal(self):
        """The reason this addon exists.

        If any of the four ends up in `dms`'s own depends, every DMS install
        drags a storefront along and the exit criterion above becomes
        unreachable -- without a single test failing anywhere else.
        """
        depends = _manifest('dms')['depends']
        leaked = [name for name in self.PROFILE_ONLY if name in depends]
        self.assertFalse(
            leaked,
            f'core `dms` must not depend on {leaked}; they belong to this '
            f'addon (plan 16 section 12, master section 3)')

    def test_dms_portal_declares_its_own_deps(self):
        depends = _manifest('dms_portal')['depends']
        self.assertIn('dms', depends)
        self.assertIn('portal', depends)

    def test_this_addon_is_the_one_on_disk_we_think_it_is(self):
        """`addons_path` can swallow this module whole.

        The order on this stack is

            /mnt/srs-addons, /mnt/extra-addons, /mnt/oca-addons/*,
            /mnt/custom-addons/bamboo-dms

        and `/mnt/extra-addons` (`/home/dockers/odoo19/addons`) comes FIRST.
        Odoo takes the first directory matching the module name and warns
        about nothing. A module named `dms_portal` dropped in there would be
        loaded instead of this one, and every other test in this file would
        still pass -- against somebody else's code.
        """
        path = pathlib.Path(str(_manifest('dms_portal').path)).resolve()
        self.assertIn(
            'custom-addons', path.parts,
            f'dms_portal loaded from {path}, not from custom-addons; an '
            f'earlier entry in addons_path is shadowing it')
