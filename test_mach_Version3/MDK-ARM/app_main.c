/**
 * app_main.c — Vong lap ung dung conveyor
 *
 * Update moi:
 * - $CMD,START,1 chi cho phep bang tai 1, chi doc S1/S3.
 * - $CMD,START,2 chi cho phep bang tai 2, chi doc S2/S4.
 * - $CMD,STOP,1,LEFT/RIGHT chi chay bang tai 1.
 * - $CMD,STOP,2,LEFT/RIGHT chi chay bang tai 2.
 * - Hai bang tai co the chay doc lap neu ROS2 gui lenh cho tung bang tai.
 * - Nut START/RUN vat ly: bat che do auto lien tuc cho ca 2 bang tai: belt1 S1<->S3, belt2 S2<->S4 den khi STOP.
 * - Cam bien khong phat loa nua.
 * - Telemetry direction de NONE, chi ACK moi xac nhan ket qua lenh ROS2.
 */

#include "app_main.h"
#include "audio_board.h"
#include "belt_fsm.h"
#include "board_gpio.h"
#include "input_filter.h"
#include "uart_proto.h"

static InputFilter_t s_f_emer;
static InputFilter_t s_f_stop;
static InputFilter_t s_f_start;
static InputFilter_t s_f_reset;
static InputFilter_t s_f_b1;
static InputFilter_t s_f_b2;

static uint32_t s_telem_tick = 0;
static uint32_t s_emer_audio_tick = 0;

#define TELEMETRY_PERIOD_MS  1000U

static void poll_inputs(void)
{
  InputFilter_Update(&s_f_emer,
                     HAL_GPIO_ReadPin(BTN_EMER_PORT, BTN_EMER_PIN),
                     BTN_EMER_ACTIVE);

  InputFilter_Update(&s_f_stop,
                     HAL_GPIO_ReadPin(BTN_STOP_PORT, BTN_STOP_PIN),
                     BTN_CTRL_ACTIVE);

  InputFilter_Update(&s_f_start,
                     HAL_GPIO_ReadPin(BTN_START_PORT, BTN_START_PIN),
                     BTN_CTRL_ACTIVE);

  InputFilter_Update(&s_f_reset,
                     HAL_GPIO_ReadPin(BTN_RESET_PORT, BTN_RESET_PIN),
                     BTN_CTRL_ACTIVE);

  InputFilter_Update(&s_f_b1,
                     HAL_GPIO_ReadPin(BUMPER1_PORT, BUMPER1_PIN),
                     BUMPER_ACTIVE);

  InputFilter_Update(&s_f_b2,
                     HAL_GPIO_ReadPin(BUMPER2_PORT, BUMPER2_PIN),
                     BUMPER_ACTIVE);
}

static void handle_buttons(void)
{
  /* Emergency: bai 16, lap lai moi 1 giay khi con tin hieu */
  if (s_f_emer.active_event || InputFilter_IsActive(&s_f_emer, BTN_EMER_ACTIVE)) {
    if (Belt_GetState() != SYS_ESTOP) {
      Belt_TriggerEstop(ESTOP_SRC_EMER);
      Audio_SendHex(AUDIO_CODE_BAI_16);
      s_emer_audio_tick = HAL_GetTick();
    } else if ((HAL_GetTick() - s_emer_audio_tick) >= EMER_AUDIO_REPEAT_MS) {
      Audio_SendHex(AUDIO_CODE_BAI_16);
      s_emer_audio_tick = HAL_GetTick();
    }

    return;
  }

  /* Bumper 1/2: bai 20/21, phat mot lan theo canh kich hoat */
  if (s_f_b1.active_event) {
    Belt_TriggerEstop(ESTOP_SRC_BUMPER1);
    UART_SendEventBumper(1U);
    Audio_SendHex(AUDIO_CODE_BAI_20);
    return;
  }

  if (s_f_b2.active_event) {
    Belt_TriggerEstop(ESTOP_SRC_BUMPER2);
    UART_SendEventBumper(2U);
    Audio_SendHex(AUDIO_CODE_BAI_21);
    return;
  }

  /* Stop vat ly: bai 17 */
  if (s_f_stop.active_event) {
    Belt_OnStopButton();
    Audio_SendHex(AUDIO_CODE_BAI_17);
    return;
  }

  /* Start/RUN vat ly: bai 18, mo khoa STOP va bat auto ca 2 bang tai */
  if (s_f_start.active_event) {
    Belt_OnStartButton();
    Audio_SendHex(AUDIO_CODE_BAI_18);
    return;
  }

  /* RESET chi dung de reset ESTOP sau khi Emergency da nha. */
  if (s_f_reset.active_event) {
    if (Belt_TryResetEstop()) {
      UART_SendAckResetEstop();
      Audio_SendHex(AUDIO_CODE_BAI_19);
    }
    return;
  }
}

