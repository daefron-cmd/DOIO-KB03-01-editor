ENCODER_MAP_ENABLE = yes

# Keep VIA on so usevia.app can remap keys/layers/macros at runtime.
# VIA stores encoder bindings dynamically. The boot hook reserves only
# the outer ring; keys and inner-encoder remaps persist across boots.
VIA_ENABLE = yes

# MX-Master scroll support
SRC += inertia.c
RAW_ENABLE = yes
