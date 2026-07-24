/**
 * board_gpio.h — GPIO mapping AMR conveyor board
 *
 * PA0-PA3: cam bien INPUT_PULLUP, active LOW
 * PB4-PB9: nut INPUT_PULLUP, active LOW
 * PA11/PA12/PA15/PB3: relay ON=SET, OFF=RESET
 * PB12-PB15: audio bit
 * PA9/PA10: UART1 @ 256000
 */
#ifndef BOARD_GPIO_H
#define BOARD_GPIO_H

#include "main.h"

/* Relay */
#define RELAY_ON   GPIO_PIN_SET
#define RELAY_OFF  GPIO_PIN_RESET

/* Cam bien PA0-PA3, active LOW = co vat */
#define SENSOR_PORT       S1_GPIO_Port
#define S1_PIN            S1_Pin
#define S2_PIN            S2_Pin
#define S3_PIN            S3_Pin
#define S4_PIN            S4_Pin

/* Nut PB4-PB9, INPUT_PULLUP, active LOW */
#define BTN_EMER_PORT     Button_EMER_GPIO_Port
#define BTN_EMER_PIN      Button_EMER_Pin
#define BTN_STOP_PORT     Button_STOP_GPIO_Port
#define BTN_STOP_PIN      Button_STOP_Pin
#define BTN_RESET_PORT    Button_RESET_GPIO_Port
#define BTN_RESET_PIN     Button_RESET_Pin
#define BTN_START_PORT    Button_START_GPIO_Port
#define BTN_START_PIN     Button_START_Pin
#define BUMPER1_PORT      Bumper_S1_GPIO_Port
#define BUMPER1_PIN       Bumper_S1_Pin
#define BUMPER2_PORT      Bumper_S2_GPIO_Port
#define BUMPER2_PIN       Bumper_S2_Pin

#define SENSOR_ACTIVE     GPIO_PIN_RESET
#define BTN_EMER_ACTIVE   GPIO_PIN_RESET
#define BUMPER_ACTIVE     GPIO_PIN_RESET
#define BTN_CTRL_ACTIVE   GPIO_PIN_RESET

/* Relay motor */
#define M1_R1_PORT        RUN1_GPIO_Port
#define M1_R1_PIN         RUN1_Pin  /* Motor 1: S1 -> S3 */
#define M1_R2_PORT        RF1_GPIO_Port
#define M1_R2_PIN         RF1_Pin   /* Motor 1: S3 -> S1 */
#define M2_R3_PORT        RUN2_GPIO_Port
#define M2_R3_PIN         RUN2_Pin  /* Motor 2: S4 -> S2 */
#define M2_R4_PORT        RF2_GPIO_Port
#define M2_R4_PIN         RF2_Pin   /* Motor 2: S2 -> S4 */

/* Loa PB12-PB15 */
#define AUDIO_PORT        N1_GPIO_Port
#define AUDIO_N1_PIN      N1_Pin
#define AUDIO_N2_PIN      N2_Pin
#define AUDIO_N3_PIN      N3_Pin
#define AUDIO_N4_PIN      N4_Pin
#define AUDIO_ALL_PINS    (AUDIO_N1_PIN | AUDIO_N2_PIN | AUDIO_N3_PIN | AUDIO_N4_PIN)

typedef enum {
  BELT_DIR_LEFT = 0,
  BELT_DIR_RIGHT = 1
} BeltDirection_t;

typedef enum {
  BELT_SIDE_LEFT = 0,
  BELT_SIDE_RIGHT = 1
} BeltSide_t;

typedef enum {
  SYS_IDLE = 0,
  SYS_RUNNING,
  SYS_ESTOP
} SystemState_t;

void Board_SensorsInit(void);
void Board_SensorsUpdate(void);
uint8_t Board_S1(void);
uint8_t Board_S2(void);
uint8_t Board_S3(void);
uint8_t Board_S4(void);

void Board_RelayAllOff(void);

void Board_BeltRun(uint8_t belt_id, BeltDirection_t dir);
void Board_BeltStop(uint8_t belt_id);
void Board_BeltHold(uint8_t belt_id);

#endif /* BOARD_GPIO_H */
