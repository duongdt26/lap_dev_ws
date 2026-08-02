/**
 * board_gpio.h — GPIO mapping AMR conveyor board
 *
 * PA0-PA5: cam bien INPUT_PULLUP, active LOW
 * PB4-PB9: nut INPUT_PULLUP, active LOW
 * PA11/PA12/PA15/PB3: relay ON=SET, OFF=RESET
 * PB12-PB15: audio bit
 * PA9/PA10: UART1 @ 256000
 */
#ifndef BOARD_GPIO_H
#define BOARD_GPIO_H

#include "stm32f1xx_hal.h"

/* Relay */
#define RELAY_ON   GPIO_PIN_SET
#define RELAY_OFF  GPIO_PIN_RESET

/* Cam bien PA0-PA5, active LOW = co vat */
#define SENSOR_PORT       GPIOA
#define S1_PIN            GPIO_PIN_0   /* PA0 */
#define S2_PIN            GPIO_PIN_1   /* PA1 */
#define S3_PIN            GPIO_PIN_2   /* PA2 */
#define S4_PIN            GPIO_PIN_3   /* PA3 */
#define S5_PIN            GPIO_PIN_4   /* PA4 du phong */
#define S6_PIN            GPIO_PIN_5   /* PA5 du phong */

/* Nut PB4-PB9, INPUT_PULLUP, active LOW */
#define BTN_EMER_PORT     GPIOB
#define BTN_EMER_PIN      GPIO_PIN_9
#define BTN_STOP_PORT     GPIOB
#define BTN_STOP_PIN      GPIO_PIN_8
#define BTN_START_PORT    GPIOB
#define BTN_START_PIN     GPIO_PIN_6
#define BTN_RESET_PORT    GPIOB
#define BTN_RESET_PIN     GPIO_PIN_7
#define BUMPER1_PORT      GPIOB
#define BUMPER1_PIN       GPIO_PIN_5
#define BUMPER2_PORT      GPIOB
#define BUMPER2_PIN       GPIO_PIN_4

#define SENSOR_ACTIVE     GPIO_PIN_RESET
#define BTN_EMER_ACTIVE   GPIO_PIN_RESET
#define BUMPER_ACTIVE     GPIO_PIN_RESET
#define BTN_CTRL_ACTIVE   GPIO_PIN_RESET

/* Relay motor */
#define M1_R1_PORT        GPIOA
#define M1_R1_PIN         GPIO_PIN_11  /* Motor 1: S1 -> S3 */
#define M1_R2_PORT        GPIOA
#define M1_R2_PIN         GPIO_PIN_12  /* Motor 1: S3 -> S1 */
#define M2_R3_PORT        GPIOA
#define M2_R3_PIN         GPIO_PIN_15  /* Motor 2: S4 -> S2 */
#define M2_R4_PORT        GPIOB
#define M2_R4_PIN         GPIO_PIN_3   /* Motor 2: S2 -> S4 */

/* Loa PB12-PB15 */
#define AUDIO_PORT        GPIOB
#define AUDIO_B4_PIN      GPIO_PIN_12
#define AUDIO_B3_PIN      GPIO_PIN_13
#define AUDIO_B2_PIN      GPIO_PIN_14
#define AUDIO_B1_PIN      GPIO_PIN_15
#define AUDIO_ALL_PINS    (AUDIO_B4_PIN | AUDIO_B3_PIN | AUDIO_B2_PIN | AUDIO_B1_PIN)

#define UART_BAUDRATE     256000U

typedef enum {
  BELT_DIR_LEFT = 0,
  BELT_DIR_RIGHT = 1
} BeltDirection_t;

typedef enum {
  BELT_SIDE_LEFT = 0,
  BELT_SIDE_RIGHT = 1
} BeltSide_t;

typedef enum {
  SYS_BOOT = 0,
  SYS_IDLE,
  SYS_RUNNING,
  SYS_ESTOP
} SystemState_t;

uint8_t Board_SensorActive(uint16_t pin);
uint8_t Board_S1(void);
uint8_t Board_S2(void);
uint8_t Board_S3(void);
uint8_t Board_S4(void);
uint8_t Board_S5(void);
uint8_t Board_S6(void);

void Board_M1_Set(uint8_t r1, uint8_t r2);
void Board_M2_Set(uint8_t r3, uint8_t r4);
void Board_RelayAllOff(void);

void Board_BeltRun(uint8_t belt_id, BeltDirection_t dir);
void Board_BeltStop(uint8_t belt_id);
void Board_BeltHold(uint8_t belt_id);

#endif /* BOARD_GPIO_H */