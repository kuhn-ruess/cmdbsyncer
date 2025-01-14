"""
Custom Export for Syncer Models
"""
class ExportObjects:
    """
    Format Class for Syncer Objects
    too use with Tablib
    """
    title='Objects'


    @classmethod
    def export_set(cls, dset):
        """returns string representation of given dataset"""
        dset.headers = None
        return str(dset)
