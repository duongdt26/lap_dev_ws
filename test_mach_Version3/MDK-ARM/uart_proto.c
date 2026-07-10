#include "uart_proto.h"
#include "belt_fsm.h"
#include "audio_board.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static UART_HandleTypeDef *s_huart = NULL;
static uint8_t s_uart_rx_byte = 0U;
static volatile uint8_t s_rx_head = 0U;
static volatile uint8_t s_rx_tail = 0U;
static uint8_t s_rx_ring[UART_RX_RING_SIZE];
static char s_line_buf[UART_LINE_MAX];
static uint16_t s_line_len = 0U;
static uint32_t s_last_heartbeat_tick = 0U;
static uint8_t s_link_seen = 0U;

static void handle_line(char *line);

static void uart_send_str(const char *s)
{
  if (s_huart == NULL || s == NULL) {
    return;
  }

  HAL_UART_Transmit(s_huart, (uint8_t *)s, (uint16_t)strlen(s), 50U);
}

static void uart_send_frame(const char *fmt, ...)
{
  char buf[UART_LINE_MAX];
  va_list ap;

  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);

  uart_send_str(buf);
}

static uint8_t ascii_upper(uint8_t c)
{
  if (c >= 'a' && c <= 'z') {
    return (uint8_t)(c - 32U);
  }

  return c;
}

static int str_eq_nocase(const char *a, const char *b)
{
  uint16_t i = 0U;

  while (a[i] != '\0' && b[i] != '\0') {
    if (ascii_upper((uint8_t)a[i]) != ascii_upper((uint8_t)b[i])) {
      return 0;
    }
    i++;
  }

  return (a[i] == '\0' && b[i] == '\0') ? 1 : 0;
}

static uint8_t is_dec_number(const char *s)
{
  uint16_t i;

  if (s == NULL || s[0] == '\0') {
    return 0U;
  }

  for (i = 0U; s[i] != '\0'; i++) {
    if (s[i] < '0' || s[i] > '9') {
      return 0U;
    }
  }

  return 1U;
}

static const char *side_to_str(BeltSide_t side)
{
  return (side == BELT_SIDE_LEFT) ? "LEFT" : "RIGHT";
}

static BeltSide_t parse_side(const char *s, uint8_t *ok)
{
  if (str_eq_nocase(s, "LEFT")) {
    *ok = 1U;
    return BELT_SIDE_LEFT;
  }

  if (str_eq_nocase(s, "RIGHT")) {
    *ok = 1U;
    return BELT_SIDE_RIGHT;
  }

  *ok = 0U;
  return BELT_SIDE_LEFT;
}

static const char *cmd_result_reason(BeltCmdResult_t r)
{
  switch (r) {
  case BELT_CMD_BUSY:      return "BUSY";
  case BELT_CMD_ESTOP:     return "ESTOP";
  case BELT_CMD_INVALID:   return "INVALID";
  case BELT_CMD_NO_CARGO:  return "NO_CARGO";
  case BELT_CMD_STOP_LOCK: return "STOP_LOCK";
  case BELT_CMD_FAULT:     return "FAULT";
  case BELT_CMD_COMM_LOST: return "COMM_LOST";
  case BELT_CMD_NOT_READY: return "NOT_READY";
  case BELT_CMD_OK:
  default:                 return "OK";
  }
}

static void build_status_bits(char *out, size_t out_len)
{
  if (out_len < 9U) {
    return;
  }

  snprintf(out, out_len, "%u%u%u%u%u%u%u%u",
           Belt_HasCargo(1U), Belt_HasCargo(2U),
           Board_S1(), Board_S2(), Board_S3(), Board_S4(),
           Board_S5(), Board_S6());
}

static int split_fields(char *line, char *fields[], int max_fields)
{
  int n = 0;
  char *p;

  if (line[0] != '$') {
    return 0;
  }

  fields[n++] = line + 1;

  for (p = line + 1; *p != '\0' && n < max_fields; ++p) {
    if (*p == ',') {
      *p = '\0';
      fields[n++] = p + 1;
    }
  }

  return n;
}

static void mark_heartbeat_ok(void)
{
  s_last_heartbeat_tick = HAL_GetTick();
  s_link_seen = 1U;
  Belt_OnHeartbeatOk();
}

