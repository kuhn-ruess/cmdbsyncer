# Module icons

Small square marks shown next to the module entries in the "Modules" menu
and on each module's Overview page.

These are **not** the vendors' logos. Logos and names of Checkmk, Red
Hat/Ansible, NetBox, i-doit, Atlassian/Jira and Broadcom/VMware are trademarks
of their respective owners; no vendor logo is bundled here, only a mark drawn
for this project.

Both halves of each mark are deliberately unrelated to the vendor: the glyph
shows what the module does (a gauge for monitoring, a rack, a database, a
cube) instead of quoting the vendor's symbol, and the colour comes from this
project's own palette — no module carries the colour its vendor brands with.
The palette is picked so the six stay distinguishable at menu size and keep a
readable contrast against the white glyph in every theme.

If your installation is allowed to display the real logos (for example
because you run the product and your licence or the vendor's brand
guidelines permit it), just drop the official SVG in here under the same
file name — the menu and the overview pages pick it up with no code change.

The mapping file name → module lives in ``application/module_registry.py``.
