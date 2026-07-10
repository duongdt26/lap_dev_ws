#include "board_gpio.h"

/*
   NOTE AN TOAN:
   - Board_BeltHold() duoc doi thanh Stop(), khong bat dong thoi 2 relay dao chieu.
   - Neu mach cong suat cua ban co chan brake rieng, hay them brake rieng thay vi bat ca 2 relay.
*/

uint8_t Board_SensorActive(uint16_t pin)
{
  return (HAL_GPIO_ReadPin(SENSOR_PORT, pin) == SENSOR_ACTIVE) ? 1U : 0U;
}

uint8_t Board_S1(void) { return Board_SensorActive(S1_PIN); }
uint8_t Board_S2(void) { return Board_SensorActive(S2_PIN); }
uint8_t Board_S3(void) { return Board_SensorActive(S3_PIN); }
uint8_t Board_S4(void) { return Board_SensorActive(S4_PIN); }
uint8_t Board_S5(void) { return Board_SensorActive(S5_PIN); }
uint8_t Board_S6(void) { return Board_SensorActive(S6_PIN); }

void Board_M1_Set(uint8_t r1, uint8_t r2)
{
  HAL_GPIO_WritePin(M1_R1_PORT, M1_R1_PIN, r1 ? RELAY_ON : RELAY_OFF);
  HAL_GPIO_WritePin(M1_R2_PORT, M1_R2_PIN, r2 ? RELAY_ON : RELAY_OFF);
}

void Board_M2_Set(uint8_t r3, uint8_t r4)
{
  HAL_GPIO_WritePin(M2_R3_PORT, M2_R3_PIN, r3 ? RELAY_ON : RELAY_OFF);
  HAL_GPIO_WritePin(M2_R4_PORT, M2_R4_PIN, r4 ? RELAY_ON : RELAY_OFF);
}

void Board_RelayAllOff(void)
{
  Board_M1_Set(0U, 0U);
  Board_M2_Set(0U, 0U);
}

void Board_BeltRun(uint8_t belt_id, BeltDirection_t dir)
{
  /*
     Khi doi chieu, FSM luon goi Board_BeltStop() truoc khi goi ham nay.
     Neu relay/motor can dead-time dai hon, thuc hien bang timer trong FSM.
  */
  if (belt_id == 1U) {
    if (dir == BELT_DIR_LEFT) {
      Board_M1_Set(1U, 0U);   /* Belt 1: S1 -> S3 */
    } else {
      Board_M1_Set(0U, 1U);   /* Belt 1: S3 -> S1 */
    }
  } else if (belt_id == 2U) {
    if (dir == BELT_DIR_LEFT) {
      Board_M2_Set(0U, 1U);   /* Belt 2: S2 -> S4 */
    } else {
      Board_M2_Set(1U, 0U);   /* Belt 2: S4 -> S2 */
    }
  }
}

void Board_BeltStop(uint8_t belt_id)
{
  if (belt_id == 1U) {
    Board_M1_Set(0U, 0U);
  } else if (belt_id == 2U) {
    Board_M2_Set(0U, 0U);
  } else {
    Board_RelayAllOff();
  }
}

void Board_BeltHold(uint8_t belt_id)
{
  /* Safe hold = stop relay. Khong bat ca 2 relay dao chieu cung luc. */
  Board_BeltStop(belt_id);
}