void UART_Proto_Init(UART_HandleTypeDef *huart)
{
  s_huart = huart;
  s_rx_head = 0U;
  s_rx_tail = 0U;
  s_line_len = 0U;
  s_line_buf[0] = '\0';
  s_last_heartbeat_tick = HAL_GetTick();
  s_link_seen = 0U;
}

uint8_t UART_Proto_LinkSeen(void)
{
  return s_link_seen;
}

uint8_t UART_Proto_LinkTimedOut(void)
{
  if (!s_link_seen) {
    return 0U;
  }

  return ((HAL_GetTick() - s_last_heartbeat_tick) > UART_HEARTBEAT_TIMEOUT_MS) ? 1U : 0U;
}

void UART_Proto_ClearHeartbeatTimeout(void)
{
  s_last_heartbeat_tick = HAL_GetTick();
  s_link_seen = 0U;
}

void UART_Proto_RxByte(uint8_t byte)
{
  uint8_t next = (uint8_t)((s_rx_head + 1U) % UART_RX_RING_SIZE);

  if (next == s_rx_tail) {
    /* Drop oldest byte on overflow. */
    s_rx_tail = (uint8_t)((s_rx_tail + 1U) % UART_RX_RING_SIZE);
  }

  s_rx_ring[s_rx_head] = byte;
  s_rx_head = next;
}

static uint8_t rx_pop(uint8_t *byte)
{
  if (s_rx_tail == s_rx_head) {
    return 0U;
  }

  *byte = s_rx_ring[s_rx_tail];
  s_rx_tail = (uint8_t)((s_rx_tail + 1U) % UART_RX_RING_SIZE);
  return 1U;
}

void UART_Proto_Process(void)
{
  uint8_t byte;

  while (rx_pop(&byte)) {
    if (byte == '\r' || byte == '\n') {
      if (s_line_len > 0U) {
        s_line_buf[s_line_len] = '\0';
        handle_line(s_line_buf);
        s_line_len = 0U;
        s_line_buf[0] = '\0';
      }
      continue;
    }

    if (s_line_len < (UART_LINE_MAX - 1U)) {
      s_line_buf[s_line_len++] = (char)byte;
      s_line_buf[s_line_len] = '\0';
    } else {
      s_line_len = 0U;
      s_line_buf[0] = '\0';
      UART_SendNack("LINE", 0U, BELT_SEQ_NONE, "TOO_LONG");
    }
  }
}

void UART_Proto_Poll(void)
{
  UART_Proto_Process();
}

static void handle_simple_text(char *line)
{
  if (str_eq_nocase(line, "START") ||
      str_eq_nocase(line, "STOP") ||
      str_eq_nocase(line, "RESET")) {
    mark_heartbeat_ok();
  }

  if (str_eq_nocase(line, "START")) {
    if (Belt_OnStartButton()) {
      UART_SendAckReady();
      UART_SendEventReady();
    }
    return;
  }

  if (str_eq_nocase(line, "STOP")) {
    Belt_OnStopButton();
    UART_SendEventStopLock(1U);
    return;
  }

  if (str_eq_nocase(line, "RESET")) {
    uint8_t r = Belt_OnResetButton();
    if (r == 1U) {
      UART_SendAckResetSeq("ESTOP", BELT_SEQ_NONE);
      UART_SendEventReset("ESTOP");
    } else if (r == 2U) {
      UART_SendAckResetSeq("STOP_LOCK", BELT_SEQ_NONE);
      UART_SendEventStopLock(0U);
      UART_SendEventReset("STOP_LOCK");
    } else if (r == 3U) {
      UART_SendAckResetSeq("FAULT", BELT_SEQ_NONE);
      UART_SendEventReset("FAULT");
    } else if (r == 4U) {
      UART_SendAckResetSeq("COMM_LOST", BELT_SEQ_NONE);
      UART_SendEventReset("COMM_LOST");
    } else {
      UART_SendNack("RESET", 0U, BELT_SEQ_NONE, "NOTHING_TO_RESET");
    }
    return;
  }
}

static void parse_cmd_indices(char *fields[], int nf, int *cmd_idx, uint32_t *seq)
{
  *cmd_idx = 1;
  *seq = BELT_SEQ_NONE;

  if (nf >= 3 && is_dec_number(fields[1])) {
    *seq = (uint32_t)strtoul(fields[1], NULL, 10);
    *cmd_idx = 2;
  }
}

