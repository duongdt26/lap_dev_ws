#ifndef UART_PROTO_H
#define UART_PROTO_H

#include "board_gpio.h"
#include "belt_fsm.h"
#include <stdint.h>

#define UART_RX_RING_SIZE          128U
#define UART_LINE_MAX              96U
#define UART_HEARTBEAT_TIMEOUT_MS  2000U

void UART_Proto_Init(UART_HandleTypeDef *huart);
void UART_Proto_Process(void);
void UART_Proto_Poll(void); /* compatibility alias */
void UART_Proto_RxByte(uint8_t byte);

uint8_t UART_Proto_LinkTimedOut(void);
uint8_t UART_Proto_LinkSeen(void);
void UART_Proto_ClearHeartbeatTimeout(void);

void UART_SendHelloAck(void);
void UART_SendPong(uint32_t seq);

void UART_SendAckStart(uint8_t belt_id, uint32_t seq);                 /* START accepted */
void UART_SendAckStop(uint8_t belt_id, uint32_t seq);                  /* legacy */
void UART_SendAckStopSide(uint8_t belt_id, BeltSide_t side, uint32_t seq);
void UART_SendAckUnloadAccepted(uint8_t belt_id, BeltSide_t side, uint32_t seq);
void UART_SendAckManualRunAccepted(uint8_t belt_id, BeltSide_t side, uint32_t seq);
void UART_SendAckManualStop(uint8_t belt_id, uint32_t seq);
void UART_SendAckResetEstop(void);
void UART_SendAckResetFault(void);
void UART_SendAckReady(void);
void UART_SendAckReadySeq(uint32_t seq);
void UART_SendAckResetSeq(const char *what, uint32_t seq);
void UART_SendNack(const char *cmd, uint8_t belt_id, uint32_t seq, const char *reason);

void UART_SendTelemetry(SystemState_t state, uint8_t active_belt,
                        BeltDirection_t dir, uint8_t estop_source);
void UART_SendEventBumper(uint8_t bumper_id);
void UART_SendEventEstop(uint8_t source_code);
void UART_SendEventStopLock(uint8_t locked);
void UART_SendEventReady(void);
void UART_SendEventLoadDetected(uint8_t belt_id, uint8_t source_sensor, uint8_t target_sensor, uint32_t seq);
void UART_SendEventLoadDone(uint8_t belt_id, uint8_t cargo_sensor, uint32_t seq);
void UART_SendEventUnloadDone(uint8_t belt_id, BeltSide_t side, uint8_t exit_sensor, uint32_t seq);
void UART_SendEventManualRun(uint8_t belt_id, BeltSide_t side, uint32_t seq);
void UART_SendEventManualStop(uint8_t belt_id, uint32_t seq);
void UART_SendEventFault(uint8_t belt_id, BeltFaultCode_t fault, uint32_t seq);
void UART_SendEventCommLost(void);
void UART_SendEventReset(const char *what);

void UART_Proto_StartReceiveIT(void);
void UART_Proto_RxCpltCallback(UART_HandleTypeDef *huart);
void UART_Proto_ErrorCallback(UART_HandleTypeDef *huart);

#endif
