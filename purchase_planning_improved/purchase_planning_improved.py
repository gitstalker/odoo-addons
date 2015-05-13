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

from datetime import datetime

from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT, DEFAULT_SERVER_DATE_FORMAT
from openerp import fields, models, api


class procurement_order_purchase_planning_improved(models.Model):
    _inherit = 'procurement.order'

    @api.multi
    def action_reschedule(self):
        """Reschedules the moves associated to this procurement."""
        for proc in self:
            if proc.state not in ['done', 'cancel'] and proc.rule_id and proc.rule_id.action == 'buy':
                schedule_date = self._get_purchase_schedule_date(proc, proc.company_id)
                order_date = self._get_purchase_order_date(proc, proc.company_id, schedule_date)
                date_planned = proc.purchase_line_id.date_planned
                if proc.purchase_id.state in ['draft','sent','bid']:
                    # If the purchase line is not confirmed yet, try to set planned date to schedule_date
                    if order_date > datetime.now():
                        date_planned = schedule_date.strftime(DEFAULT_SERVER_DATE_FORMAT)
                proc.purchase_line_id.write({
                    'date_planned': date_planned,
                })
                if datetime.strptime(proc.purchase_id.date_order, DEFAULT_SERVER_DATETIME_FORMAT) > order_date:
                    proc.purchase_id.date_order = order_date.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        super(procurement_order_purchase_planning_improved, self).action_reschedule()


class purchase_order_line_planning_improved(models.Model):
    _inherit = 'purchase.order.line'

    date_required = fields.Date("Required Date", compute="_compute_date_required", store=True,
                                help="Required date for this purchase line. If this line was generated by a "
                                     "procurement, then this date is the date of the procurement.")

    @api.multi
    @api.depends('procurement_ids','procurement_ids.date_planned','date_required')
    def _compute_date_required(self):
        for rec in self:
            if rec.procurement_ids:
                min_date = fields.Datetime.from_string(min([p.date_planned for p in rec.procurement_ids]))
                min_proc = rec.procurement_ids.filtered(lambda p: str(p.date_planned) == str(min_date))[0]
                if min_proc.rule_id:
                    date_required = self.env['procurement.order']._get_purchase_schedule_date(min_proc, rec.company_id)
                else:
                    date_required = min_date
            else:
                date_required = rec.date_planned
            rec.date_required = date_required

    @api.multi
    def write(self, vals):
        """write method overridden here to propagate date_planned to the stock_moves of the receipt."""
        result = super(purchase_order_line_planning_improved, self).write(vals)
        if vals.get('date_planned'):
            for line in self:
                if line.move_ids:
                    date_expected = vals.get('date_planned')+" 00:00:00"
                    line.move_ids.write({'date_expected': date_expected})
        return result