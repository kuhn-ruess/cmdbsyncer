"""
Alle Stuff shared by the plugins
"""
#pylint: disable=too-few-public-methods

from application import app, logger
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
    account = False


    def init_custom_attributes(self):
        """
        Load Rules for custom Attributes
        """
        self.custom_attributes = CustomAttributeRule()
        self.custom_attributes.debug = self.debug
        self.custom_attributes.rules = \
                        CustomAttributeRuleModel.objects(enabled=True).order_by('sort_field')

    def get_host_attributes(self, db_host, cache):
        """
        Return Host Attributes or False if Host should be ignored
        """
        # Get Attributes
        db_host.cache.setdefault(cache, {})
        if 'attributes' in db_host.cache[cache]:
            logger.debug(f"Using Cache for {db_host.hostname}")
            if 'ignore_host' in db_host.cache[cache]['attributes']['filtered']:
                return False
            return db_host.cache[cache]['attributes']
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
        data = {
            'all': attributes,
            'filtered': attributes_filtered,
        }

        if self.filter:
            attributes_filtered = self.filter.get_outcomes(db_host, attributes)
            data['filtered'] = attributes_filtered
            if attributes_filtered.get('ignore_host'):
                db_host.cache[cache]['attributes'] = data
                db_host.save()
                return False

        db_host.cache[cache]['attributes'] = data
        db_host.save()
        return data
