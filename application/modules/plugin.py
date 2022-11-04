"""
Alle Stuff shared by the plugins
"""
#pylint: disable=too-few-public-methods


from application.modules.custom_attributes.models import CustomAttributeRule as CustomAttributeRuleModel
from application.modules.custom_attributes.rules import CustomAttributeRule



class Plugin():
    """
    Base Class for all Plugins
    """
    rewrite = False
    filter = False
    custom_attributes = False
    debug = False


    def init_custom_attributes(self):
        """
        Load Rules for custom Attributes
        """
        self.custom_attributes = CustomAttributeRule()
        self.custom_attributes.debug = self.debug
        self.custom_attributes.rules = \
                        CustomAttributeRuleModel.objects(enabled=True).order_by('sort_field')

    def get_host_attributes(self, db_host):
        """
        Return Host Attributes or False if Host should be ignored
        """
        # Get Attributes
        attributes = {}
        attributes.update(db_host.labels)
        attributes.update(db_host.inventory)

        self.init_custom_attributes()
        attributes.update(self.custom_attributes.get_outcomes(db_host, attributes))

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
