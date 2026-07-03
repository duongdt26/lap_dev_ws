#ifndef AUDIO_BOARD_H
#define AUDIO_BOARD_H

#include <stdint.h>

#define AUDIO_PULSE_MS       200U
#define EMER_AUDIO_REPEAT_MS 5000U

/* Chi giu cac bai can dung theo yeu cau moi */
#define AUDIO_CODE_BAI_1   0x10U  /* Emergency lap moi 5 giay */
#define AUDIO_CODE_BAI_2   0x08U  /* Stop vat ly */
#define AUDIO_CODE_BAI_3   0x04U  /* Start vat ly */
#define AUDIO_CODE_BAI_4   0x02U  /* Bumper 1/2 */
#define AUDIO_CODE_BAI_16  0x1EU  /* $BUZZER,START,1/2 */
#define AUDIO_CODE_BAI_17  0x0EU  /* $BUZZER,STOP,1/2 */

void Audio_Clear(void);
void Audio_SendHex(uint8_t code);
void Audio_Task(void);

#endif
