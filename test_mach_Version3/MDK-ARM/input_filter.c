#include "input_filter.h"

void InputFilter_Init(InputFilter_t *f, GPIO_PinState raw)
{
  f->raw_last = raw;
  f->stable = raw;
  f->last_change_tick = HAL_GetTick();
  f->active_event = 0;
}

void InputFilter_Update(InputFilter_t *f, GPIO_PinState raw, GPIO_PinState active_level)
{
  f->active_event = 0;

  if (raw != f->raw_last) {
    f->raw_last = raw;
    f->last_change_tick = HAL_GetTick();
  }

  if ((HAL_GetTick() - f->last_change_tick) >= INPUT_DEBOUNCE_MS) {
    if (f->stable != f->raw_last) {
      GPIO_PinState old = f->stable;
      f->stable = f->raw_last;
      if (old != active_level && f->stable == active_level) {
        f->active_event = 1;
      }
    }
  }
}

uint8_t InputFilter_IsActive(const InputFilter_t *f, GPIO_PinState active_level)
{
  return (f->stable == active_level) ? 1U : 0U;
}
