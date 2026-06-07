from ui import calibrated_led_color


def test_calibrated_led_color_uses_photo_sample_points():
    assert calibrated_led_color(0, 255, 200).name() == "#ff2a11"
    assert calibrated_led_color(255, 255, 200).name() == "#ff2a11"


def test_calibrated_led_color_mirrors_device_hue_direction():
    assert calibrated_led_color(64, 255, 200).name() == "#9ce33e"
    assert calibrated_led_color(192, 255, 200).name() == "#632dff"
    assert calibrated_led_color(128, 255, 200).name() == "#00d9e6"
    assert calibrated_led_color(255, 255, 200).name() == "#ff2a11"


def test_calibrated_led_color_scales_brightness_and_saturation():
    full = calibrated_led_color(0, 255, 200)
    dim = calibrated_led_color(0, 255, 100)
    desat = calibrated_led_color(0, 0, 200)
    assert dim.red() < full.red()
    assert desat.red() == 255
    assert desat.green() > full.green()
