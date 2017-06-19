/**
 * Created by apasquier on 23/05/17.
 */
openerp.odoo_utils = function(instance) {

    instance.web.FormView.include({
        on_processed_onchange: function(result) {
            console.log(result);
            if (result['action']){
                this.do_action(result['action']);
            }
            return this._super(result);
        }
    })
};

