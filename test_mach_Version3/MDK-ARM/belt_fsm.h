#ifndef BELT_FSM_H
#define BELT_FSM_H

#include "board_gpio.h"
#include <stdint.h>

#define ESTOP_SRC_EMER     10U
#define ESTOP_SRC_BUMPER1  11U
#define ESTOP_SRC_BUMPER2  12U
#define LOAD_ARMED_TIMEOUT_MS   300000U
#define LOAD_MOVING_TIMEOUT_MS   15000U
#define UNLOAD_MOVING_TIMEOUT_MS 30000U

typedef enum {
  BELT_CMD_OK = 0,
  BELT_CMD_BUSY,
  BELT_CMD_ESTOP,
  BELT_CMD_INVALID,
  BELT_CMD_NO_CARGO,
  BELT_CMD_STOP_LOCK
} BeltCmdResult_t;

typedef enum {
  BELT_EVENT_NONE = 0,
  BELT_EVENT_LOAD_STARTED,     /* gui $ACK,CMD,START,belt_id */
  BELT_EVENT_LOAD_STOPPED,     /* gui $ACK,CMD,STOP,belt_id */
  BELT_EVENT_UNLOAD_DONE,      /* gui $ACK,CMD,STOP,belt_id,LEFT/RIGHT */
  BELT_EVENT_LOAD_NO_CARGO_TIMEOUT,
  BELT_EVENT_LOAD_JAM,
  BELT_EVENT_UNLOAD_JAM
} BeltEventType_t;

typedef struct {
  BeltEventType_t type;
  uint8_t cmd_id;              /* hien tai cmd_id chinh la belt_id: 1 hoac 2 */
  BeltSide_t side;
} BeltEvent_t;

void Belt_Init(void);
void Belt_Tick(void);

SystemState_t Belt_GetState(void);
uint8_t Belt_GetActiveBelt(void);       /* bitmask: 1=belt1, 2=belt2, 3=ca 2 */
uint8_t Belt_GetEstopSource(void);
uint8_t Belt_HasCargo(uint8_t belt_id);

/* Lenh ROS2: cmd_id = belt_id */
BeltCmdResult_t Belt_CmdStartLoad(uint8_t belt_id);
BeltCmdResult_t Belt_CmdUnload(uint8_t belt_id, BeltSide_t side);

/* Nut vat ly */
void Belt_TriggerEstop(uint8_t source_code);
void Belt_OnStopButton(void);
void Belt_OnStartButton(void);   /* Nut RUN vat ly: auto lien tuc ca 2 bang tai: belt1 S1<->S3, belt2 S2<->S4 den khi STOP */
uint8_t Belt_TryResetEstop(void);

/* App lay event de gui UART ACK */
uint8_t Belt_PopEvent(BeltEvent_t *ev);

#endif
