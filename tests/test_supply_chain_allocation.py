# -*- coding: utf-8 -*-
from odoo.tests import common, tagged
from odoo.exceptions import UserError, ValidationError


@tagged('post_install', '-at_install', 'supply_chain_aio')
class TestSupplyChainAllocation(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')

        cls.product = cls.env['product.product'].create({
            'name': 'Producto de Prueba SCM',
            'type': 'consu',
            'uom_id': cls.uom_unit.id,
        })

    def test_01_allocation_creation_and_state(self):
        """Valida creación y cálculo de estado de una asignación."""
        alloc = self.env['supply.chain.allocation'].create({
            'company_id': self.company.id,
            'product_id': self.product.id,
            'product_uom_id': self.uom_unit.id,
            'requested_qty': 10.0,
            'state': 'draft',
        })
        self.assertEqual(alloc.state, 'draft')
        self.assertEqual(alloc.requested_qty, 10.0)
        self.assertEqual(alloc.open_qty, 10.0)

    def test_02_allocation_ondelete_protection(self):
        """Verifica que el decorador @api.ondelete impida borrar asignaciones en estado in_progress o done."""
        alloc = self.env['supply.chain.allocation'].create({
            'company_id': self.company.id,
            'product_id': self.product.id,
            'product_uom_id': self.uom_unit.id,
            'requested_qty': 5.0,
            'state': 'in_progress',
        })
        with self.assertRaises(UserError):
            alloc.unlink()

        # En estado borrador sí se permite eliminar
        alloc.write({'state': 'draft'})
        self.assertTrue(alloc.unlink())

    def test_03_allocation_cancellation_action(self):
        """Valida que la cancelación interactiva con reintegración opere correctamente."""
        alloc = self.env['supply.chain.allocation'].create({
            'company_id': self.company.id,
            'product_id': self.product.id,
            'product_uom_id': self.uom_unit.id,
            'requested_qty': 8.0,
            'state': 'in_progress',
        })
        alloc.action_cancel_allocation(cancel_action='reintegrate', reason='Cancelación por ajuste logístico')
        self.assertEqual(alloc.state, 'cancel')
        self.assertEqual(alloc.cancel_action, 'reintegrate')
        self.assertEqual(alloc.cancel_reason, 'Cancelación por ajuste logístico')
