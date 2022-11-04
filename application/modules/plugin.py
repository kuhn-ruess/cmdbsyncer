"""
Alle Stuff shared by the plugins
"""
#pylint: disable=too-few-public-methods


class Plugin():
    """
    Base Class for all Plugins
    """
    rewrite = False
    filter = False

    def get_host_attributes(self, db_host):
        """
        Return Host Attributes or False if Host should be ignored
        """
        # Get Attributes
        attributes = {}
        attributes.update(db_host.labels)
        attributes.update(db_host.inventory)

        attributes_filtered = {}

        if self.rewrite:
            for rewrite, value in self.rewrite.get_outcomes(db_host, attributes).items():
                realname = rewrite[4:]
                if rewrite.startswith('add_'):
                    attributes[realname] = value
                elif rewrite.startswith('del_'):
                    del attributes[realname]
        if self.filter:
            attributes_filtered = self.filter.get_outcomes(db_host, attributes)
            if attributes_filtered.get('ignore_host'):
                return False

        return {
            'all': attributes,
            'filtered': attributes_filtered,
        }