static void handle_line(char *line)
{
  char *fields[12];
  int nf;
  int cmd_idx;
  uint32_t seq;

  if (line[0] != '$') {
    handle_simple_text(line);
    return;
  }

  nf = split_fields(line, fields, 12);
  if (nf < 1) {
    return;
  }

  if (str_eq_nocase(fields[0], "HELLO")) {
    mark_heartbeat_ok();
    UART_SendHelloAck();
    return;
  }

  if (str_eq_nocase(fields[0], "PING") && nf >= 2) {
    mark_heartbeat_ok();
    UART_SendPong((uint32_t)strtoul(fields[1], NULL, 10));
    return;
  }

  if (str_eq_nocase(fields[0], "BUZZER") && nf >= 3) {
    uint8_t belt_id = (uint8_t)strtoul(fields[2], NULL, 10);

    mark_heartbeat_ok();

    if (belt_id == 1U || belt_id == 2U) {
      if (str_eq_nocase(fields[1], "START")) {
        Audio_SendHex(AUDIO_CODE_BAI_16);
      } else if (str_eq_nocase(fields[1], "STOP")) {
        Audio_SendHex(AUDIO_CODE_BAI_17);
      }
    }

    return;
  }

  if (!str_eq_nocase(fields[0], "CMD") || nf < 2) {
    return;
  }

  mark_heartbeat_ok();
  parse_cmd_indices(fields, nf, &cmd_idx, &seq);

  if (cmd_idx >= nf) {
    UART_SendNack("CMD", 0U, seq, "BAD_FORMAT");
    return;
  }

  if (str_eq_nocase(fields[cmd_idx], "ENABLE") || str_eq_nocase(fields[cmd_idx], "READY")) {
    if (Belt_OnStartButton()) {
      UART_SendAckReadySeq(seq);
      UART_SendEventReady();
    } else {
      UART_SendNack(fields[cmd_idx], 0U, seq, cmd_result_reason((Belt_GetState() == SYS_ESTOP) ? BELT_CMD_ESTOP : BELT_CMD_FAULT));
    }
    return;
  }

  if (str_eq_nocase(fields[cmd_idx], "RESET") || str_eq_nocase(fields[cmd_idx], "RESET_ESTOP")) {
    uint8_t r = Belt_OnResetButton();
    if (r == 1U) {
      UART_SendAckResetSeq("ESTOP", seq);
      UART_SendEventReset("ESTOP");
    } else if (r == 2U) {
      UART_SendAckResetSeq("STOP_LOCK", seq);
      UART_SendEventStopLock(0U);
      UART_SendEventReset("STOP_LOCK");
    } else if (r == 3U) {
      UART_SendAckResetSeq("FAULT", seq);
      UART_SendEventReset("FAULT");
    } else if (r == 4U) {
      UART_SendAckResetSeq("COMM_LOST", seq);
      UART_SendEventReset("COMM_LOST");
    } else {
      UART_SendNack(fields[cmd_idx], 0U, seq, "NOTHING_TO_RESET");
    }
    return;
  }

  if ((str_eq_nocase(fields[cmd_idx], "MANUAL_RUN") ||
       str_eq_nocase(fields[cmd_idx], "RUN")) && nf > (cmd_idx + 2)) {
    uint8_t belt_id = (uint8_t)strtoul(fields[cmd_idx + 1], NULL, 10);
    uint8_t side_ok = 0U;
    BeltSide_t side = parse_side(fields[cmd_idx + 2], &side_ok);
    BeltCmdResult_t r;

    if (!side_ok) {
      UART_SendNack(fields[cmd_idx], belt_id, seq, "BAD_SIDE");
      return;
    }

    r = Belt_CmdManualRunSeq(belt_id, side, seq);
    if (r == BELT_CMD_OK) {
      UART_SendAckManualRunAccepted(belt_id, side, seq);
    } else {
      UART_SendNack(fields[cmd_idx], belt_id, seq, cmd_result_reason(r));
    }

    return;
  }

  if ((str_eq_nocase(fields[cmd_idx], "MANUAL_STOP") ||
       str_eq_nocase(fields[cmd_idx], "MSTOP") ||
       str_eq_nocase(fields[cmd_idx], "BELT_STOP")) && nf > (cmd_idx + 1)) {
    uint8_t belt_id = (uint8_t)strtoul(fields[cmd_idx + 1], NULL, 10);
    BeltCmdResult_t r = Belt_CmdManualStopSeq(belt_id, seq);

    if (r == BELT_CMD_OK) {
      UART_SendAckManualStop(belt_id, seq);
    } else {
      UART_SendNack(fields[cmd_idx], belt_id, seq, cmd_result_reason(r));
    }

    return;
  }

  if (str_eq_nocase(fields[cmd_idx], "START") && nf > (cmd_idx + 1)) {
    uint8_t belt_id = (uint8_t)strtoul(fields[cmd_idx + 1], NULL, 10);
    BeltCmdResult_t r = Belt_CmdStartLoadSeq(belt_id, seq);

    if (r == BELT_CMD_OK) {
      UART_SendAckStart(belt_id, seq);
    } else {
      UART_SendNack("START", belt_id, seq, cmd_result_reason(r));
    }

    return;
  }

  if ((str_eq_nocase(fields[cmd_idx], "STOP") || str_eq_nocase(fields[cmd_idx], "UNLOAD")) && nf > (cmd_idx + 2)) {
    uint8_t belt_id = (uint8_t)strtoul(fields[cmd_idx + 1], NULL, 10);
    uint8_t side_ok = 0U;
    BeltSide_t side = parse_side(fields[cmd_idx + 2], &side_ok);
    BeltCmdResult_t r;

    if (!side_ok) {
      UART_SendNack("STOP", belt_id, seq, "BAD_SIDE");
      return;
    }

    r = Belt_CmdUnloadSeq(belt_id, side, seq);
    if (r == BELT_CMD_OK) {
      UART_SendAckUnloadAccepted(belt_id, side, seq);
    } else {
      UART_SendNack(fields[cmd_idx], belt_id, seq, cmd_result_reason(r));
    }

    return;
  }

  UART_SendNack(fields[cmd_idx], 0U, seq, "BAD_FORMAT");
}