static void handle_belt_events(void)
{
  BeltEvent_t ev;

  while (Belt_PopEvent(&ev)) {
    if (ev.type == BELT_EVENT_LOAD_STARTED) {
      UART_SendAckStart(ev.cmd_id);
    } else if (ev.type == BELT_EVENT_LOAD_STOPPED) {
      UART_SendAckStop(ev.cmd_id);
    } else if (ev.type == BELT_EVENT_UNLOAD_DONE) {
      UART_SendAckStopSide(ev.cmd_id, ev.side);
    } else if (ev.type == BELT_EVENT_LOAD_NO_CARGO_TIMEOUT) {
      UART_SendNack("START", ev.cmd_id, "NO_CARGO_TIMEOUT");
    } else if (ev.type == BELT_EVENT_LOAD_JAM) {
      UART_SendNack("START", ev.cmd_id, "CARGO_JAM");
    } else if (ev.type == BELT_EVENT_UNLOAD_JAM) {
      UART_SendNack("STOP", ev.cmd_id, "CARGO_JAM");
    }
  }
}

static void send_telemetry_if_due(void)
{
  SystemState_t st;
  uint8_t belt_mask;

  if ((HAL_GetTick() - s_telem_tick) < TELEMETRY_PERIOD_MS) {
    return;
  }

  s_telem_tick = HAL_GetTick();

  st = Belt_GetState();
  belt_mask = (st == SYS_RUNNING) ? Belt_GetActiveBelt() : 0U;

  /* Direction trong telemetry da de NONE trong UART_SendTelemetry() */
  UART_SendTelemetry(st, belt_mask, Belt_GetEstopSource());
}

void App_Init(UART_HandleTypeDef *huart)
{
  Audio_Clear();
  Board_SensorsInit();
  Belt_Init();

  UART_Proto_Init(huart);
  UART_Proto_StartReceiveIT();

  InputFilter_Init(&s_f_emer, HAL_GPIO_ReadPin(BTN_EMER_PORT, BTN_EMER_PIN));
  InputFilter_Init(&s_f_stop, HAL_GPIO_ReadPin(BTN_STOP_PORT, BTN_STOP_PIN));
  InputFilter_Init(&s_f_start, HAL_GPIO_ReadPin(BTN_START_PORT, BTN_START_PIN));
  InputFilter_Init(&s_f_reset, HAL_GPIO_ReadPin(BTN_RESET_PORT, BTN_RESET_PIN));
  InputFilter_Init(&s_f_b1, HAL_GPIO_ReadPin(BUMPER1_PORT, BUMPER1_PIN));
  InputFilter_Init(&s_f_b2, HAL_GPIO_ReadPin(BUMPER2_PORT, BUMPER2_PIN));

  s_telem_tick = HAL_GetTick();
  s_emer_audio_tick = HAL_GetTick();
}

void App_Loop(void)
{
  Board_SensorsUpdate();
  poll_inputs();
  handle_buttons();

  /* ISR chi dua byte vao ring buffer; parse lenh tai main loop. */
  UART_Proto_Poll();
  Belt_Tick();
  handle_belt_events();

  Audio_Task();
  send_telemetry_if_due();
}
