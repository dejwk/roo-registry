load("@rules_cc//cc:cc_test.bzl", "cc_test")

cc_test(
    name = "rtc_consumer_test",
    size = "small",
    srcs = ["rtc_consumer_test.cpp"],
    copts = [
        "-fno-exceptions",
        "-fno-rtti",
    ],
    target_compatible_with = ["@roo_testing//roo_testing/platforms:rp2040"],
    deps = [
        "@roo_rtc//:ds3231",
        "@roo_rtc//:ds3234",
        "@roo_testing//roo_testing/devices/clock/ds3231",
        "@roo_testing//roo_testing/devices/clock/ds3234",
        "@roo_testing//roo_testing/microcontrollers/rp2040:pico",
        "@roo_time",
    ] + select({
        "@roo_testing//roo_testing/platforms:is_arduino": ["@roo_testing//:arduino_gtest_main"],
        "//conditions:default": ["@roo_testing//:pico_gtest_main"],
    }),
)
