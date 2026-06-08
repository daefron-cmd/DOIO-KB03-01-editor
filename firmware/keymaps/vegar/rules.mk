ENCODER_MAP_ENABLE = yes

# Keep VIA on so usevia.app can remap keys/layers/macros at runtime.
# (Note: with ENCODER_MAP_ENABLE the encoder bindings are compile-time
# and not VIA-runtime-configurable — that is the trade-off for being
# able to set the wheel tuning constants in config.h.)
VIA_ENABLE = yes

# MX-Master scroll support
SRC += inertia.c
RAW_ENABLE = yes
