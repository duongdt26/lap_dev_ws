#include "audio_board.h"
#include "board_gpio.h"

static uint8_t s_audio_busy = 0;
static uint32_t s_audio_tick = 0;

void Audio_Clear(void)
{
  HAL_GPIO_WritePin(AUDIO_PORT, AUDIO_ALL_PINS, GPIO_PIN_RESET);
}

void Audio_SendHex(uint8_t code)
{
  HAL_GPIO_WritePin(AUDIO_PORT, AUDIO_B4_PIN, (code & 0x10U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(AUDIO_PORT, AUDIO_B3_PIN, (code & 0x08U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(AUDIO_PORT, AUDIO_B2_PIN, (code & 0x04U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(AUDIO_PORT, AUDIO_B1_PIN, (code & 0x02U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  s_audio_busy = 1U;
  s_audio_tick = HAL_GetTick();
}

void Audio_Task(void)
{
  if (s_audio_busy && (HAL_GetTick() - s_audio_tick) >= AUDIO_PULSE_MS) {
    Audio_Clear();
    s_audio_busy = 0U;
  }
}
