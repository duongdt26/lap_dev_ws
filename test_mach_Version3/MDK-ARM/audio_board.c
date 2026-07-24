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
  HAL_GPIO_WritePin(AUDIO_PORT, AUDIO_N1_PIN, (code & 0x01U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(AUDIO_PORT, AUDIO_N2_PIN, (code & 0x02U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(AUDIO_PORT, AUDIO_N3_PIN, (code & 0x04U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(AUDIO_PORT, AUDIO_N4_PIN, (code & 0x08U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  s_audio_busy = 1U;
  s_audio_tick = HAL_GetTick();
}

uint8_t Audio_PlayTrack(uint8_t track)
{
  uint8_t code;

  switch (track) {
  case 1U:  code = AUDIO_CODE_BAI_1;  break;
  case 2U:  code = AUDIO_CODE_BAI_2;  break;
  case 3U:  code = AUDIO_CODE_BAI_3;  break;
  case 4U:  code = AUDIO_CODE_BAI_4;  break;
  case 16U: code = AUDIO_CODE_BAI_16; break;
  case 17U: code = AUDIO_CODE_BAI_17; break;
  case 18U: code = AUDIO_CODE_BAI_18; break;
  case 19U: code = AUDIO_CODE_BAI_19; break;
  case 20U: code = AUDIO_CODE_BAI_20; break;
  case 21U: code = AUDIO_CODE_BAI_21; break;
  case 22U: code = AUDIO_CODE_BAI_22; break;
  case 24U: code = AUDIO_CODE_BAI_24; break;
  case 25U: code = AUDIO_CODE_BAI_25; break;
  case 26U: code = AUDIO_CODE_BAI_26; break;
  case 28U: code = AUDIO_CODE_BAI_28; break;
  default: return 0U;
  }

  Audio_SendHex(code);
  return 1U;
}

void Audio_Task(void)
{
  if (s_audio_busy && (HAL_GetTick() - s_audio_tick) >= AUDIO_PULSE_MS) {
    Audio_Clear();
    s_audio_busy = 0U;
  }
}
