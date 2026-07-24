#ifndef AUDIO_BOARD_H
#define AUDIO_BOARD_H

#include <stdint.h>

#define AUDIO_PULSE_MS       200U
#define EMER_AUDIO_REPEAT_MS 1000U

#define AUDIO_CODE_BAI_1   0x01U
#define AUDIO_CODE_BAI_2   0x02U
#define AUDIO_CODE_BAI_3   0x04U
#define AUDIO_CODE_BAI_4   0x08U
#define AUDIO_CODE_BAI_16  0x0FU
#define AUDIO_CODE_BAI_17  0x0EU
#define AUDIO_CODE_BAI_18  0x0DU
#define AUDIO_CODE_BAI_19  0x0CU
#define AUDIO_CODE_BAI_20  0x0BU
#define AUDIO_CODE_BAI_21  0x0AU
#define AUDIO_CODE_BAI_22  0x09U
#define AUDIO_CODE_BAI_24  0x07U
#define AUDIO_CODE_BAI_25  0x06U
#define AUDIO_CODE_BAI_26  0x05U
#define AUDIO_CODE_BAI_28  0x03U

void Audio_Clear(void);
void Audio_SendHex(uint8_t code);
uint8_t Audio_PlayTrack(uint8_t track);
void Audio_Task(void);

#endif
