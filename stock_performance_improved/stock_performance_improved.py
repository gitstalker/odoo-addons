# -*- coding: utf8 -*-
#
# Copyright (C) 2014 NDP Systèmes (<http://www.ndp-systemes.fr>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
import time

from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT, drop_view_if_exists
from openerp import fields, models, api, exceptions, _

class stock_picking_performance_improved(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def assign_moves_to_picking(self):
        """Assign prereserved moves that do not belong to a picking yet to a picking by reconfirming them.
        """
        prereservations = self.env['stock.prereservation'].search([('picking_id','=',False)])
        todo_moves = prereservations.mapped(lambda p: p.move_id)
        to_assign_moves = todo_moves.filtered(lambda m: m.state == 'assigned')
        todo_moves.action_confirm()
        # We reassign moves that were assigned beforehand because action_confirmed changed the state
        to_assign_moves.action_assign()

    @api.multi
    def action_assign(self):
        """Check availability of picking moves.

        This has the effect of changing the state and reserve quants on available moves, and may
        also impact the state of the picking as it is computed based on move's states.
        Overridden here to assign prereserved moves to pickings beforehand.
        :return: True
        """
        self.assign_moves_to_picking()
        return super(stock_picking_performance_improved, self).action_assign()

    @api.multi
    def rereserve_pick(self):
        """
        This can be used to provide a button that rereserves taking into account the existing pack operations
        Overridden here to assign prereserved moves to pickings beforehand
        """
        self.assign_moves_to_picking()
        super(stock_picking_performance_improved, self).rereserve_pick()


class stock_move(models.Model):
    _inherit = 'stock.move'

    @api.multi
    def _picking_assign(self, procurement_group, location_from, location_to):
        """Assigns these moves that share the same procurement.group, location_from and location_to to a stock picking.

        Overridden here to assign only if the move is prereserved.
        :param procurement_group: The procurement.group of the moves
        :param location_from: The source location of the moves
        :param location_to: The destination lcoation of the moves
        """
        prereservations = self.env['stock.prereservation'].search([('move_id','in',self.ids)])
        prereserved_moves = prereservations.mapped(lambda p: p.move_id)
        outgoing_moves = self.filtered(lambda m: m.picking_type_id.code == 'outgoing')
        todo_moves = outgoing_moves | prereserved_moves
        if todo_moves:
            return super(stock_move, todo_moves)._picking_assign(procurement_group, location_from, location_to)
        return True

    @api.multi
    def action_assign(self):
        """ Checks the product type and accordingly writes the state.
        Overridden here to also assign a picking if it is not done yet.
        """
        moves_no_pick = self.filtered(lambda m: m.picking_type_id and not m.picking_id)
        moves_no_pick.action_confirm()
        super(stock_move, self).action_assign()


class stock_prereservation(models.Model):
    _name = 'stock.prereservation'
    _description = "Stock Pre-Reservation"
    _auto = False

    id = fields.Integer(readonly=True)
    move_id = fields.Many2one('stock.move', readonly=True, index=True)
    picking_id = fields.Many2one('stock.picking', readonly=True, index=True)

    def init(self, cr):
        drop_view_if_exists(cr, "stock_prereservation")
        cr.execute("""
        create or replace view stock_prereservation as (
            with move_qties as (
                select
                    sm.id as move_id,
                    sm.picking_id,
                    sm.location_id,
                    sm.product_id,
                    sum(sm.product_qty) over (PARTITION BY sm.product_id, COALESCE(sm.picking_id, sm.location_id) ORDER BY priority DESC, date_expected) as qty
                from
                    stock_move sm
                where
                    sm.state = 'confirmed'
                    and sm.picking_type_id is not null
                    and sm.id not in (
                    select reservation_id from stock_quant where reservation_id is not null)
            )
            select
                row_number() over () as id,
                foo.move_id,
                foo.picking_id
            from (
                    select
                        sm.id as move_id,
                        sm.picking_id as picking_id
                    from
                        stock_move sm
                    where
                        sm.id in (
                            select sq.reservation_id from stock_quant sq where sq.reservation_id is not null)
                        and sm.picking_type_id is not null
                union
                    select distinct
                        sm.id as move_id,
                        sm.picking_id as picking_id
                    from
                        stock_move sm
                        left join stock_move smp on smp.move_dest_id = sm.id
                        left join stock_move sms on sm.split_from = sms.id
                        left join stock_move smps on smps.move_dest_id = sms.id
                    where
                        sm.state = 'waiting'
                        and sm.picking_type_id is not null
                        and smp.state = 'done' or smps.state = 'done'
                union
                    select
                        mq.move_id,
                        mq.picking_id
                    from
                        move_qties mq
                        where
                            mq.qty <= (
                                select
                                    sum(qty)
                                from
                                    stock_quant sq
                                where
                                    sq.reservation_id is null
                                    and sq.location_id = mq.location_id
                                    and sq.product_id = mq.product_id)
            ) foo
        )
        """)