void UART_SendHelloAck(void)
{
  uart_send_frame("$HELLO_ACK,STM32,OK,AMR_CONVEYOR_SAFE_V4\r\n");
}

void UART_SendPong(uint32_t seq)
{
  uart_send_frame("$PONG,%lu\r\n", (unsigned long)seq);
}

static void send_ack_cmd(const char *cmd, uint8_t belt_id, uint32_t seq, const char *extra)
{
  if (seq != BELT_SEQ_NONE) {
    if (extra != NULL) {
      uart_send_frame("$ACK,%lu,CMD,%s,%u,%s\r\n", (unsigned long)seq, cmd, belt_id, extra);
    } else if (belt_id > 0U) {
      uart_send_frame("$ACK,%lu,CMD,%s,%u\r\n", (unsigned long)seq, cmd, belt_id);
    } else {
      uart_send_frame("$ACK,%lu,CMD,%s\r\n", (unsigned long)seq, cmd);
    }
  } else {
    if (extra != NULL) {
      uart_send_frame("$ACK,CMD,%s,%u,%s\r\n", cmd, belt_id, extra);
    } else if (belt_id > 0U) {
      uart_send_frame("$ACK,CMD,%s,%u\r\n", cmd, belt_id);
    } else {
      uart_send_frame("$ACK,CMD,%s\r\n", cmd);
    }
  }
}

void UART_SendAckStart(uint8_t belt_id, uint32_t seq)
{
  send_ack_cmd("START", belt_id, seq, "ACCEPTED");
}

void UART_SendAckStop(uint8_t belt_id, uint32_t seq)
{
  send_ack_cmd("STOP", belt_id, seq, NULL);
}

void UART_SendAckStopSide(uint8_t belt_id, BeltSide_t side, uint32_t seq)
{
  send_ack_cmd("STOP", belt_id, seq, side_to_str(side));
}

