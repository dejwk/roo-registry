#include "roo_rtc/ds3231.h"
#include "roo_rtc/ds3234.h"
#include "roo_testing/devices/clock/ds3231/ds3231.h"
#include "roo_testing/devices/clock/ds3234/ds3234.h"
#include "roo_testing/microcontrollers/rp2040/fake_pico.h"
#include "gtest/gtest.h"

#if !defined(ARDUINO)
#include <hardware/gpio.h>
#include <hardware/i2c.h>
#include <hardware/spi.h>
#endif

namespace {
struct Wiring {
  Wiring() {
    FakePico().attachI2cDevice(i2c, 4, 5);
    FakePico().attachSpiDevice(spi, 18, 16, 19);
    FakePico().attachOutput(17, spi.cs());
  }
  roo_testing_transducers::FakeClock oscillator;
  FakeDs3231 i2c{oscillator};
  FakeDs3234 spi{&oscillator};
} wiring;

// Verifies real downstream I2C/SPI clock drivers use the selected Pico backend
// for calendar writes, oscillator advancement and hardware time-loss recovery.
TEST(PicoIoConsumers, CalendarDrivers) {
#if defined(ARDUINO)
  Wire.begin();
  SPI.begin();
  roo_io::I2cMasterBusHandle i2c(Wire);
  roo_io::SpiMasterBusHandle spi(SPI);
#else
  i2c_init(i2c0, 400000);
  gpio_set_function(4, GPIO_FUNC_I2C);
  gpio_set_function(5, GPIO_FUNC_I2C);
  spi_init(spi0, 1000000);
  for (int pin : {18, 16, 19})
    gpio_set_function(pin, GPIO_FUNC_SPI);
  roo_io::I2cMasterBusHandle i2c(i2c0);
  roo_io::SpiMasterBusHandle spi(spi0);
#endif
  roo_rtc::Ds3231Clock i2c_clock(i2c);
  roo_rtc::Ds3234Clock spi_clock(spi, 17);
  ASSERT_TRUE(i2c_clock.init());
  ASSERT_TRUE(spi_clock.init());
  const roo_time::WallTime start =
      roo_time::DateTime(2024, 2, 28, 23, 59, 59, 0, roo_time::timezone::UTC)
          .wallTime();
  ASSERT_TRUE(i2c_clock.set(start));
  ASSERT_TRUE(spi_clock.set(start));
  wiring.oscillator.delayMicros(2000000);
  EXPECT_EQ(i2c_clock.read().time, start + roo_time::Seconds(2));
  EXPECT_EQ(spi_clock.read().time, start + roo_time::Seconds(2));
  wiring.i2c.simulateTimeLoss();
  wiring.spi.simulateTimeLoss();
  EXPECT_EQ(i2c_clock.read().status, roo_rtc::ReadStatus::kTimeLost);
  EXPECT_EQ(spi_clock.read().status, roo_rtc::ReadStatus::kTimeLost);
#if defined(ARDUINO)
  Wire.end();
  SPI.end();
#else
  i2c_deinit(i2c0);
  spi_deinit(spi0);
#endif
}
} // namespace
