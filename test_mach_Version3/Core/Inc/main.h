/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c — AMR conveyor board
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32f1xx_hal.h"

void Error_Handler(void);

/* ── Cảm biến PA0-PA3 ── */
#define S1_Pin        GPIO_PIN_0
#define S1_GPIO_Port  GPIOA
#define S2_Pin        GPIO_PIN_1
#define S2_GPIO_Port  GPIOA
#define S3_Pin        GPIO_PIN_2
#define S3_GPIO_Port  GPIOA
#define S4_Pin        GPIO_PIN_3
#define S4_GPIO_Port  GPIOA
/* ── Relay motor PA11/PA12/PA15 ── */
#define RUN1_Pin      GPIO_PIN_11   /* Belt1 trái  (FWD) */
#define RUN1_GPIO_Port GPIOA
#define RF1_Pin       GPIO_PIN_12   /* Belt1 phải (REV) */
#define RF1_GPIO_Port GPIOA
#define RUN2_Pin      GPIO_PIN_15   /* Belt2 phải (REV) */
#define RUN2_GPIO_Port GPIOA

/* ── Relay + audio PB3/PB12-PB15 ── */
#define RF2_Pin       GPIO_PIN_3    /* Belt2 trái (FWD) */
#define RF2_GPIO_Port GPIOB
#define N1_Pin        GPIO_PIN_15   /* Audio bit 0x01 */
#define N1_GPIO_Port  GPIOB
#define N2_Pin        GPIO_PIN_14   /* Audio bit 0x02 */
#define N2_GPIO_Port  GPIOB
#define N3_Pin        GPIO_PIN_13   /* Audio bit 0x04 */
#define N3_GPIO_Port  GPIOB
#define N4_Pin        GPIO_PIN_12   /* Audio bit 0x08 */
#define N4_GPIO_Port  GPIOB

/* ── Nút / bumper PB4-PB9 ── */
#define Button_EMER_Pin       GPIO_PIN_4
#define Button_EMER_GPIO_Port GPIOB
#define Button_STOP_Pin       GPIO_PIN_5
#define Button_STOP_GPIO_Port GPIOB
#define Button_RESET_Pin      GPIO_PIN_6
#define Button_RESET_GPIO_Port GPIOB
#define Button_START_Pin      GPIO_PIN_7
#define Button_START_GPIO_Port GPIOB
#define Bumper_S1_Pin         GPIO_PIN_8
#define Bumper_S1_GPIO_Port   GPIOB
#define Bumper_S2_Pin         GPIO_PIN_9
#define Bumper_S2_GPIO_Port   GPIOB

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
