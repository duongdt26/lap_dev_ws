/**
 * app_main.c — Application loop for AMR conveyor board
 *
 * Safety policy:
 * - Emergency/Bumper is checked every loop and forces ESTOP.
 * - Stop physical creates STOP_LOCK.
 * - Reset clears STOP_LOCK/ESTOP/FAULT/COMM_LOST only; it never starts any belt.
 * - Start physical enables READY only; it never starts any belt.
 * - UART RX interrupt only stores bytes. All command parsing happens in App_Loop().
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

static uint32_t s_telem_tick = 0U;
static uint32_t s_emer_audio_tick = 0U;

#define TELEMETRY_PERIOD_MS  500U

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

static void handle_emergency_audio(void)
{
  if ((HAL_GetTick() - s_emer_audio_tick) >= EMER_AUDIO_REPEAT_MS) {
    Audio_SendHex(AUDIO_CODE_BAI_1);
    s_emer_audio_tick = HAL_GetTick();
  }
}

static void handle_buttons(void)
{
  /* Emergency is level-based, not only edge-based. */
  if (s_f_emer.active_event || InputFilter_IsActive(&s_f_emer, BTN_EMER_ACTIVE)) {
    if (Belt_GetState() != SYS_ESTOP || Belt_GetEstopSource() != ESTOP_SRC_EMER) {
      Belt_TriggerEstop(ESTOP_SRC_EMER);
      UART_SendEventEstop(ESTOP_SRC_EMER);
      Audio_SendHex(AUDIO_CODE_BAI_1);
      s_emer_audio_tick = HAL_GetTick();
    } else {
      handle_emergency_audio();
    }
    return;
  }

  /* Bumper is also level-based. If powered on while bumper is held, still enter ESTOP. */
  if (s_f_b1.active_event || InputFilter_IsActive(&s_f_b1, BUMPER_ACTIVE)) {
    if (Belt_GetState() != SYS_ESTOP || Belt_GetEstopSource() != ESTOP_SRC_BUMPER1) {
      Belt_TriggerEstop(ESTOP_SRC_BUMPER1);
      UART_SendEventBumper(1U);
      UART_SendEventEstop(ESTOP_SRC_BUMPER1);
      Audio_SendHex(AUDIO_CODE_BAI_4);
    }
    return;
  }

  if (s_f_b2.active_event || InputFilter_IsActive(&s_f_b2, BUMPER_ACTIVE)) {
    if (Belt_GetState() != SYS_ESTOP || Belt_GetEstopSource() != ESTOP_SRC_BUMPER2) {
      Belt_TriggerEstop(ESTOP_SRC_BUMPER2);
      UART_SendEventBumper(2U);
      UART_SendEventEstop(ESTOP_SRC_BUMPER2);
      Audio_SendHex(AUDIO_CODE_BAI_4);
    }
    return;
  }

  if (s_f_stop.active_event) {
    Belt_OnStopButton();
    UART_SendEventStopLock(1U);
    Audio_SendHex(AUDIO_CODE_BAI_2);
    return;
  }

  if (s_f_start.active_event) {
    if (Belt_OnStartButton()) {
      UART_SendAckReady();
      UART_SendEventReady();
    }
    Audio_SendHex(AUDIO_CODE_BAI_3);
    return;
  }

  if (s_f_reset.active_event) {
    uint8_t reset_result = Belt_OnResetButton();

    if (reset_result == 1U) {
      UART_SendAckResetEstop();
      UART_SendEventReset("ESTOP");
    } else if (reset_result == 2U) {
      UART_SendEventStopLock(0U);
      UART_SendEventReset("STOP_LOCK");
    } else if (reset_result == 3U) {
      UART_SendAckResetFault();
      UART_SendEventReset("FAULT");
    } else if (reset_result == 4U) {
      UART_Proto_ClearHeartbeatTimeout();
      UART_SendEventReset("COMM_LOST");
    }

    return;
  }
}

static void handle_comm_watchdog(void)
{
  if (UART_Proto_LinkTimedOut()) {
    if (Belt_SetCommLost()) {
      UART_SendEventCommLost();
    }
  }
}

static void handle_belt_events(void)
{
  BeltEvent_t ev;

  while (Belt_PopEvent(&ev)) {
    if (ev.type == BELT_EVENT_LOAD_DETECTED) {
      UART_SendEventLoadDetected(ev.belt_id, ev.sensor_a, ev.sensor_b, ev.seq);
    } else if (ev.type == BELT_EVENT_LOAD_DONE) {
      UART_SendEventLoadDone(ev.belt_id, ev.sensor_a, ev.seq);
    } else if (ev.type == BELT_EVENT_UNLOAD_DONE) {
      UART_SendEventUnloadDone(ev.belt_id, ev.side, ev.sensor_a, ev.seq);
    } else if (ev.type == BELT_EVENT_MANUAL_RUN) {
      UART_SendEventManualRun(ev.belt_id, ev.side, ev.seq);
    } else if (ev.type == BELT_EVENT_MANUAL_STOP) {
      UART_SendEventManualStop(ev.belt_id, ev.seq);
    } else if (ev.type == BELT_EVENT_FAULT) {
      UART_SendEventFault(ev.belt_id, ev.fault, ev.seq);
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
  belt_mask = Belt_GetActiveBelt();
  UART_SendTelemetry(st, belt_mask, Belt_GetDirection(), Belt_GetEstopSource());
}

void App_Init(UART_HandleTypeDef *huart)
{
  Audio_Clear();
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
  poll_inputs();
  handle_buttons();

  UART_Proto_Process();
  handle_comm_watchdog();

  Belt_Tick();
  handle_belt_events();

  Audio_Task();
  send_telemetry_if_due();
}
