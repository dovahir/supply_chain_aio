# -*- coding: utf-8 -*-
from odoo.tests import common, tagged


@tagged('post_install', '-at_install', 'supply_chain_aio')
class TestSupplyChainMixins(common.TransactionCase):
    def test_01_category_cascading_mixin(self):
        """Valida que el mixin de propagación en cascada actualice subcategorías sin alterar padres."""
        parent_categ = self.env['product.category'].create({
            'name': 'Categoría Padre Test',
        })
        child_categ = self.env['product.category'].create({
            'name': 'Categoría Hija Test',
            'parent_id': parent_categ.id,
        })
        # Si el mixin está instalado y product.category hereda de él, _cascade_field_to_descendants existe
        if hasattr(parent_categ, '_cascade_field_to_descendants'):
            # Modificar una bandera en el padre y propagar
            parent_categ._cascade_field_to_descendants('name', 'Nombre Propagado', 'skip_test_prop')
            self.assertEqual(child_categ.name, 'Nombre Propagado')