void UART_SendAckUnloadAccepted(uint8_t belt_id, BeltSide_t side, uint32_t seq)
{
  if (seq != BELT_SEQ_NONE) {
    uart_send_frame("$ACK,%lu,CMD,STOP,%u,%s,ACCEPTED\r\n",
                    (unsigned long)seq, belt_id, side_to_str(side));
  } else {
    uart_send_frame("$ACK,CMD,STOP,%u,%s,ACCEPTED\r\n", belt_id, side_to_str(side));
  }
}

void UART_SendAckManualRunAccepted(uint8_t belt_id, BeltSide_t side, uint32_t seq)
{
  if (seq != BELT_SEQ_NONE) {
    uart_send_frame("$ACK,%lu,CMD,MANUAL_RUN,%u,%s,ACCEPTED\r\n",
                    (unsigned long)seq, belt_id, side_to_str(side));
  } else {
    uart_send_frame("$ACK,CMD,MANUAL_RUN,%u,%s,ACCEPTED\r\n", belt_id, side_to_str(side));
  }
}

void UART_SendAckManualStop(uint8_t belt_id, uint32_t seq)
{
  if (seq != BELT_SEQ_NONE) {
    uart_send_frame("$ACK,%lu,CMD,MANUAL_STOP,%u\r\n", (unsigned long)seq, belt_id);
  } else {
    uart_send_frame("$ACK,CMD,MANUAL_STOP,%u\r\n", belt_id);
  }
}

void UART_SendAckResetEstop(void)
{
  uart_send_frame("$ACK,CMD,RESET_ESTOP\r\n");
}

void UART_SendAckResetFault(void)
{
  uart_send_frame("$ACK,CMD,RESET_FAULT\r\n");
}

void UART_SendAckReady(void)
{
  uart_send_frame("$ACK,CMD,READY\r\n");
}

void UART_SendAckReadySeq(uint32_t seq)
{
  if (seq != BELT_SEQ_NONE) {
    uart_send_frame("$ACK,%lu,CMD,READY\r\n", (unsigned long)seq);
  } else {
    UART_SendAckReady();
  }
}

void UART_SendAckResetSeq(const char *what, uint32_t seq)
{
  if (what == NULL) {
    what = "UNKNOWN";
  }

  if (seq != BELT_SEQ_NONE) {
    uart_send_frame("$ACK,%lu,CMD,RESET,%s\r\n", (unsigned long)seq, what);
  } else {
    uart_send_frame("$ACK,CMD,RESET,%s\r\n", what);
  }
}

void UART_SendNack(const char *cmd, uint8_t belt_id, uint32_t seq, const char *reason)
{
  if (seq != BELT_SEQ_NONE) {
    if (belt_id > 0U) {
      uart_send_frame("$NACK,%lu,CMD,%s,%u,%s\r\n", (unsigned long)seq, cmd, belt_id, reason);
    } else {
      uart_send_frame("$NACK,%lu,CMD,%s,%s\r\n", (unsigned long)seq, cmd, reason);
    }
  } else {
    if (belt_id > 0U) {
      uart_send_frame("$NACK,CMD,%s,%u,%s\r\n", cmd, belt_id, reason);
    } else {
      uart_send_frame("$NACK,CMD,%s,%s\r\n", cmd, reason);
    }
  }
}

void UART_SendTelemetry(SystemState_t state, uint8_t active_belt,
                        BeltDirection_t dir, uint8_t estop_source)
{
  char bits[10];
  const char *ds;

  (void)dir;
  build_status_bits(bits, sizeof(bits));
  ds = "NONE";

  uart_send_frame("$TELEMETRY,%s,%s,%u,%s,%u,%u,%s,%s,%u\r\n",
                  Belt_StateToString(state),
                  bits,
                  active_belt,
                  ds,
                  estop_source,
                  Belt_GetFaultCode(),
                  Belt_PublicStateToString(Belt_GetBeltPublicState(1U)),
                  Belt_PublicStateToString(Belt_GetBeltPublicState(2U)),
                  Belt_IsStopLocked());
}

void UART_SendEventBumper(uint8_t bumper_id)
{
  uart_send_frame("$EVENT,BUMPER,%u,TRIGGER\r\n", bumper_id);
}

void UART_SendEventEstop(uint8_t source_code)
{
  uart_send_frame("$EVENT,ESTOP,%u,TRIGGER\r\n", source_code);
}

void UART_SendEventStopLock(uint8_t locked)
{
  uart_send_frame("$EVENT,STOP_LOCK,%s\r\n", locked ? "TRIGGER" : "CLEAR");
}

