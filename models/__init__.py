# -*- coding: utf-8 -*-

# Mixins transversales abstractos
from . import supply_chain_mixins

# Secuencias en compras e inventario
from . import purchase_order
from . import stock_picking

# Control de stock negativo
from . import res_config
from . import stock_location
from . import stock_quant

# Trazabilidad transversal de suministro (Allocation)
from . import supply_chain_allocation
from . import stock_move