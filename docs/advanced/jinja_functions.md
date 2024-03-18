# Custom Jinja Functions the Syncer offers



## merge_list_of_dicts()
If you have, for example in your Attributes, a List of Dictionaries like this:

```
location = [{"site":""},{"section":""},{"level":""},{"room":""},{"description":""},{"note":""}]
```


Then you can use this Jinja Syntax to pick given values in the rewrite

```
{{ merge_list_of_dicts(location)['room'] }}
```


## get_list()
This helper converts a Attribute List of given List into a Python list, which is used in some of the Syncers functions. See [Hostags](../checkmk/create_hosttags.md) for example.


## cmk_cleanup_tag_id()
Cleans a String so that it can serve as Checkmk Hosttag ID. Invalid Chars are replaced by underscore.







