# Export Rules
Export Rules manage how hosts will export to Checkmk. So, you can control in which Folder they will import and which attribute they will have. Note that the best way for folders is, to extract them from your Attributes.  Rules how define Folders, are automatically stacked and result in a folder structure like /this/is/my/folder out of all the outcomes.  It makes no difference if just one rule defines multiple outcomes, or multiple rule just define one outcome. At the End, it's just a long list of outcomes in the Order given by the Sort Field. It's recommended to make use of the last_match Option in Rules, to create the wanted Folder Paths. 

::: application.modules.checkmk.models.CheckmkRuleOutcome
    options:
      show_source: false
