#ifndef APP_MAIN_H
#define APP_MAIN_H

#include "stm32f1xx_hal.h"

void App_Init(UART_HandleTypeDef *huart);
void App_Loop(void);

#endif
