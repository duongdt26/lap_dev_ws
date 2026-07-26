#include "uart_proto.h"
#include "belt_fsm.h"
#include "audio_board.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static UART_HandleTypeDef *s_huart = NULL;
static char s_line_buf[UART_LINE_MAX];
static uint16_t s_line_len = 0;
static uint8_t s_uart_rx_byte = 0;
static volatile uint8_t s_rx_ring[UART_RX_BUF_SIZE];
static volatile uint16_t s_rx_head = 0U;
static volatile uint16_t s_rx_tail = 0U;
static volatile uint8_t s_rx_overflow = 0U;

static void handle_line(char *line);
static void process_rx_byte(uint8_t byte);

static void uart_send_str(const char *s)
{
  if (s_huart == NULL) {
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

static const char *state_to_str(SystemState_t st)
{
  switch (st) {
  case SYS_RUNNING: return "RUNNING";
  case SYS_ESTOP:   return "ESTOP";
  default:          return "IDLE";
  }
}

static const char *side_to_str(BeltSide_t side)
{
  return (side == BELT_SIDE_LEFT) ? "LEFT" : "RIGHT";
}

static void build_status_bits(char *out, size_t out_len)
{
  if (out_len < 7U) {
    return;
  }

  snprintf(out, out_len, "%u%u%u%u%u%u",
           Belt_HasCargo(1U), Belt_HasCargo(2U),
           Board_S1(), Board_S2(), Board_S3(), Board_S4());
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

static uint8_t parse_u8_decimal(const char *s, uint8_t *value)
{
  char *end;
  unsigned long parsed;

  if (s == NULL || s[0] == '\0' || value == NULL) {
    return 0U;
  }

  parsed = strtoul(s, &end, 10);
  if (*end != '\0' || parsed > 255UL) {
    return 0U;
  }

  *value = (uint8_t)parsed;
  return 1U;
}

static const char *cmd_result_reason(BeltCmdResult_t r)
{
  switch (r) {
  case BELT_CMD_BUSY:     return "BUSY";
  case BELT_CMD_ESTOP:    return "ESTOP";
  case BELT_CMD_INVALID:  return "INVALID";
  case BELT_CMD_NO_CARGO:  return "NO_CARGO";
  case BELT_CMD_STOP_LOCK: return "STOP_LOCK";
  case BELT_CMD_OK:
  default:                return "OK";
  }
}

void UART_Proto_Init(UART_HandleTypeDef *huart)
{
  s_huart = huart;
  s_line_len = 0U;
  s_rx_head = 0U;
  s_rx_tail = 0U;
  s_rx_overflow = 0U;
  memset(s_line_buf, 0, sizeof(s_line_buf));
}

static void process_rx_byte(uint8_t byte)
{
  if (byte == '\r' || byte == '\n') {
    if (s_line_len > 0U) {
      s_line_buf[s_line_len] = '\0';
      handle_line(s_line_buf);

      s_line_len = 0U;
      s_line_buf[0] = '\0';
    }

    return;
  }

  if (s_line_len < (UART_LINE_MAX - 1U)) {
    s_line_buf[s_line_len++] = (char)byte;
    s_line_buf[s_line_len] = '\0';
  } else {
    s_line_len = 0U;
    s_line_buf[0] = '\0';
  }
}

void UART_Proto_Poll(void)
{
  uint8_t byte;

  if (s_rx_overflow) {
    __disable_irq();
    s_rx_tail = s_rx_head;
    s_rx_overflow = 0U;
    __enable_irq();

    s_line_len = 0U;
    s_line_buf[0] = '\0';
    UART_SendNack("UART", 0U, "RX_OVERFLOW");
  }

  while (s_rx_tail != s_rx_head) {
    byte = s_rx_ring[s_rx_tail];
    s_rx_tail = (uint16_t)((s_rx_tail + 1U) % UART_RX_BUF_SIZE);
    process_rx_byte(byte);
  }
}

static int split_fields(char *line, char *fields[], int max_fields)
{
  int n = 0;

  if (line[0] != '$') {
    return 0;
  }

  fields[n++] = line + 1;

  for (char *p = line + 1; *p != '\0' && n < max_fields; ++p) {
    if (*p == ',') {
      *p = '\0';
      fields[n++] = p + 1;
    }
  }

  return n;
}

static void handle_line(char *line)
{
  char *fields[12];
  int nf;

  if (line[0] != '$') {
    return;
  }

  nf = split_fields(line, fields, 12);
  if (nf < 1) {
    return;
  }

  if (str_eq_nocase(fields[0], "HELLO")) {
    UART_SendHelloAck();
    return;
  }

  if (str_eq_nocase(fields[0], "PING") && nf >= 2) {
    UART_SendPong((uint32_t)strtoul(fields[1], NULL, 10));
    return;
  }

  if (!str_eq_nocase(fields[0], "CMD") || nf < 2) {
    return;
  }

  /* $CMD,Buzzer,<track>: xuat ma GPIO song song trong 200 ms. */
  if (str_eq_nocase(fields[1], "BUZZER") && nf >= 3) {
    uint8_t track;

    if (!parse_u8_decimal(fields[2], &track)) {
      UART_SendNack("BUZZER", 0U, "BAD_TRACK");
      return;
    }

    if (!Audio_PlayTrack(track)) {
      UART_SendNack("BUZZER", track, "INVALID_TRACK");
    }

    return;
  }

  /* ROS2 kich hoat Emergency: $CMD,ESTOP */
  if (str_eq_nocase(fields[1], "ESTOP")) {
    Belt_TriggerEstop(ESTOP_SRC_ROS2);
    UART_SendAckEstop();
    return;
  }

  /* Reset dong thoi Emergency va STOP_LOCK: $CMD,RESET_ESTOP */
  if (str_eq_nocase(fields[1], "RESET_ESTOP")) {
    if (Belt_TryResetEstop()) {
      UART_SendAckResetEstop();
    } else {
      UART_SendNack("RESET_ESTOP", 0U, "RESET_BLOCKED");
    }
    return;
  }

  /*
     START moi:
       $CMD,START,1  -> chi arm/load bang tai 1, chi doc S1/S3
       $CMD,START,2  -> chi arm/load bang tai 2, chi doc S2/S4
       Neu co them field phia sau thi bo qua, vi START chi can belt_id.

     Khong ACK START ngay luc nhan lenh.
     Chi ACK khi cam bien cua dung bang tai lan dau phat hien hang sau khi da arm.
  */
  if (str_eq_nocase(fields[1], "START") && nf >= 3) {
    uint8_t cmd_id;
    BeltCmdResult_t r;

    if (!parse_u8_decimal(fields[2], &cmd_id)) {
      UART_SendNack("START", 0U, "BAD_ID");
      return;
    }

    r = Belt_CmdStartLoad(cmd_id);

    if (r != BELT_CMD_OK) {
      UART_SendNack("START", cmd_id, cmd_result_reason(r));
    }

    return;
  }

  /*
     STOP moi = tra hang:
       $CMD,STOP,1,LEFT/RIGHT  -> chi chay bang tai 1, chi dung S1/S3
       $CMD,STOP,2,LEFT/RIGHT  -> chi chay bang tai 2, chi dung S2/S4

     Khong ACK STOP ngay luc nhan lenh.
     Chi ACK khi hang da ra khoi sensor cua ra.
  */
  if (str_eq_nocase(fields[1], "STOP") && nf >= 4) {
    uint8_t cmd_id;
    uint8_t side_ok = 0U;
    BeltSide_t side;
    BeltCmdResult_t r;

    if (!parse_u8_decimal(fields[2], &cmd_id)) {
      UART_SendNack("STOP", 0U, "BAD_ID");
      return;
    }

    side = parse_side(fields[3], &side_ok);

    if (!side_ok) {
      UART_SendNack("STOP", cmd_id, "BAD_SIDE");
      return;
    }

    r = Belt_CmdUnload(cmd_id, side);
    if (r != BELT_CMD_OK) {
      UART_SendNack("STOP", cmd_id, cmd_result_reason(r));
    }

    return;
  }

  UART_SendNack(fields[1], 0U, "BAD_FORMAT");
}

void UART_SendHelloAck(void)
{
  uart_send_frame("$HELLO_ACK,STM32,OK,good job\r\n");
}

void UART_SendPong(uint32_t seq)
{
  uart_send_frame("$PONG,%lu\r\n", (unsigned long)seq);
}

void UART_SendAckStart(uint8_t cmd_id)
{
  uart_send_frame("$ACK,CMD,START,%u\r\n", cmd_id);
}

void UART_SendAckStop(uint8_t cmd_id)
{
  uart_send_frame("$ACK,CMD,STOP,%u\r\n", cmd_id);
}

void UART_SendAckStopSide(uint8_t cmd_id, BeltSide_t side)
{
  uart_send_frame("$ACK,CMD,STOP,%u,%s\r\n", cmd_id, side_to_str(side));
}

void UART_SendAckEstop(void)
{
  uart_send_frame("$ACK,CMD,ESTOP\r\n");
}

void UART_SendAckResetEstop(void)
{
  uart_send_frame("$ACK,CMD,RESET_ESTOP\r\n");
}

void UART_SendNack(const char *cmd, uint8_t cmd_id, const char *reason)
{
  if (cmd_id > 0U) {
    uart_send_frame("$NACK,CMD,%s,%u,%s\r\n", cmd, cmd_id, reason);
  } else {
    uart_send_frame("$NACK,CMD,%s,%s\r\n", cmd, reason);
  }
}

void UART_SendTelemetry(SystemState_t state, uint8_t active_belt,
                        uint8_t estop_source)
{
  char bits[8];
  const char *ds;

  build_status_bits(bits, sizeof(bits));

  /*
     Theo yeu cau:
     - Telemetry khong hien LEFT/RIGHT nua
     - Chi can STM32 thuc hien dung lenh ROS2
     - Ket qua LEFT/RIGHT se xac nhan bang ACK:
       $ACK,CMD,STOP,id,LEFT
       $ACK,CMD,STOP,id,RIGHT
  */
  ds = "NONE";

  if (state == SYS_ESTOP && estop_source > 0U) {
    uart_send_frame("$TELEMETRY,%s,%s,%u,%s,%u\r\n",
                    state_to_str(state), bits, active_belt, ds, estop_source);
  } else {
    uart_send_frame("$TELEMETRY,%s,%s,%u,%s\r\n",
                    state_to_str(state), bits, active_belt, ds);
  }
}

void UART_SendEventBumper(uint8_t bumper_id)
{
  uart_send_frame("$EVENT,BUMPER,%u,TRIGGER\r\n", bumper_id);
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
  uint16_t next;

  if (s_huart == NULL) {
    return;
  }

  if (huart->Instance == s_huart->Instance) {
    next = (uint16_t)((s_rx_head + 1U) % UART_RX_BUF_SIZE);

    if (next == s_rx_tail) {
      s_rx_overflow = 1U;
    } else {
      s_rx_ring[s_rx_head] = s_uart_rx_byte;
      s_rx_head = next;
    }

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
