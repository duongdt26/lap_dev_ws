#ifndef INPUT_FILTER_H
#define INPUT_FILTER_H

#include "stm32f1xx_hal.h"

#define INPUT_DEBOUNCE_MS  50U

typedef struct {
  GPIO_PinState raw_last;
  GPIO_PinState stable;
  uint32_t last_change_tick;
  uint8_t active_event;
} InputFilter_t;

void InputFilter_Init(InputFilter_t *f, GPIO_PinState raw);
void InputFilter_Update(InputFilter_t *f, GPIO_PinState raw, GPIO_PinState active_level);
uint8_t InputFilter_IsActive(const InputFilter_t *f, GPIO_PinState active_level);

#endif
