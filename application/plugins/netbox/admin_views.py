from application.modules.rule.views import FiltereModelView, RewriteAttributeView

from .views import (
                  NetboxCustomAttributesView,
                  NetboxDataFlowAttributesView,
                  NetboxDataFlowModelView,
              )
from .models import (
                 NetboxCustomAttributes,
                 NetboxRewriteAttributeRule,
                 NetboxIpamIpaddressattributes,
                 NetboxDcimInterfaceAttributes,
                 NetboxContactAttributes,
                 NetboxDataflowAttributes,
                 NetboxDataflowModels,
                 NetboxClusterAttributes,
                 NetboxVirtualMachineAttributes,
                 NetboxIpamPrefixAttributes,
                 NetboxVirtualizationInterfaceAttributes,
                 )


def register_admin_views(admin):
    """Register Flask-Admin views."""
    admin.add_sub_category(name="Netbox", parent_name="Modules")

    admin.add_view(RewriteAttributeView(NetboxRewriteAttributeRule, name="Rewrite Attributes",
                                                                category="Netbox",
                                                                menu_icon_type='fa',
                                                                menu_icon_value='fa-exchange'))

    admin.add_view(NetboxCustomAttributesView(NetboxCustomAttributes,\
            name="DCIM: Devices", category="Netbox",
            menu_icon_type='fa', menu_icon_value='fa-server'))
    admin.add_view(NetboxCustomAttributesView(NetboxDcimInterfaceAttributes,\
            name="DCIM: Interfaces", category="Netbox",
            menu_icon_type='fa', menu_icon_value='fa-plug'))
    admin.add_view(NetboxCustomAttributesView(NetboxIpamIpaddressattributes,\
            name="IPAM: IP Addresses", category="Netbox",
            menu_icon_type='fa', menu_icon_value='fa-hashtag'))
    admin.add_view(NetboxCustomAttributesView(NetboxIpamPrefixAttributes,\
            name="IPAM: Prefix", category="Netbox",
            menu_icon_type='fa', menu_icon_value='fa-sitemap'))
    admin.add_view(NetboxCustomAttributesView(NetboxClusterAttributes,\
            name="Virtualization: Cluster", category="Netbox",
            menu_icon_type='fa', menu_icon_value='fa-cube'))
    admin.add_view(NetboxCustomAttributesView(NetboxVirtualMachineAttributes,\
            name="Virtualization: Virtual Machines", category="Netbox",
            menu_icon_type='fa', menu_icon_value='fa-cubes'))
    admin.add_view(NetboxCustomAttributesView(NetboxVirtualizationInterfaceAttributes,\
            name="Virtualization: Interfaces", category="Netbox",
            menu_icon_type='fa', menu_icon_value='fa-link'))
    admin.add_view(NetboxCustomAttributesView(NetboxContactAttributes,\
            name="Tenancy: Contacts", category="Netbox",
            menu_icon_type='fa', menu_icon_value='fa-user'))

    admin.add_sub_category(name="Plugin: Dataflow", parent_name="Netbox")
    admin.add_view(NetboxDataFlowModelView(NetboxDataflowModels,\
            name="Model Defintion", category="Plugin: Dataflow",
            menu_icon_type='fa', menu_icon_value='fa-arrows'))

    admin.add_view(NetboxDataFlowAttributesView(NetboxDataflowAttributes,\
            name="Field Definition", category="Plugin: Dataflow",\
            menu_icon_type='fa', menu_icon_value='fa-list'))
