# Context of the print layouts

- `locator_context.gpkg`, layer `countries`: Natural Earth 1:10 million admin 0 countries (public domain), clipped to 90-145 E,
  15 S-12 N and simplified (0.005 degree) for the locator inset.
- `locator_context.gpkg`, layer `provinces_idn`: geoBoundaries gbOpen IDN ADM1 (simplified further, 0.003 degree), 34 provinces as of 2017, from
  OpenStreetMap; Open Data Commons Open Database License 1.0. Credit on the map: "© OpenStreetMap contributors, geoBoundaries".
  `name_id` holds the Indonesian province name.
- `klh_bplh_logo_ring_commons.png`, `klh_bplh_logo_kemenlh.png`: the KLH/BPLH emblem, with and without the ring text. The first is
  from Wikimedia Commons (tagged CC0 by its uploader, cropped from a third-party file), the second from the header of kemenlh.go.id.
  Use of the emblem is the ministry's to grant; it is here for the ministry's own maps.

Rebuilt from `_data` written by `python -m repeat_common.fetch_map_context` (repeat-common); the plugin copy keeps only the two layers
above, countries simplified.
