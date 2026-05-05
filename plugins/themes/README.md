# Custom themes

Drop a `.css` file into this directory and restart cmdbsyncer — the
filename (without `.css`) becomes the theme slug, and the new theme
appears in the picker under **Account → Theme**.

## Format

A theme file is plain CSS. The first job is to set the navbar
custom properties on `:root`; everything else is up to you.

```css
/* @name: My Theme */
:root {
    --nav-bg: #112233;
    --nav-link: #eeeeee;
}
body { background-color: #112233; color: #eeeeee; }
/* ...overrides for tables, cards, dropdowns, forms, modals... */
```

The optional `/* @name: ... */` header sets the human label shown in
the picker. Without it the slug is title-cased (`solarized-dark` →
"Solarized Dark").

## Conflicts

Shipped themes (under `application/themes/`) win on slug collision.
Pick a different filename if you want to override a built-in look.

## Reference

The shipped themes (`gruvbox-dark.css`, `gruvbox-light.css`,
`nord.css`) are the most complete templates to copy from — they cover
every Bootstrap component the admin UI uses (tables, dropdowns,
modals, pagination, filter chips, the changelog widget, etc.).