void UART_SendEventReady(void)
{
  uart_send_frame("$EVENT,READY\r\n");
}

void UART_SendEventLoadDetected(uint8_t belt_id, uint8_t source_sensor, uint8_t target_sensor, uint32_t seq)
{
  if (seq != BELT_SEQ_NONE) {
    uart_send_frame("$EVENT,%lu,LOAD_DETECTED,%u,%u,%u\r\n",
                    (unsigned long)seq, belt_id, source_sensor, target_sensor);
  } else {
    uart_send_frame("$EVENT,LOAD_DETECTED,%u,%u,%u\r\n",
                    belt_id, source_sensor, target_sensor);
  }
}

void UART_SendEventLoadDone(uint8_t belt_id, uint8_t cargo_sensor, uint32_t seq)
{
  if (seq != BELT_SEQ_NONE) {
    uart_send_frame("$EVENT,%lu,LOAD_DONE,%u,%u\r\n",
                    (unsigned long)seq, belt_id, cargo_sensor);
  } else {
    uart_send_frame("$EVENT,LOAD_DONE,%u,%u\r\n", belt_id, cargo_sensor);
  }
}

void UART_SendEventUnloadDone(uint8_t belt_id, BeltSide_t side, uint8_t exit_sensor, uint32_t seq)
{
  if (seq != BELT_SEQ_NONE) {
    uart_send_frame("$EVENT,%lu,UNLOAD_DONE,%u,%s,%u\r\n",
                    (unsigned long)seq, belt_id, side_to_str(side), exit_sensor);
  } else {
    uart_send_frame("$EVENT,UNLOAD_DONE,%u,%s,%u\r\n",
                    belt_id, side_to_str(side), exit_sensor);
  }
}

void UART_SendEventManualRun(uint8_t belt_id, BeltSide_t side, uint32_t seq)
{
  if (seq != BELT_SEQ_NONE) {
    uart_send_frame("$EVENT,%lu,MANUAL_RUN,%u,%s\r\n",
                    (unsigned long)seq, belt_id, side_to_str(side));
  } else {
    uart_send_frame("$EVENT,MANUAL_RUN,%u,%s\r\n", belt_id, side_to_str(side));
  }
}

void UART_SendEventManualStop(uint8_t belt_id, uint32_t seq)
{
  if (seq != BELT_SEQ_NONE) {
    uart_send_frame("$EVENT,%lu,MANUAL_STOP,%u\r\n", (unsigned long)seq, belt_id);
  } else {
    uart_send_frame("$EVENT,MANUAL_STOP,%u\r\n", belt_id);
  }
}

void UART_SendEventFault(uint8_t belt_id, BeltFaultCode_t fault, uint32_t seq)
{
  if (seq != BELT_SEQ_NONE) {
    uart_send_frame("$EVENT,%lu,FAULT,%s,%u\r\n", (unsigned long)seq, Belt_FaultToString(fault), belt_id);
  } else {
    uart_send_frame("$EVENT,FAULT,%s,%u\r\n", Belt_FaultToString(fault), belt_id);
  }
}

void UART_SendEventCommLost(void)
{
  uart_send_frame("$EVENT,COMM_LOST\r\n");
}

void UART_SendEventReset(const char *what)
{
  uart_send_frame("$EVENT,RESET,%s\r\n", what);
}

void UART_Proto_StartReceiveIT(void)
{
  if (s_huart == NULL) {
    return;
  }

  HAL_UART_Receive_IT(s_huart, &s_uart_rx_byte, 1U);
}

void UART_Proto_RxCpltCallback(UART_HandleTypeDef *huart)
{
  if (s_huart == NULL) {
    return;
  }

  if (huart->Instance == s_huart->Instance) {
    UART_Proto_RxByte(s_uart_rx_byte);
    HAL_UART_Receive_IT(s_huart, &s_uart_rx_byte, 1U);
  }
}

void UART_Proto_ErrorCallback(UART_HandleTypeDef *huart)
{
  if (s_huart == NULL) {
    return;
  }

  if (huart->Instance == s_huart->Instance) {
    HAL_UART_Receive_IT(s_huart, &s_uart_rx_byte, 1U);
  }
}
