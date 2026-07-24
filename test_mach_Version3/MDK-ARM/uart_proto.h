#ifndef UART_PROTO_H
#define UART_PROTO_H

#include "board_gpio.h"
#include <stdint.h>

#define UART_RX_BUF_SIZE   128U
#define UART_LINE_MAX      96U

void UART_Proto_Init(UART_HandleTypeDef *huart);
void UART_Proto_Poll(void);

void UART_SendHelloAck(void);
void UART_SendPong(uint32_t seq);

void UART_SendAckStart(uint8_t cmd_id);
void UART_SendAckStop(uint8_t cmd_id);
void UART_SendAckStopSide(uint8_t cmd_id, BeltSide_t side);
void UART_SendAckResetEstop(void);
void UART_SendNack(const char *cmd, uint8_t cmd_id, const char *reason);

void UART_SendTelemetry(SystemState_t state, uint8_t active_belt,
                        uint8_t estop_source);
void UART_SendEventBumper(uint8_t bumper_id);

void UART_Proto_StartReceiveIT(void);
void UART_Proto_RxCpltCallback(UART_HandleTypeDef *huart);
void UART_Proto_ErrorCallback(UART_HandleTypeDef *huart);

#endif
