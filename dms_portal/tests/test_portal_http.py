"""Plan 16B Task 5 — the HTTP surface.

Section 8: "no IDOR by numeric ID". Section 11, first required test: portal
user A cannot reach Outlet/order/invoice/media B.
"""
from odoo.tests.common import HttpCase, tagged

from .test_portal_catalog import PortalCatalogCase


@tagged('post_install', '-at_install')
class TestPortalHttp(PortalCatalogCase, HttpCase):

    def setUp(self):
        super().setUp()
        self.buyer.write({'password': 'buyer-16b-pw'})
        self.env.flush_all()

    def _login(self):
        self.authenticate('buyer-16a@dms.test', 'buyer-16b-pw')

    def test_anonymous_is_not_served_the_portal(self):
        response = self.url_open('/my/dms', allow_redirects=False)
        self.assertIn(response.status_code, (302, 303),
                      'an unauthenticated request must be redirected to login')

    def test_home_says_so_when_there_is_no_entitlement(self):
        self._login()
        body = self.url_open('/my/dms').text
        self.assertIn('no approved entitlement', body)

    def test_catalog_of_an_entitled_outlet_renders_its_listing(self):
        self._entitle()
        self._listing()
        rows = self.env['dms.portal.api'].with_user(
            self.buyer).dms_portal_catalog(outlet_id=self.outlet_a.id)
        self.assertTrue(rows, 'the API itself returned nothing')
        self._login()
        body = self.url_open(
            f'/my/dms/catalog?outlet_id={self.outlet_a.id}').text
        self.assertIn('PT SKU A', body)

    def test_catalog_of_another_outlet_is_404_not_403(self):
        """A 403 confirms the outlet exists. An id that answers differently
        for a real outlet than for an invented one is an oracle, which is
        what section 8 means by "no IDOR by numeric ID"."""
        self._entitle()
        self._login()
        response = self.url_open(
            f'/my/dms/catalog?outlet_id={self.outlet_b.id}')
        self.assertEqual(response.status_code, 404)

    def test_order_of_another_partner_is_404(self):
        self._entitle()
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.outlet_b.id})
        self._login()
        response = self.url_open(f'/my/dms/order/{order.id}')
        self.assertEqual(response.status_code, 404)

    def test_own_order_renders(self):
        self._entitle()
        result = self.env['dms.portal.api'].with_user(
            self.buyer).dms_portal_submit(
                self.outlet_a.id,
                [{'product_id': self.product_a.id, 'quantity': 1}])
        self.assertTrue(result['order_id'], result.get('errors'))
        self._login()
        body = self.url_open(f"/my/dms/order/{result['order_id']}").text
        self.assertIn('PT SKU A', body)
