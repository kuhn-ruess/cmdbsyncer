"""
Custom Export for Syncer Models
"""
import json

from flask import g, has_app_context


class ExportObjects:
    """
    Format Class for Syncer Objects
    too use with Tablib
    """
    title='Objects'


    @classmethod
    def export_set(cls, dset):
        """
        Returns string representation of given dataset, behind a line with
        the rule type if the view exports one. Some rule types have the same
        fields, only that line tells on import which type a file belongs to.
        """
        dset.headers = None
        rule_type = g.get('rule_export_type') if has_app_context() else None
        if rule_type:
            return json.dumps({'rule_type': rule_type}) + "\n" + str(dset)
        return str(dset)
