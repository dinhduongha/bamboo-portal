"""Plan 16B Task 1 — the catalog a portal user is allowed to see.

Section 5: "Server resolve serving Distributor, assortment, pricelist,
fiscal position, credit va warehouse. Client khong chon arbitrary
company/warehouse/pricelist/tax."

`dms` already decides what an Outlet may buy:
`dms.outlet.product.listing._effective_for(outlet)` filters by state, by the
effective window, by company and by the Distributor the row was snapshotted
under. This layer adds the one thing that model cannot know -- whether the
caller is entitled to that Outlet at all.
"""
from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from .test_entitlement import EntitlementCase


class PortalCatalogCase(EntitlementCase):
    """A real serving topology, because a quote without one raises.

    `res.partner.dms_quote` refuses an Outlet with no serving Distributor --
    "chua co Distributor phuc vu" -- which is correct behaviour and the reason
    this fixture cannot be two `res.partner` rows. It mirrors the topology
    `dms/tests/test_pricing_service.py` sets up: parent company, a Distributor
    child, a Team pointing at it, and an active `dms.outlet.assignment`.
    """

    def setUp(self):
        super().setUp()
        Company = self.env['res.company']
        self.parent = Company.create({'name': 'PT Parent'})
        self.dist = Company.create({
            'name': 'PT Dist', 'is_dms_distributor': True,
            'dms_parent_company_id': self.parent.id})
        self.team = self.env['crm.team'].create({
            'is_dms_team': True, 'dms_team_code': 'PTT', 'name': 'PT Team',
            'company_id': self.parent.id,
            'distributor_company_id': self.dist.id})
        self.env.user.write({'company_ids': [
            (4, self.parent.id), (4, self.dist.id)]})

        self.outlet_a = self.env['res.partner'].with_company(
            self.parent).create({
                'name': 'PT Outlet A', 'is_outlet': True, 'customer_rank': 1,
                'company_id': self.parent.id,
                'dms_parent_company_id': self.parent.id})
        self.env['dms.outlet.assignment'].create({
            'outlet_id': self.outlet_a.id, 'company_id': self.parent.id,
            'distributor_company_id': self.dist.id, 'team_id': self.team.id,
            'reason': 'portal fixture'}).action_activate()
        self.outlet_a.invalidate_recordset()

        Product = self.env['product.product']
        self.product_a = Product.create({
            'name': 'PT SKU A', 'company_id': False, 'list_price': 500.0})
        self.product_b = Product.create({
            'name': 'PT SKU B', 'company_id': False, 'list_price': 200.0})
        self.env['dms.distributor.assortment'].create({
            'company_id': self.dist.id, 'product_id': self.product_a.id,
            'state': 'active'})

        pricelist = self.env['product.pricelist'].create({
            'name': 'PT Shared', 'company_id': False,
            'item_ids': [(0, 0, {
                'applied_on': '1_product',
                'product_tmpl_id': self.product_a.product_tmpl_id.id,
                'compute_price': 'fixed', 'fixed_price': 100.0})]})
        # Creating a pricelist does not attach it to anything. Without this
        # the quote falls back to `list_price` and every price assertion below
        # measures the product, not the pricing service.
        self.outlet_a.with_company(self.dist) \
            .specific_property_product_pricelist = pricelist

        # `dms_quote` refuses an order with no credit headroom --
        # "Vuot han muc tin dung: con 0" -- so an Outlet with no credit row
        # cannot buy anything at all. That is correct behaviour; the fixture
        # has to grant a limit the way a real Distributor would.
        self.env['dms.outlet.credit'].create({
            'res_partner_id': self.outlet_a.id,
            'company_id': self.parent.id,
            'distributor_company_id': self.dist.id,
            'credit_limit': 1000000.0,
            'credit_days': 30,
        })
        self.outlet_a.invalidate_recordset()

    def _listing(self, product=None, outlet=None):
        listing = self.env['dms.outlet.product.listing'].create({
            'res_partner_id': (outlet or self.outlet_a).id,
            'product_id': (product or self.product_a).id,
            'company_id': self.parent.id,
            'distributor_company_id': self.dist.id,
        })
        listing.action_activate()
        return listing

    def _entitle(self, partner=None):
        ent = self._entitlement(partner=partner or self.outlet_a)
        ent.with_user(self.approver).action_approve()
        return ent


@tagged('post_install', '-at_install')
class TestPortalCatalog(PortalCatalogCase):

    def test_catalog_is_empty_without_entitlement(self):
        self.assertEqual(
            self.env['dms.portal.api'].with_user(
                self.buyer).dms_portal_catalog(), [])

    def test_catalog_of_an_unentitled_outlet_is_refused_not_empty(self):
        """An empty list says "this shop sells nothing"; that is a leak of
        the shop's existence. Refuse instead."""
        self._entitle()
        with self.assertRaises(AccessError):
            self.env['dms.portal.api'].with_user(self.buyer).dms_portal_catalog(
                outlet_id=self.outlet_b.id)

    def test_catalog_returns_the_active_listing(self):
        self._entitle()
        self._listing()
        rows = self.env['dms.portal.api'].with_user(
            self.buyer).dms_portal_catalog(outlet_id=self.outlet_a.id)
        self.assertEqual([r['product_id'] for r in rows], [self.product_a.id])
        self.assertEqual(rows[0]['price_unit'], 100.0)

    def test_catalog_never_exposes_cost(self):
        """Section 8 forbids margins reaching the portal. `standard_price` is
        the margin, one subtraction away.

        The listing is created first on purpose: this assertion is vacuous
        over an empty list, and an empty list is exactly what a broken
        catalog returns."""
        self._entitle()
        self._listing()
        rows = self.env['dms.portal.api'].with_user(
            self.buyer).dms_portal_catalog(outlet_id=self.outlet_a.id)
        self.assertTrue(rows)
        for row in rows:
            self.assertNotIn('standard_price', row)
            self.assertNotIn('margin', row)

    def test_catalog_takes_no_client_supplied_pricelist(self):
        self._entitle()
        with self.assertRaises(TypeError):
            self.env['dms.portal.api'].with_user(self.buyer).dms_portal_catalog(
                outlet_id=self.outlet_a.id, pricelist_id=1)
