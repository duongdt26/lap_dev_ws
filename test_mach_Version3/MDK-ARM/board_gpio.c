#include "board_gpio.h"
#include "input_filter.h"

static InputFilter_t s_sensor_filter[4];

static GPIO_PinState sensor_raw(uint16_t pin)
{
  return HAL_GPIO_ReadPin(SENSOR_PORT, pin);
}

void Board_SensorsInit(void)
{
  InputFilter_Init(&s_sensor_filter[0], sensor_raw(S1_PIN));
  InputFilter_Init(&s_sensor_filter[1], sensor_raw(S2_PIN));
  InputFilter_Init(&s_sensor_filter[2], sensor_raw(S3_PIN));
  InputFilter_Init(&s_sensor_filter[3], sensor_raw(S4_PIN));
}

void Board_SensorsUpdate(void)
{
  InputFilter_Update(&s_sensor_filter[0], sensor_raw(S1_PIN), SENSOR_ACTIVE);
  InputFilter_Update(&s_sensor_filter[1], sensor_raw(S2_PIN), SENSOR_ACTIVE);
  InputFilter_Update(&s_sensor_filter[2], sensor_raw(S3_PIN), SENSOR_ACTIVE);
  InputFilter_Update(&s_sensor_filter[3], sensor_raw(S4_PIN), SENSOR_ACTIVE);
}

static uint8_t sensor_active(uint16_t pin)
{
  switch (pin) {
  case S1_PIN: return InputFilter_IsActive(&s_sensor_filter[0], SENSOR_ACTIVE);
  case S2_PIN: return InputFilter_IsActive(&s_sensor_filter[1], SENSOR_ACTIVE);
  case S3_PIN: return InputFilter_IsActive(&s_sensor_filter[2], SENSOR_ACTIVE);
  case S4_PIN: return InputFilter_IsActive(&s_sensor_filter[3], SENSOR_ACTIVE);
  default:     return 0U;
  }
}

uint8_t Board_S1(void) { return sensor_active(S1_PIN); }
uint8_t Board_S2(void) { return sensor_active(S2_PIN); }
uint8_t Board_S3(void) { return sensor_active(S3_PIN); }
uint8_t Board_S4(void) { return sensor_active(S4_PIN); }

static void set_motor_1(uint8_t r1, uint8_t r2)
{
  HAL_GPIO_WritePin(M1_R1_PORT, M1_R1_PIN, r1 ? RELAY_ON : RELAY_OFF);
  HAL_GPIO_WritePin(M1_R2_PORT, M1_R2_PIN, r2 ? RELAY_ON : RELAY_OFF);
}

static void set_motor_2(uint8_t r3, uint8_t r4)
{
  HAL_GPIO_WritePin(M2_R3_PORT, M2_R3_PIN, r3 ? RELAY_ON : RELAY_OFF);
  HAL_GPIO_WritePin(M2_R4_PORT, M2_R4_PIN, r4 ? RELAY_ON : RELAY_OFF);
}

void Board_RelayAllOff(void)
{
  set_motor_1(0, 0);
  set_motor_2(0, 0);
}

void Board_BeltRun(uint8_t belt_id, BeltDirection_t dir)
{
  if (belt_id == 1U) {
    if (dir == BELT_DIR_LEFT) {
      set_motor_1(1, 0);   /* PA11 ON — trái / FWD */
    } else {
      set_motor_1(0, 1);   /* PA12 ON — phải / REV */
    }
  } else if (belt_id == 2U) {
    if (dir == BELT_DIR_LEFT) {
      set_motor_2(0, 1);   /* PB3 ON — trái / FWD */
    } else {
      set_motor_2(1, 0);   /* PA15 ON — phải / REV */
    }
  }
}

void Board_BeltStop(uint8_t belt_id)
{
  if (belt_id == 1U) {
    set_motor_1(0, 0);
  } else if (belt_id == 2U) {
    set_motor_2(0, 0);
  } else {
    Board_RelayAllOff();
  }
}

void Board_BeltHold(uint8_t belt_id)
{
  if (belt_id == 1U) {
    set_motor_1(1, 1);
  } else if (belt_id == 2U) {
    set_motor_2(1, 1);
  }
}
